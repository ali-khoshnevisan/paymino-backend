from django.db import IntegrityError, transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response

from catalog.models import Product, products_with_variants
from core.auth import require_user
from core.errors import ApiError, field_errors
from core.models import SiteSettings
from core.utils import EMAIL_RE, as_str, client_ip, throttle
from payments.services import _add_event, create_invoice

from .dto import order_dto, order_list_item
from . import coupons
from .models import Coupon, Order, OrderEvent, OrderItem
from .pricing import build_quote, parse_cart_items, public_quote
from .services import get_owned_order, next_order_number, order_queryset
from .status import ACTIVE_ORDER_STATES, can_transition_order, is_payable


def _coupon_code(request, d):
    return coupons.normalize_code(d.get('couponCode'))


def _limit_misses(request, q):
    """Codes must not be guessable: count unknown or unusable codes per account (or per IP when signed out)."""
    if q['coupon'] and not q['coupon']['valid']:
        user = _user_or_none(request)
        throttle(f"coupon-miss:{user.pk if user else client_ip(request)}", 20, 600)


def _user_or_none(request):
    return request.user if getattr(request, 'user', None) is not None and request.user.is_authenticated else None


@api_view(['POST'])
def quote(request):
    d = request.data if isinstance(request.data, dict) else {}
    items = parse_cart_items(d.get('items'))
    q = build_quote(items, _coupon_code(request, d), _user_or_none(request))
    _limit_misses(request, q)
    return Response(public_quote(q))


@api_view(['GET', 'POST'])
def orders(request):
    user = require_user(request)
    if request.method == 'GET':
        flt = request.query_params.get('status', 'all')
        qs = order_queryset().filter(user=user)
        if flt == 'active':
            qs = qs.filter(status__in=ACTIVE_ORDER_STATES)
        elif flt == 'completed':
            qs = qs.exclude(status__in=ACTIVE_ORDER_STATES)
        results = []
        for o in qs[:200]:
            if o.current_invoice and o.current_invoice.status == 'awaiting_payment':
                o = get_owned_order(o.pk, user)
            results.append(order_list_item(o))
        return Response({'count': len(results), 'results': results})
    return _create_order(request, user)


def _create_order(request, user):
    idem = (request.headers.get('Idempotency-Key') or '')[:80] or None
    if idem:
        existing = Order.objects.filter(user=user, idempotency_key=idem).first()
        if existing:
            return Response(order_dto(get_owned_order(existing.pk, user)))

    if not SiteSettings.get().orders_enabled:
        raise ApiError(503, 'ثبت سفارش موقتاً غیرفعال است. کمی بعد دوباره تلاش کنید.', code='orders_disabled')
    throttle(f'order:{user.pk}', 20, 3600)

    d = request.data if isinstance(request.data, dict) else {}
    if d.get('acceptedTerms') is not True:
        field_errors({'acceptedTerms': ['برای ثبت سفارش، پذیرش قوانین الزامی است.']})
    items = parse_cart_items(d.get('items'))
    if not items:
        raise ApiError(400, 'سبد خرید خالی است.', code='empty_cart')

    products = {p.id: p for p in products_with_variants(Product.objects.filter(pk__in={i['productId'] for i in items}))}
    errors = {}
    for it in items:
        p = products.get(it['productId'])
        if not p:
            continue
        for f in p.required_fields or []:
            key, label = f.get('key'), f.get('label', '')
            value = as_str(it['fields'].get(key)).strip()
            ek = f"{it['lineId']}.{key}"
            if f.get('required') and not value:
                errors[ek] = [f'{label} الزامی است.']
            elif value and f.get('type') == 'email' and not EMAIL_RE.match(value):
                errors[ek] = ['ایمیل معتبر وارد کنید.']
            elif len(value) > 200:
                errors[ek] = ['مقدار واردشده بیش از حد طولانی است.']
    if errors:
        field_errors(errors)

    code = _coupon_code(request, d)
    q = build_quote(items, code, user)
    if code and not q['coupon']['valid']:
        _limit_misses(request, q)
        raise ApiError(409, q['coupon']['message'], code='coupon_invalid', quote=public_quote(q))
    blocking = [l for l in q['lines'] if not l['available'] or (l.get('issue') or {}).get('code') in ('price_changed', 'quantity_adjusted')]
    try:
        expected = int(d.get('expectedTotalToman'))
    except (TypeError, ValueError):
        expected = -1
    if blocking or q['totalToman'] != expected:
        raise ApiError(409, 'قیمت یا موجودی برخی اقلام تغییر کرده است. لطفاً سبد خرید را دوباره بررسی کنید.', code='quote_changed', quote=public_quote(q))

    try:
        with transaction.atomic():
            coupon = q['_coupon']
            if coupon:
                # Lock the code and count its uses again, so two orders can't both take the last use
                coupon = Coupon.objects.select_for_update().get(pk=coupon.pk)
                try:
                    still = coupons.check(coupon, sum(l['lineTotalToman'] for l in q['lines']), user=user)
                except coupons.CouponError as e:
                    raise ApiError(409, e.message, code='coupon_invalid', quote=public_quote(build_quote(items, code, user)))
                if still != q['couponDiscountToman']:
                    raise ApiError(409, 'مبلغ تخفیف این کد تغییر کرده است. سبد خرید را دوباره بررسی کنید.', code='quote_changed',
                                   quote=public_quote(build_quote(items, code, user)))
            order = Order.objects.create(
                number=next_order_number(), user=user, idempotency_key=idem, status='pending_payment',
                payment_status='awaiting_payment', subtotal_toman=q['subtotalToman'],
                service_fee_toman=q['serviceFeeToman'], discount_toman=q['discountToman'], total_toman=q['totalToman'],
                coupon=coupon, coupon_code=coupon.code if coupon else '', coupon_discount_toman=q['couponDiscountToman'],
            )
            for pos, line in enumerate(q['lines']):
                p = products[line['productId']]
                v = next(x for x in p.variants.all() if x.id == line['variantId'])
                inp = next(i for i in items if i['lineId'] == line['lineId'])
                fields, labels = {}, {}
                for f in p.required_fields or []:
                    fields[f['key']] = as_str(inp['fields'].get(f['key'])).strip()
                    labels[f['key']] = f.get('label', f['key'])
                OrderItem.objects.create(
                    order=order, product=p, variant=v, product_slug=p.slug, product_name=p.name, brand_name=p.brand_name,
                    variant_label=v.label, type=p.type, stock_mode=v.stock_mode, quantity=line['quantity'],
                    unit_price_toman=line['unitPriceToman'], line_total_toman=line['lineTotalToman'],
                    fields=fields, field_labels=labels, position=pos,
                )
            inv = create_invoice(order, as_str(d.get('currency')), as_str(d.get('network')))
            order.current_invoice = inv
            order.payment_currency, order.payment_network = inv.currency, inv.network
            order.save()
            _add_event(order, 'سفارش ثبت شد و فاکتور پرداخت صادر شد.', status='pending_payment', payment_status='awaiting_payment')
    except IntegrityError:
        # Same idempotency key raced in parallel → return the winner
        existing = Order.objects.filter(user=user, idempotency_key=idem).first() if idem else None
        if not existing:
            raise
        return Response(order_dto(get_owned_order(existing.pk, user)))

    return Response(order_dto(get_owned_order(order.pk, user)), status=201)


@api_view(['GET'])
def order_detail(request, order_id):
    user = require_user(request)
    return Response(order_dto(get_owned_order(order_id, user)))


@api_view(['POST'])
def cancel(request, order_id):
    user = require_user(request)
    with transaction.atomic():
        order = Order.objects.select_for_update().filter(pk=order_id, user=user).first()
        if not order:
            raise ApiError(404, 'سفارش یافت نشد.', code='order_not_found')
        cancellable_payment = order.payment_status in (None, 'awaiting_payment', 'expired', 'failed')
        if order.status != 'pending_payment' or not cancellable_payment or not can_transition_order(order.status, 'cancelled'):
            raise ApiError(409, 'این سفارش قابل لغو نیست. برای پیگیری با پشتیبانی تماس بگیرید.', code='not_cancellable')
        inv = order.current_invoice
        if inv and inv.status == 'awaiting_payment':
            inv.status = 'expired'
            inv.save(update_fields=['status'])
        order.status = 'cancelled'
        order.save(update_fields=['status', 'updated_at'])
        _add_event(order, 'سفارش توسط شما لغو شد.', status='cancelled')
    return Response(order_dto(get_owned_order(order_id, user)))


@api_view(['POST'])
def new_invoice(request, order_id):
    user = require_user(request)
    throttle(f'invoice:{user.pk}', 20, 3600)
    get_owned_order(order_id, user)  # 404 + lazy expiry
    with transaction.atomic():
        order = Order.objects.select_for_update(of=('self',)).select_related('current_invoice', 'user').get(pk=order_id)
        if not is_payable(order.status, order.payment_status):
            raise ApiError(409, 'برای این سفارش امکان صدور فاکتور جدید وجود ندارد.', code='not_payable')
        inv = create_invoice(order, as_str(request.data.get('currency')), as_str(request.data.get('network')))
        old = order.current_invoice
        if old and old.status == 'awaiting_payment':
            old.status = 'expired'  # superseded (a late payment to it is still adopted — see apply_payment_event)
            old.save(update_fields=['status'])
        order.current_invoice = inv
        order.payment_status = 'awaiting_payment'
        order.payment_currency, order.payment_network = inv.currency, inv.network
        order.save()
        _add_event(order, 'فاکتور پرداخت جدید صادر شد.', payment_status='awaiting_payment')
    return Response(order_dto(get_owned_order(order_id, user)))
