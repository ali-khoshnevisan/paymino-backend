from django.db.models import Count, Q, Sum
from rest_framework.response import Response

from accounts.models import User
from accounts.validators import password_problems
from core.errors import ApiError, field_errors
from core.pagination import paginate
from core.utils import EMAIL_RE, IR_PHONE_RE, normalize_digits

from .common import staff_view
from .dto import user_row


def _qs():
    return User.objects.annotate(
        order_count=Count('orders', distinct=True),
        total_spent=Sum('orders__total_toman', filter=Q(orders__status='completed')),
    ).order_by('-created_at')


@staff_view(['GET'])
def users(request):
    q = request.query_params
    qs = _qs()
    if q.get('q'):
        term = normalize_digits(q['q'].strip())
        qs = qs.filter(Q(email__icontains=term) | Q(full_name__icontains=term) | Q(phone__icontains=term) | Q(id=term))
    if q.get('staff') == '1':
        qs = qs.filter(is_staff=True)
    if q.get('active') in ('1', '0'):
        qs = qs.filter(is_active=q['active'] == '1')
    count, items = paginate(request, qs, 25, 100)
    return Response({'count': count, 'results': [user_row(u) for u in items]})


def _detail(u):
    d = user_row(u)
    d['adminNote'] = u.admin_note
    return d


@staff_view(['GET', 'PATCH'])
def user_detail(request, pk):
    u = _qs().filter(pk=pk).first()
    if not u:
        raise ApiError(404, 'کاربر یافت نشد.')
    if request.method == 'GET':
        return Response(_detail(u))

    d = request.data
    errors = {}
    me = request.user
    if 'fullName' in d:
        v = str(d.get('fullName') or '').strip()
        if len(v) < 3 or len(v) > 120:
            errors['fullName'] = ['نام و نام خانوادگی را کامل وارد کنید.']
        else:
            u.full_name = v
    if 'email' in d:
        v = str(d.get('email') or '').strip().lower()
        if not EMAIL_RE.match(v):
            errors['email'] = ['ایمیل معتبر وارد کنید.']
        elif User.objects.filter(email=v).exclude(pk=u.pk).exists():
            errors['email'] = ['این ایمیل برای کاربر دیگری ثبت شده است.']
        else:
            u.email = v
    if 'phone' in d:
        v = normalize_digits(str(d.get('phone') or '').strip()) or None
        if v and not IR_PHONE_RE.match(v):
            errors['phone'] = ['شماره موبایل باید ۱۱ رقم و با ۰۹ شروع شود.']
        elif v and User.objects.filter(phone=v).exclude(pk=u.pk).exists():
            errors['phone'] = ['این شماره موبایل برای کاربر دیگری ثبت شده است.']
        else:
            u.phone = v
    if 'emailVerified' in d:
        u.email_verified = d.get('emailVerified') is True
    if 'adminNote' in d:
        u.admin_note = str(d.get('adminNote') or '')[:5000]
    if 'isActive' in d:
        if u.pk == me.pk and d.get('isActive') is not True:
            errors['isActive'] = ['نمی‌توانید حساب خودتان را غیرفعال کنید.']
        elif u.is_superuser and not me.is_superuser:
            errors['isActive'] = ['فقط مدیر ارشد می‌تواند وضعیت این حساب را تغییر دهد.']
        else:
            u.is_active = d.get('isActive') is True
    if 'isStaff' in d:
        if not me.is_superuser:
            errors['isStaff'] = ['فقط مدیر ارشد می‌تواند دسترسی مدیریت بدهد یا بگیرد.']
        elif u.pk == me.pk:
            errors['isStaff'] = ['نمی‌توانید دسترسی خودتان را تغییر دهید.']
        else:
            u.is_staff = d.get('isStaff') is True
    if errors:
        field_errors(errors)
    u.save()  # inactive users are rejected by the auth backend on their next request
    return Response(_detail(_qs().get(pk=pk)))


@staff_view(['POST'])
def user_password(request, pk):
    u = User.objects.filter(pk=pk).first()
    if not u:
        raise ApiError(404, 'کاربر یافت نشد.')
    if u.is_superuser and not request.user.is_superuser:
        raise ApiError(403, 'اجازه دسترسی به این بخش را ندارید.')
    pw = str(request.data.get('password') or '')
    problems = password_problems(pw)
    if problems:
        field_errors({'password': problems})
    u.set_password(pw)  # invalidates the user's existing sessions
    u.save(update_fields=['password'])
    return Response({'ok': True})

