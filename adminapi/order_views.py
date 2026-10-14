from django.db import transaction
from django.db.models import Q
from rest_framework.response import Response

from core import mail
from core.errors import ApiError, field_errors
from core.pagination import paginate
from core.utils import iso, normalize_digits
from orders.dto import order_dto
from orders.models import Delivery, Order, OrderItem
from orders.services import complete_if_delivered, fulfill_order, order_queryset
from orders.status import ORDER_STATUSES, ORDER_TRANSITIONS, PAYMENT_STATUSES
from payments.models import PaymentInvoice
from payments.services import _add_event, invoice_dto, move_order

from .common import staff_view
from .dto import admin_order_row

ORDER_CODES = [c for c, _ in ORDER_STATUSES]
STATUS_LABELS = dict(ORDER_STATUSES)

# Admin-facing messages shown to the customer on each manual transition
CUSTOMER_MESSAGES = {
    'processing': 'سفارش در حال انجام است.',
    'awaiting_customer_info': 'برای ادامه انجام سفارش به اطلاعات بیشتری از شما نیاز داریم. لطفاً پیام پشتیبانی را بررسی کنید.',
    'completed': 'سفارش تکمیل شد.',
    'failed': 'انجام سفارش ممکن نشد. پشتیبانی برای بازپرداخت با شما هماهنگ می‌کند.',
    'cancelled': 'سفارش لغو شد.',
    'refund_pending': 'درخواست بازپرداخت ثبت شد.',
    'refunded': 'مبلغ سفارش بازگردانده شد.',
    'paid': 'پرداخت سفارش تأیید شد.',
    'payment_verification': 'سفارش در مرحله بررسی پرداخت است.',
    'pending_payment': 'سفارش در انتظار پرداخت است.',
}


def admin_order_detail_dto(o):
    d = order_dto(o)
    d['needsReview'] = o.needs_review
    d['adminNote'] = o.admin_note
    d['user'] = {'id': o.user_id, 'fullName': o.user.full_name, 'email': o.user.email, 'phone': o.user.phone}
    d['allEvents'] = [
        {'at': iso(e.at), 'status': e.status, 'paymentStatus': e.payment_status, 'message': e.message,
         'internal': e.internal, 'actor': e.actor.full_name if e.actor_id else None}
        for e in o.events.select_related('actor').all()
    ]
    d['invoices'] = [invoice_dto(i) | {'providerRef': i.provider_ref} for i in PaymentInvoice.objects.filter(order=o).order_by('-created_at')]
    d['allowedTransitions'] = ORDER_TRANSITIONS.get(o.status, [])
    for item, src in zip(d['items'], o.items.all()):
        item['stockMode'] = src.stock_mode
        item['variantId'] = src.variant_id
    d['tickets'] = [{'id': t.id, 'number': t.number, 'status': t.status} for t in o.tickets.all()]
    return d


def _load(pk):
    o = order_queryset().filter(pk=pk).first()
    if not o:
        raise ApiError(404, 'سفارش یافت نشد.')
    return o


@staff_view(['GET'])
def orders(request):
    q = request.query_params
    qs = order_queryset().order_by('-created_at')
    if q.get('status') in ORDER_CODES:
        qs = qs.filter(status=q['status'])
    elif q.get('status') == 'action':
        qs = qs.filter(Q(status__in=['paid', 'processing', 'awaiting_customer_info', 'refund_pending', 'payment_verification']) | Q(needs_review=True))
    if q.get('paymentStatus') in [c for c, _ in PAYMENT_STATUSES]:
        qs = qs.filter(payment_status=q['paymentStatus'])
    if q.get('needsReview') == '1':
        qs = qs.filter(needs_review=True)
    if q.get('user'):
        qs = qs.filter(user_id=q['user'])
    if q.get('q'):
        term = normalize_digits(q['q'].strip())
        qs = qs.filter(Q(number__iexact=term) | Q(number__iexact=f'PM-{term}') | Q(id=term) | Q(user__email__icontains=term)
                       | Q(user__full_name__icontains=term) | Q(user__phone__icontains=term) | Q(invoices__tx_hash__iexact=term)
                       | Q(invoices__address__iexact=term)).distinct()
    count, items = paginate(request, qs, 25, 100)
    return Response({'count': count, 'results': [admin_order_row(o) for o in items]})


@staff_view(['GET', 'PATCH'])
def order_detail(request, pk):
    o = _load(pk)
    if request.method == 'PATCH':
        fields = []
        if 'needsReview' in request.data:
            o.needs_review = request.data.get('needsReview') is True
            fields.append('needs_review')
        if 'adminNote' in request.data:
            o.admin_note = str(request.data.get('adminNote') or '')[:5000]
            fields.append('admin_note')
        if fields:
            o.save(update_fields=fields + ['updated_at'])
        o = _load(pk)
    return Response(admin_order_detail_dto(o))


@staff_view(['POST'])
def order_status(request, pk):
    to = request.data.get('status')
    message = str(request.data.get('message') or '').strip()[:1000]
    notify = request.data.get('notify') is True
    if to not in ORDER_CODES:
        field_errors({'status': ['وضعیت نامعتبر است.']})
    with transaction.atomic():
        o = Order.objects.select_for_update(of=('self',)).select_related('user', 'current_invoice').get(pk=_load(pk).pk)
        if to == o.status:
            raise ApiError(409, 'سفارش هم‌اکنون در این وضعیت است.', code='same_status')
        if to not in ORDER_TRANSITIONS.get(o.status, []):
            raise ApiError(409, f'انتقال از «{STATUS_LABELS[o.status]}» به «{STATUS_LABELS[to]}» مجاز نیست.', code='invalid_transition')
        if to in ('paid', 'processing') and o.payment_status != 'confirmed':
            # Manual payment confirmation (e.g. checked on-chain by hand) is recorded explicitly
            if request.data.get('confirmPayment') is not True:
                raise ApiError(409, 'پرداخت این سفارش تأیید نشده است. برای تأیید دستی، گزینه «تأیید دستی پرداخت» را بزنید.', code='payment_not_confirmed')
            o.payment_status = 'confirmed'
            o.save(update_fields=['payment_status', 'updated_at'])
            _add_event(o, 'پرداخت سفارش به‌صورت دستی تأیید شد.', payment_status='confirmed', internal=True, actor=request.user)
        move_order(o, to, message or CUSTOMER_MESSAGES.get(to, STATUS_LABELS[to]), actor=request.user)
        if to == 'refunded' and o.payment_status == 'confirmed':
            o.payment_status = 'refunded'
            o.save(update_fields=['payment_status', 'updated_at'])
            _add_event(o, 'مبلغ پرداختی بازگردانده شد.', payment_status='refunded', actor=request.user)
        if to == 'cancelled' and o.current_invoice and o.current_invoice.status == 'awaiting_payment':
            o.current_invoice.status = 'expired'
            o.current_invoice.save(update_fields=['status'])
    if notify:
        mail.send(o.user.email, f'به‌روزرسانی سفارش {o.number}',
                  f'وضعیت سفارش {o.number}: {STATUS_LABELS[to]}\n\n{message or CUSTOMER_MESSAGES.get(to, "")}\n\n{mail.frontend(f"/account/orders/{o.id}")}')
    if to == 'processing':
        fulfill_order(o.pk)
    return Response(admin_order_detail_dto(_load(pk)))


@staff_view(['POST'])
def order_delivery(request, pk):
    item_id = request.data.get('itemId')
    kind = request.data.get('kind')
    value = str(request.data.get('value') or '').strip()
    complete = request.data.get('complete') is not False
    errors = {}
    if kind not in ('code', 'service_note'):
        errors['kind'] = ['نوع تحویل نامعتبر است.']
    if not value or len(value) > 5000:
        errors['value'] = ['متن تحویل را وارد کنید.']
    if errors:
        field_errors(errors)
    with transaction.atomic():
        o = Order.objects.select_for_update().select_related('user').get(pk=_load(pk).pk)
        if o.status not in ('processing', 'awaiting_customer_info', 'completed'):
            raise ApiError(409, 'تحویل فقط برای سفارش‌های پرداخت‌شده و در حال انجام ممکن است.', code='not_deliverable')
        item = OrderItem.objects.filter(pk=item_id, order=o).first()
        if not item:
            field_errors({'itemId': ['قلم سفارش نامعتبر است.']})
        values = [v.strip() for v in value.splitlines() if v.strip()] if kind == 'code' else [value]
        for v in values:
            Delivery.objects.create(item=item, kind=kind, value=v, created_by=request.user)
        _add_event(o, f'تحویل دستی برای «{item.product_name} — {item.variant_label}» ثبت شد.', internal=True, actor=request.user)
        if o.status == 'awaiting_customer_info':
            move_order(o, 'processing', CUSTOMER_MESSAGES['processing'], actor=request.user)
        if complete:
            complete_if_delivered(o, actor=request.user)
    return Response(admin_order_detail_dto(_load(pk)))


@staff_view(['POST'])
def order_note(request, pk):
    o = _load(pk)
    msg = str(request.data.get('message') or '').strip()
    if not msg or len(msg) > 2000:
        field_errors({'message': ['متن یادداشت را وارد کنید.']})
    public = request.data.get('public') is True
    _add_event(o, msg, internal=not public, actor=request.user)
    if public and request.data.get('notify') is True:
        mail.send(o.user.email, f'پیام درباره سفارش {o.number}', f'{msg}\n\n{mail.frontend(f"/account/orders/{o.id}")}')
    return Response(admin_order_detail_dto(_load(pk)))


@staff_view(['POST'])
def order_autofulfill(request, pk):
    o = _load(pk)
    if o.status != 'processing':
        raise ApiError(409, 'فقط سفارش‌های در حال انجام قابل تحویل خودکار هستند.', code='not_processing')
    fulfill_order(o.pk)
    return Response(admin_order_detail_dto(_load(pk)))
