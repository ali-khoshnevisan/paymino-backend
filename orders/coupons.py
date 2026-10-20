"""Discount codes. Evaluated by the server on every quote and again, under a row lock, when the order is created."""
import re
from decimal import ROUND_DOWN, Decimal

from core.utils import normalize_digits, now

from .models import Coupon, Order

CODE_RE = re.compile(r'^[A-Z0-9_-]{3,40}$')
MIN_TOTAL_AFTER_COUPON = 1000  # an invoice is never for 0 Toman


class CouponError(Exception):
    def __init__(self, message, code='coupon_invalid'):
        super().__init__(message)
        self.message = message
        self.code = code


def normalize_code(raw) -> str:
    """Customers type codes in any case, with Persian digits or stray spaces."""
    return re.sub(r'\s+', '', normalize_digits(str(raw or ''))).upper()[:40]


def used_count(coupon, user=None) -> int:
    """Uses that count against the limits: every order with this code except cancelled ones."""
    qs = Order.objects.filter(coupon=coupon).exclude(status='cancelled')
    if user is not None:
        qs = qs.filter(user=user)
    return qs.count()


def find(code: str):
    if not CODE_RE.match(code):
        raise CouponError('کد تخفیف معتبر نیست.')
    coupon = Coupon.objects.filter(code=code).first()
    if not coupon:
        raise CouponError('کد تخفیف معتبر نیست.')
    return coupon


def check(coupon, payable: int, user=None, at=None):
    """Raise CouponError when the code cannot be used on this order; return the discount in Toman otherwise.

    Without a signed-in user the per-user limit is checked again when the order is placed."""
    at = at or now()
    if not coupon.is_active or (coupon.starts_at and at < coupon.starts_at):
        raise CouponError('کد تخفیف معتبر نیست.')
    if coupon.ends_at and at >= coupon.ends_at:
        raise CouponError('مهلت استفاده از این کد تخفیف تمام شده است.', 'coupon_expired')
    if payable < coupon.min_order_toman:
        raise CouponError(f'این کد برای سفارش‌های بالای {coupon.min_order_toman:,} تومان قابل استفاده است.', 'coupon_min_order')
    if coupon.usage_limit is not None and used_count(coupon) >= coupon.usage_limit:
        raise CouponError('ظرفیت استفاده از این کد تخفیف تکمیل شده است.', 'coupon_used_up')
    if user is not None and coupon.per_user_limit is not None and used_count(coupon, user) >= coupon.per_user_limit:
        raise CouponError('شما قبلاً از این کد تخفیف استفاده کرده‌اید.', 'coupon_used_by_user')
    return discount_for(coupon, payable)


def discount_for(coupon, payable: int) -> int:
    if coupon.kind == 'percent':
        amount = int((Decimal(payable) * min(coupon.value, 100) / 100).quantize(Decimal('1'), rounding=ROUND_DOWN))
        if coupon.max_discount_toman is not None:
            amount = min(amount, int(coupon.max_discount_toman))
    else:
        amount = int(coupon.value)
    return max(0, min(amount, payable - MIN_TOTAL_AFTER_COUPON))


def label(coupon) -> str:
    """Short public description, e.g. "۱۰٪ تخفیف" or "۲۰۰٬۰۰۰ تومان تخفیف" (digits are localised by the frontend)."""
    return f'{coupon.value}٪ تخفیف' if coupon.kind == 'percent' else f'{coupon.value:,} تومان تخفیف'
