import secrets
from datetime import timedelta

from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.tokens import default_token_generator
from django.db.models import Q
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core import mail
from core.auth import require_user
from core.errors import ApiError, field_errors
from core.utils import EMAIL_RE, IR_PHONE_RE, as_str, client_ip, normalize_digits, now, throttle

from .dto import public_user
from .models import User
from .validators import password_problems

VERIFICATION_TTL = timedelta(minutes=30)


def _send_verification(user: User):
    user.verification_code = f'{secrets.randbelow(900000) + 100000}'
    user.verification_sent_at = now()
    user.save(update_fields=['verification_code', 'verification_sent_at'])
    mail.send(
        user.email,
        'کد تأیید ایمیل',
        f'سلام {user.full_name}\n\nکد تأیید ایمیل شما: {user.verification_code}\n\nاین کد ۳۰ دقیقه اعتبار دارد.',
    )


def _find_user(identifier: str):
    ident = normalize_digits(identifier.strip().lower())
    if not ident:
        return None
    return User.objects.filter(Q(email=ident) | Q(phone=ident)).first()


@api_view(['POST'])
def register(request):
    throttle(f'register:{client_ip(request)}', 10)
    d = request.data
    full_name = as_str(d.get('fullName')).strip()
    email = as_str(d.get('email')).strip().lower()
    phone = normalize_digits(as_str(d.get('phone')).strip()) or None
    password = as_str(d.get('password'))

    errors = {}
    if len(full_name) < 3 or len(full_name) > 120:
        errors['fullName'] = ['نام و نام خانوادگی را کامل وارد کنید.']
    if not EMAIL_RE.match(email) or len(email) > 254:
        errors['email'] = ['ایمیل معتبر وارد کنید.']
    if phone and not IR_PHONE_RE.match(phone):
        errors['phone'] = ['شماره موبایل باید ۱۱ رقم و با ۰۹ شروع شود.']
    pw = password_problems(password)
    if pw:
        errors['password'] = pw
    if 'email' not in errors and User.objects.filter(email=email).exists():
        errors['email'] = ['با این ایمیل قبلاً حساب ساخته شده است.']
    if phone and 'phone' not in errors and User.objects.filter(phone=phone).exists():
        errors['phone'] = ['این شماره موبایل قبلاً ثبت شده است.']
    if errors:
        field_errors(errors)

    user = User.objects.create_user(email=email, password=password, full_name=full_name, phone=phone)
    _send_verification(user)
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    return Response({'user': public_user(user)}, status=201)


@api_view(['POST'])
def login_view(request):
    identifier = as_str(request.data.get('identifier')).strip()
    password = as_str(request.data.get('password'))
    throttle(f'login:{client_ip(request)}:{identifier.lower()}')

    errors = {}
    if not identifier:
        errors['identifier'] = ['ایمیل یا شماره موبایل را وارد کنید.']
    if not password:
        errors['password'] = ['رمز عبور را وارد کنید.']
    if errors:
        field_errors(errors)

    user = _find_user(identifier)
    # One generic message: never reveal whether the account exists.
    if not user or not user.is_active or not user.check_password(password):
        raise ApiError(400, 'ایمیل/موبایل یا رمز عبور اشتباه است.', code='invalid_credentials')

    request.session.cycle_key()
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    return Response({'user': public_user(user)})


@api_view(['POST'])
def logout_view(request):
    logout(request)
    return Response({'ok': True})


@api_view(['GET', 'PATCH'])
def me(request):
    user = require_user(request)
    if request.method == 'GET':
        return Response({'user': public_user(user)})

    d = request.data
    errors = {}
    fields = []
    if 'fullName' in d:
        full_name = as_str(d.get('fullName')).strip()
        if len(full_name) < 3 or len(full_name) > 120:
            errors['fullName'] = ['نام و نام خانوادگی را کامل وارد کنید.']
        else:
            user.full_name = full_name
            fields.append('full_name')
    if 'phone' in d:
        phone = normalize_digits(as_str(d.get('phone')).strip()) or None
        if phone and not IR_PHONE_RE.match(phone):
            errors['phone'] = ['شماره موبایل باید ۱۱ رقم و با ۰۹ شروع شود.']
        elif phone and User.objects.filter(phone=phone).exclude(pk=user.pk).exists():
            errors['phone'] = ['این شماره موبایل قبلاً ثبت شده است.']
        else:
            user.phone = phone
            fields.append('phone')
    if errors:
        field_errors(errors)
    if fields:
        user.save(update_fields=fields)
    return Response({'user': public_user(user)})


@api_view(['POST'])
def change_password(request):
    user = require_user(request)
    throttle(f'change-pw:{user.pk}', 5)
    current = as_str(request.data.get('currentPassword'))
    new = as_str(request.data.get('newPassword'))
    if not user.check_password(current):
        field_errors({'currentPassword': ['رمز عبور فعلی اشتباه است.']})
    problems = password_problems(new)
    if problems:
        field_errors({'newPassword': problems})
    user.set_password(new)
    user.save(update_fields=['password'])
    update_session_auth_hash(request, user)  # keeps this session; all others are invalidated
    return Response({'ok': True})


@api_view(['POST'])
def verify_email(request):
    user = require_user(request)
    throttle(f'verify:{user.pk}', 10)
    code = normalize_digits(as_str(request.data.get('code')).strip())
    if user.email_verified:
        return Response({'user': public_user(user)})
    expired = not user.verification_sent_at or user.verification_sent_at + VERIFICATION_TTL < now()
    if not user.verification_code or expired or not secrets.compare_digest(code, user.verification_code):
        field_errors({'code': ['کد واردشده صحیح نیست یا منقضی شده است.']})
    user.email_verified = True
    user.verification_code = ''
    user.save(update_fields=['email_verified', 'verification_code'])
    return Response({'user': public_user(user)})


@api_view(['POST'])
def resend_verification(request):
    user = require_user(request)
    throttle(f'resend:{user.pk}', 3, 300)
    if not user.email_verified:
        _send_verification(user)
    return Response({'ok': True})


def _make_reset_token(user: User) -> str:
    return f'{urlsafe_base64_encode(force_bytes(user.pk))}.{default_token_generator.make_token(user)}'


def _user_from_reset_token(token: str):
    uid_b64, _, tok = token.partition('.')
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uid_b64)))
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        return None
    return user if user.is_active and default_token_generator.check_token(user, tok) else None


@api_view(['POST'])
def password_reset(request):
    throttle(f'reset:{client_ip(request)}', 5)
    email = as_str(request.data.get('email')).strip().lower()
    if not EMAIL_RE.match(email):
        field_errors({'email': ['ایمیل معتبر وارد کنید.']})
    user = User.objects.filter(email=email, is_active=True).first()
    if user:
        link = mail.frontend(f'/auth/reset-password?token={_make_reset_token(user)}')
        mail.send(user.email, 'بازیابی رمز عبور', f'برای تعیین رمز عبور جدید روی لینک زیر بزنید (اعتبار: ۳۰ دقیقه):\n\n{link}\n\nاگر این درخواست را شما نداده‌اید، این پیام را نادیده بگیرید.')
    return Response({'ok': True})  # always 200: no account enumeration


@api_view(['POST'])
def password_reset_confirm(request):
    throttle(f'reset-confirm:{client_ip(request)}', 10)
    token = as_str(request.data.get('token'))
    password = as_str(request.data.get('password'))
    user = _user_from_reset_token(token)
    if not user:
        raise ApiError(400, 'لینک بازیابی نامعتبر است یا منقضی شده است.', code='invalid_token')
    problems = password_problems(password)
    if problems:
        field_errors({'password': problems})
    user.set_password(password)  # changes the session hash → logs out every existing session; token becomes invalid
    user.save(update_fields=['password'])
    return Response({'ok': True})
