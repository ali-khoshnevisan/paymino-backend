import logging

from django.db import transaction
from django.db.models import Count, Prefetch

from catalog.models import GiftCode
from core import mail
from core.errors import ApiError
from core.models import Counter
from core.utils import now
from payments.services import _add_event, move_order, refresh_invoice_expiry

from .models import Delivery, Order, OrderEvent, OrderItem

log = logging.getLogger(__name__)


def order_queryset():
    return Order.objects.select_related('current_invoice', 'user').prefetch_related(
        Prefetch('items', queryset=OrderItem.objects.prefetch_related('deliveries')),
        'events',
    )


def get_owned_order(order_id, user) -> Order:
    order = order_queryset().filter(pk=order_id, user=user).first()
    # Same 404 for "missing" and "not yours" so order ids cannot be probed.
    if not order:
        raise ApiError(404, 'سفارش یافت نشد.', code='order_not_found')
    if order.current_invoice and order.current_invoice.status == 'awaiting_payment':
        refresh_invoice_expiry(order)
        order = order_queryset().get(pk=order.pk)
    return order


def next_order_number() -> str:
    return f'PM-{Counter.next("order", 10240)}'


def _items_fully_delivered(order) -> bool:
    # Fresh query: callers may hold prefetched (stale) deliveries
    for it in OrderItem.objects.filter(order_id=order.pk).annotate(n=Count('deliveries')):
        n = it.n
        if it.type == 'gift_card' and n < it.quantity:
            return False
        if it.type != 'gift_card' and n < 1:
            return False
    return True


def complete_if_delivered(order, actor=None, message='سفارش تکمیل شد.') -> bool:
    if order.status == 'processing' and _items_fully_delivered(order):
        if move_order(order, 'completed', message, actor=actor):
            mail.send(
                order.user.email,
                f'سفارش {order.number} تکمیل شد',
                f'سلام {order.user.full_name}\n\nسفارش {order.number} تکمیل شد. جزئیات و کدها در پنل کاربری شما:\n{mail.frontend(f"/account/orders/{order.id}")}',
            )
            return True
    return False


def fulfill_order(order_pk: str):
    """Auto-deliver gift card codes from stock. Anything that can't be auto-delivered waits for an admin."""
    with transaction.atomic():
        order = Order.objects.select_for_update().select_related('user').get(pk=order_pk)
        if order.status != 'processing':
            return
        short = []
        delivered_any = False
        for it in order.items.select_related('variant').all():
            if it.type != 'gift_card' or it.stock_mode != 'codes' or not it.variant_id:
                continue
            need = it.quantity - it.deliveries.count()
            if need <= 0:
                continue
            codes = list(
                GiftCode.objects.select_for_update(skip_locked=True)
                .filter(variant_id=it.variant_id, status='available')
                .order_by('created_at', 'id')[:need]
            )
            at = now()
            for c in codes:
                c.status, c.order_item, c.delivered_at = 'delivered', it, at
                c.save(update_fields=['status', 'order_item', 'delivered_at'])
                Delivery.objects.create(item=it, kind='code', value=c.code)
                delivered_any = True
            if len(codes) < need:
                short.append(f'{it.product_name} — {it.variant_label}: {need - len(codes)} کد کم است')

        if short:
            order.needs_review = True
            order.save(update_fields=['needs_review', 'updated_at'])
            _add_event(order, 'موجودی کد کافی نبود: ' + '؛ '.join(short), internal=True)
        if delivered_any:
            if not complete_if_delivered(order, message='کد گیفت کارت در پنل شما قرار گرفت.'):
                _add_event(order, 'بخشی از سفارش تحویل شد؛ باقی موارد در حال انجام است.')


def dev_fulfill(order):
    if order.status != 'processing':
        raise ApiError(409, 'Order is not processing')
    with transaction.atomic():
        for it in OrderItem.objects.filter(order_id=order.pk).annotate(n=Count('deliveries')):
            if it.type == 'gift_card':
                for _ in range(it.quantity - it.n):
                    Delivery.objects.create(item=it, kind='code', value=f'SAMPLE-{now().microsecond:04d}-XXXX-XXXX')
            elif not it.n:
                Delivery.objects.create(item=it, kind='service_note', value='اشتراک روی حساب شما فعال شد (نمونه).')
        complete_if_delivered(order)
