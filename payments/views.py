import hashlib
import json
import logging
import uuid

from django.conf import settings
from rest_framework.decorators import api_view, authentication_classes
from rest_framework.response import Response

from core.auth import require_user
from core.errors import ApiError
from core.models import SiteSettings

from .amounts import format_units, to_units
from .gateways import plisio, sandbox
from .models import PaymentInvoice
from .services import apply_payment_event, list_currencies

log = logging.getLogger(__name__)


@api_view(['GET'])
def currencies(request):
    return Response({
        'currencies': list_currencies(),
        'invoiceTtlMinutes': SiteSettings.get().invoice_ttl_minutes,
        'sandbox': settings.PAYMENT_PROVIDER == 'sandbox',
    })


def _sandbox_apply(payload: dict):
    if not payload.get('eventId') or not payload.get('invoiceId') or not payload.get('status'):
        raise ApiError(400, 'Missing fields', code='invalid_payload')
    if payload['status'] not in ('detected', 'confirming', 'confirmed', 'underpaid', 'expired', 'failed'):
        raise ApiError(400, 'Invalid status', code='invalid_payload')
    inv = PaymentInvoice.objects.filter(pk=payload['invoiceId'], sandbox=True).first()
    if not inv:
        raise ApiError(404, 'فاکتور یافت نشد.', code='invoice_not_found')
    return apply_payment_event(
        event_id=f"sandbox:{payload['eventId']}",
        invoice_id=inv.id,
        status=payload['status'],
        currency=payload.get('currency'),
        network=payload.get('network'),
        amount_received=payload.get('amountReceived'),
        tx_hash=payload.get('txHash'),
        confirmations=payload.get('confirmations'),
        payload=payload,
    )


@api_view(['POST'])
@authentication_classes([])
def sandbox_webhook(request):
    """Sandbox gateway webhook. Header X-Signature = hex HMAC-SHA256(raw body, SANDBOX_WEBHOOK_SECRET)."""
    if settings.PAYMENT_PROVIDER != 'sandbox':
        raise ApiError(404, 'Not found')
    raw = request.body
    if not sandbox.verify(raw, request.headers.get('X-Signature')):
        raise ApiError(401, 'Invalid signature', code='invalid_signature')
    try:
        payload = json.loads(raw)
    except ValueError:
        raise ApiError(400, 'Invalid JSON', code='invalid_json')
    return Response(_sandbox_apply(payload))


@api_view(['POST'])
@authentication_classes([])
def plisio_callback(request):
    """Plisio status callback (callback_url has ?json=true)."""
    if settings.PAYMENT_PROVIDER != 'plisio':
        raise ApiError(404, 'Not found')
    data = request.data if isinstance(request.data, dict) else {}
    data = dict(data)
    if not plisio.verify_callback(data):
        log.warning('Plisio callback with invalid verify_hash: %s', {k: data.get(k) for k in ('txn_id', 'order_number', 'status')})
        return Response({'detail': 'invalid signature'}, status=422)

    status_raw = str(data.get('status') or '')
    status = plisio.STATUS_MAP.get(status_raw)
    inv = PaymentInvoice.objects.filter(pk=str(data.get('order_number') or ''), provider='plisio').first()
    if not inv or (inv.provider_ref and str(data.get('txn_id')) != inv.provider_ref and not data.get('switch_id')):
        log.warning('Plisio callback for unknown invoice: %s', data.get('order_number'))
        return Response({'ok': True})  # acknowledge so Plisio stops retrying; nothing to do
    if not status or status == 'awaiting_payment':
        return Response({'ok': True})

    # Partial payment that ran out of time → underpaid (money is held, needs support)
    amount_received = None
    try:
        total = to_units(str(data.get('amount') or inv.amount_crypto), 8)
        pending = to_units(str(data.get('pending_amount') or '0'), 8)
        if data.get('pending_amount') is not None:
            amount_received = format_units(max(0, total - pending), 8)
            if status == 'expired' and 0 < total - pending < total:
                status = 'underpaid'
    except ValueError:
        pass

    tx_urls = data.get('tx_urls') or []
    if isinstance(tx_urls, str):
        try:
            tx_urls = json.loads(tx_urls)
        except ValueError:
            tx_urls = [tx_urls]
    explorer = tx_urls[-1] if isinstance(tx_urls, list) and tx_urls else None

    try:
        confirmations = int(data.get('confirmations')) if data.get('confirmations') not in (None, '') else None
    except (TypeError, ValueError):
        confirmations = None

    fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:32]
    try:
        result = apply_payment_event(
            event_id=f'plisio:{fingerprint}',
            invoice_id=inv.id,
            status=status,
            amount_received=amount_received,
            confirmations=confirmations,
            explorer_url=explorer,
            payload=data,
            trust_status=True,
        )
    except ApiError as e:
        log.error('Plisio callback rejected for %s: %s', inv.id, e.payload)
        return Response({'ok': False})
    return Response(result)


# ---------------------------------------------------------------- dev only

@api_view(['POST'])
def dev_simulate(request, order_id):
    """DEVELOPMENT ONLY: drives the sandbox gateway through the same verified event path."""
    if not settings.DEBUG or settings.PAYMENT_PROVIDER != 'sandbox':
        raise ApiError(404, 'Not found')
    from orders.dto import order_dto
    from orders.services import dev_fulfill, get_owned_order

    user = require_user(request)
    order = get_owned_order(order_id, user)
    kind = str(request.data.get('event') or '')

    if kind == 'fulfill':
        dev_fulfill(order)
        return Response(order_dto(get_owned_order(order_id, user)))

    inv = order.current_invoice
    if not inv:
        raise ApiError(409, 'No invoice')
    d = max(8, len(inv.amount_crypto.partition('.')[2]))
    expected = to_units(inv.amount_crypto, d)
    steps = {
        'detected': ('detected', None, 0),
        'confirming': ('confirming', None, max(1, inv.confirmations_required // 2)),
        'confirmed': ('confirmed', expected, None),
        'overpaid': ('confirmed', expected + expected // 10, None),
        'underpaid': ('confirmed', expected * 7 // 10, None),
        'expired': ('expired', None, None),
        'failed': ('failed', None, None),
    }
    if kind not in steps:
        raise ApiError(400, 'Unknown event')
    status, amount, conf = steps[kind]
    payload = {
        'eventId': f'sim_{uuid.uuid4()}',
        'invoiceId': inv.id,
        'status': status,
        'currency': inv.currency,
        'network': inv.network,
        'amountReceived': format_units(amount, d) if amount is not None else None,
        'txHash': f'0xSAMPLE{uuid.uuid4().hex}' if kind in ('detected', 'confirming', 'confirmed', 'overpaid', 'underpaid') else None,
        'confirmations': conf,
    }
    raw = json.dumps(payload).encode()
    assert sandbox.verify(raw, sandbox.sign(raw))  # same signed path a gateway would use
    _sandbox_apply(payload)
    return Response(order_dto(get_owned_order(order_id, user)))
