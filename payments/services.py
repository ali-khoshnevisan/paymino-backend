import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction

from core.errors import ApiError
from core.models import SiteSettings
from core.utils import iso, now
from orders.status import can_transition_order, can_transition_payment

from .amounts import to_units, toman_to_crypto
from .gateways import get_gateway
from .models import PaymentCurrency, PaymentInvoice, PaymentNetwork, ProcessedEvent

log = logging.getLogger(__name__)

PAYMENT_MESSAGES = {
    'awaiting_payment': 'در انتظار پرداخت',
    'detected': 'تراکنش شما در شبکه شناسایی شد.',
    'confirming': 'تراکنش در حال دریافت تأییدهای شبکه است.',
    'confirmed': 'پرداخت تأیید شد.',
    'expired': 'مهلت پرداخت به پایان رسید.',
    'underpaid': 'مبلغ دریافتی کمتر از مبلغ فاکتور است.',
    'failed': 'پرداخت ناموفق بود.',
    'refunded': 'مبلغ پرداختی بازگردانده شد.',
}


def _fmt_decimal(d: Decimal) -> float | int:
    f = float(d)
    return int(f) if f.is_integer() else f


def list_currencies():
    out = []
    for c in PaymentCurrency.objects.filter(is_active=True).prefetch_related('networks'):
        nets = [n for n in c.networks.all() if n.is_active]
        if not nets:
            continue
        out.append({
            'code': c.code,
            'name': c.name,
            'rateToman': int(c.rate_toman),
            'rateUpdatedAt': iso(c.rate_updated_at),
            'networks': [
                {
                    'code': n.code,
                    'name': n.name,
                    'minAmount': _fmt_decimal(n.min_amount),
                    'confirmationsRequired': n.confirmations_required,
                    'networkFeeNote': n.network_fee_note,
                }
                for n in nets
            ],
        })
    return out


def find_network(currency_code: str, network_code: str) -> PaymentNetwork | None:
    return (
        PaymentNetwork.objects.select_related('currency')
        .filter(currency__code=currency_code, code=network_code, is_active=True, currency__is_active=True)
        .first()
    )


def invoice_dto(inv: PaymentInvoice | None):
    if inv is None:
        return None
    return {
        'id': inv.id,
        'orderId': inv.order_id,
        'provider': inv.provider,
        'currency': inv.currency,
        'network': inv.network,
        'amountCrypto': inv.amount_crypto,
        'amountReceived': inv.amount_received,
        'rateToman': int(inv.rate_toman),
        'totalToman': int(inv.total_toman),
        'address': inv.address,
        'memo': inv.memo,
        'paymentUri': inv.payment_uri,
        'expiresAt': iso(inv.expires_at),
        'createdAt': iso(inv.created_at),
        'status': inv.status,
        'confirmations': inv.confirmations,
        'confirmationsRequired': inv.confirmations_required,
        'txHash': inv.tx_hash,
        'explorerUrl': inv.explorer_url,
        'sandbox': inv.sandbox,
    }


def create_invoice(order, currency_code: str, network_code: str) -> PaymentInvoice:
    """Create a gateway invoice for the order's locked Toman total at the current rate."""
    net = find_network(currency_code, network_code)
    if not net:
        raise ApiError(400, 'ارز یا شبکه انتخاب‌شده پشتیبانی نمی‌شود.', code='unsupported_currency')
    cur = net.currency
    amount = toman_to_crypto(int(order.total_toman), int(cur.rate_toman), cur.decimals)
    if to_units(amount, 8) < to_units(str(net.min_amount), 8):
        min_str = f'{net.min_amount.normalize():f}'
        raise ApiError(400, f'حداقل مبلغ پرداخت در این شبکه {min_str} {cur.code} است.', code='below_minimum')

    gateway = get_gateway()
    inv = PaymentInvoice(
        order=order, provider=gateway.name, currency=cur.code, network=net.code, amount_crypto=amount,
        rate_toman=cur.rate_toman, total_toman=order.total_toman, address='', expires_at=now(),
        confirmations_required=net.confirmations_required, sandbox=gateway.sandbox,
    )
    ttl = SiteSettings.get().invoice_ttl_minutes
    g = gateway.create_invoice(inv, net, ttl, order, order.user)
    inv.address = g.address
    inv.amount_crypto = g.amount_crypto
    inv.expires_at = g.expires_at
    inv.confirmations_required = g.confirmations_required
    inv.provider_ref = g.provider_ref
    inv.memo = g.memo
    inv.payment_uri = g.payment_uri
    inv.raw = g.raw
    inv.save()
    return inv


def _add_event(order, message, status=None, payment_status=None, internal=False, actor=None):
    from orders.models import OrderEvent
    OrderEvent.objects.create(order=order, status=status, payment_status=payment_status, message=message, internal=internal, actor=actor)


def move_order(order, to: str, message: str, actor=None) -> bool:
    if order.status != to and can_transition_order(order.status, to):
        order.status = to
        order.save(update_fields=['status', 'updated_at'])
        _add_event(order, message, status=to, actor=actor)
        return True
    return False


def apply_payment_event(*, event_id: str, invoice_id: str, status: str, currency: str | None = None,
                        network: str | None = None, amount_received: str | None = None, tx_hash: str | None = None,
                        confirmations: int | None = None, explorer_url: str | None = None, payload: dict | None = None,
                        trust_status: bool = False):
    """
    Apply a VERIFIED gateway event to an invoice and its order. Idempotent per event_id.
    trust_status=True: the gateway itself judged the amount (e.g. Plisio "completed").
    """
    from orders.models import Order
    from orders.services import fulfill_order

    with transaction.atomic():
        inv = PaymentInvoice.objects.select_for_update().filter(pk=invoice_id).first()
        if not inv:
            raise ApiError(404, 'فاکتور یافت نشد.', code='invoice_not_found')
        try:
            with transaction.atomic():
                ProcessedEvent.objects.create(event_id=event_id[:200], invoice=inv, payload=payload or {}, result='pending')
        except IntegrityError:
            return {'duplicate': True}

        if (currency and currency != inv.currency) or (network and network != inv.network):
            ProcessedEvent.objects.filter(event_id=event_id[:200]).update(result='mismatch')
            raise ApiError(400, 'ارز یا شبکه رویداد با فاکتور مطابقت ندارد.', code='mismatch')

        order = Order.objects.select_for_update().get(pk=inv.order_id)
        note = None
        decimals = max(8, len(inv.amount_crypto.partition('.')[2]))
        if amount_received is not None:
            inv.amount_received = amount_received
            if not trust_status:
                received, expected = to_units(amount_received, decimals), to_units(inv.amount_crypto, decimals)
                if status == 'confirmed' and received < expected:
                    status = 'underpaid'
                elif status == 'confirmed' and received > expected:
                    note = 'مبلغ اضافه دریافت شد و برای بررسی به پشتیبانی ارجاع شد.'

        if not can_transition_payment(inv.status, status):
            ProcessedEvent.objects.filter(event_id=event_id[:200]).update(result='ignored')
            inv.save(update_fields=['amount_received'])
            return {'ignored': True}

        late = inv.status == 'expired' and status in ('detected', 'confirming', 'confirmed', 'underpaid')
        inv.status = status
        if tx_hash:
            inv.tx_hash = tx_hash
        if explorer_url:
            inv.explorer_url = explorer_url
        if confirmations is not None:
            inv.confirmations = confirmations
        if status == 'confirmed':
            inv.confirmations = max(inv.confirmations, inv.confirmations_required)
        inv.save()

        is_current = order.current_invoice_id == inv.id
        if not is_current:
            if status in ('detected', 'confirming', 'confirmed', 'underpaid') and order.status in ('pending_payment', 'payment_verification'):
                # Customer paid a superseded invoice: adopt it, retire the newer unpaid one.
                if order.current_invoice_id:
                    PaymentInvoice.objects.filter(pk=order.current_invoice_id, status='awaiting_payment').update(status='expired')
                order.current_invoice = inv
                order.payment_currency, order.payment_network = inv.currency, inv.network
                is_current = True
            else:
                order.needs_review = True
                order.save(update_fields=['needs_review', 'updated_at'])
                _add_event(order, f'رویداد پرداخت «{status}» برای فاکتور قدیمی {inv.id} دریافت شد.', internal=True)
                ProcessedEvent.objects.filter(event_id=event_id[:200]).update(result='flagged')
                return {'ok': True, 'flagged': True}

        order.payment_status = status
        if late or note or status == 'underpaid':
            order.needs_review = True
        order.save()
        _add_event(order, PAYMENT_MESSAGES[status], payment_status=status)
        if note:
            _add_event(order, note)
        if late:
            _add_event(order, 'پرداخت پس از پایان مهلت فاکتور دریافت شد.', internal=True)

        if status in ('detected', 'confirming', 'underpaid'):
            move_order(order, 'payment_verification', 'سفارش در مرحله بررسی پرداخت است.')
        elif status == 'confirmed':
            if order.status == 'cancelled':
                _add_event(order, 'پرداخت برای سفارش لغوشده تأیید شد — بازپرداخت یا انجام دستی لازم است.', internal=True)
            else:
                if order.status == 'pending_payment':
                    move_order(order, 'payment_verification', 'سفارش در مرحله بررسی پرداخت است.')
                move_order(order, 'paid', 'پرداخت سفارش تأیید شد.')
                move_order(order, 'processing', 'سفارش در حال انجام است.')
        elif status in ('expired', 'failed'):
            move_order(order, 'pending_payment', 'برای ادامه، فاکتور پرداخت جدید ایجاد کنید.')

        ProcessedEvent.objects.filter(event_id=event_id[:200]).update(result='ok')
        should_fulfill = status == 'confirmed' and order.status == 'processing'

    if should_fulfill:
        fulfill_order(order.pk)
    return {'ok': True}


def refresh_invoice_expiry(order):
    """Lazily expire stale invoices. Real-gateway invoices get a grace period (their own expiry callback normally arrives)."""
    inv = order.current_invoice
    if not inv or inv.status != 'awaiting_payment':
        return
    grace = timedelta(minutes=0 if inv.sandbox else settings.PLISIO_EXPIRY_GRACE_MINUTES)
    if inv.expires_at + grace < now():
        apply_payment_event(event_id=f'expiry_{inv.id}', invoice_id=inv.id, status='expired')
        order.refresh_from_db()
