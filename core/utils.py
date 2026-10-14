import re
from datetime import datetime, timezone as dt_timezone
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .errors import ApiError

EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]{2,}$')
IR_PHONE_RE = re.compile(r'^09\d{9}$')

_FA = '۰۱۲۳۴۵۶۷۸۹'
_AR = '٠١٢٣٤٥٦٧٨٩'
_DIGITS = str.maketrans({**{c: str(i) for i, c in enumerate(_FA)}, **{c: str(i) for i, c in enumerate(_AR)}})


def normalize_digits(value: str) -> str:
    return value.translate(_DIGITS)


def normalize_search(text: str) -> str:
    """Normalize Arabic letters/digits and ZWNJ so Persian search behaves as users expect."""
    text = text.replace('ي', 'ی').replace('ك', 'ک').replace('‌', ' ').replace('‏', ' ')
    return normalize_digits(text).lower().strip()


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(dt_timezone.utc).isoformat().replace('+00:00', 'Z')


def now():
    return timezone.now()


def round_to_1000(value: Decimal | int) -> int:
    return int((Decimal(value) / 1000).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * 1000)


def client_ip(request) -> str:
    if settings.TRUST_X_FORWARDED_FOR:
        xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if xff:
            return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


def throttle(key: str, limit: int = 8, window_seconds: int = 600):
    """Fixed-window counter in the cache. Raises 429 once `limit` is exceeded."""
    cache_key = f'throttle:{key}'
    added = cache.add(cache_key, 1, timeout=window_seconds)
    if added:
        return
    try:
        count = cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, timeout=window_seconds)
        return
    if count > limit:
        raise ApiError(429, 'تعداد تلاش‌ها بیش از حد مجاز است. چند دقیقه بعد دوباره امتحان کنید.', code='throttled')


def as_str(value, default='') -> str:
    if value is None:
        return default
    return str(value)


def as_int(value, default=None):
    try:
        if value is None or str(value).strip() == '':
            return default
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in ('1', 'true', 'yes', 'on')


def media_url(file_field) -> str | None:
    if not file_field:
        return None
    url = file_field.url
    return url if url.startswith('http') else f'{settings.API_PUBLIC_URL}{url}'
