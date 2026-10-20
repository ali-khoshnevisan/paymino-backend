from django.db.models import Count, Q
from rest_framework.response import Response

from core.errors import ApiError, field_errors
from core.utils import iso
from orders import coupons
from orders.models import Coupon

from .common import Form, staff_view

KINDS = [k for k, _ in Coupon.KINDS]


def coupon_dto(c):
    used = getattr(c, 'used', None)
    return {
        'id': c.id, 'code': c.code, 'kind': c.kind, 'value': int(c.value),
        'maxDiscountToman': int(c.max_discount_toman) if c.max_discount_toman is not None else None,
        'minOrderToman': int(c.min_order_toman), 'startsAt': iso(c.starts_at), 'endsAt': iso(c.ends_at),
        'usageLimit': c.usage_limit, 'perUserLimit': c.per_user_limit, 'isActive': c.is_active, 'note': c.note,
        'usedCount': used if used is not None else coupons.used_count(c), 'label': coupons.label(c), 'createdAt': iso(c.created_at),
    }


def _with_usage(qs):
    return qs.annotate(used=Count('orders', filter=~Q(orders__status='cancelled')))


def _form(data, partial, instance=None):
    f = Form(data, partial)
    if not f.skip('code'):
        code = coupons.normalize_code(data.get('code'))
        if not coupons.CODE_RE.match(code):
            f.err('code', 'بین ۳ تا ۴۰ کاراکتر: حروف انگلیسی، عدد، خط تیره یا زیرخط.')
        elif Coupon.objects.filter(code=code).exclude(pk=getattr(instance, 'pk', None)).exists():
            f.err('code', 'این کد قبلاً ساخته شده است.')
        else:
            f.clean['code'] = code
    f.choice('kind', 'kind', KINDS)
    f.integer('value', 'value', min_value=1, max_value=10**12)
    f.integer('maxDiscountToman', 'max_discount_toman', nullable=True, min_value=1000, max_value=10**12)
    f.integer('minOrderToman', 'min_order_toman', required=False, min_value=0, max_value=10**12)
    f.datetime('startsAt', 'starts_at')
    f.datetime('endsAt', 'ends_at')
    f.integer('usageLimit', 'usage_limit', nullable=True, min_value=1, max_value=10**7)
    f.integer('perUserLimit', 'per_user_limit', nullable=True, min_value=1, max_value=1000)
    f.boolean('isActive', 'is_active')
    f.text('note', 'note', required=False, max_len=255)
    clean = f.raise_if_errors()

    errors = {}
    kind = clean.get('kind', getattr(instance, 'kind', None))
    value = clean.get('value', getattr(instance, 'value', None))
    if kind == 'percent' and value is not None and value > 100:
        errors['value'] = ['درصد تخفیف حداکثر ۱۰۰ است.']
    if kind == 'fixed' and value is not None and value < 1000:
        errors['value'] = ['مبلغ تخفیف دست‌کم ۱٬۰۰۰ تومان است.']
    starts = clean.get('starts_at', getattr(instance, 'starts_at', None))
    ends = clean.get('ends_at', getattr(instance, 'ends_at', None))
    if starts and ends and ends <= starts:
        errors['endsAt'] = ['پایان باید بعد از شروع باشد.']
    if errors:
        field_errors(errors)
    return clean


@staff_view(['GET', 'POST'])
def coupon_list(request):
    if request.method == 'POST':
        c = Coupon.objects.create(**_form(request.data, False))
        return Response(coupon_dto(_with_usage(Coupon.objects.filter(pk=c.pk)).get()), status=201)
    qs = _with_usage(Coupon.objects.all())
    q = coupons.normalize_code(request.query_params.get('q'))
    if q:
        qs = qs.filter(code__contains=q)
    return Response({'count': qs.count(), 'results': [coupon_dto(c) for c in qs[:500]]})


@staff_view(['GET', 'PATCH', 'DELETE'])
def coupon_detail(request, pk):
    c = _with_usage(Coupon.objects.filter(pk=pk)).first()
    if not c:
        raise ApiError(404, 'کد تخفیف یافت نشد.')
    if request.method == 'GET':
        return Response(coupon_dto(c))
    if request.method == 'DELETE':
        if c.orders.exists():
            raise ApiError(409, 'این کد در سفارش‌ها استفاده شده و حذف نمی‌شود. آن را غیرفعال کنید.', code='protected')
        c.delete()
        return Response(status=204)
    for k, v in _form(request.data, True, c).items():
        setattr(c, k, v)
    c.save()
    return Response(coupon_dto(_with_usage(Coupon.objects.filter(pk=pk)).get()))
