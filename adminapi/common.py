import re

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, permission_classes

from core.auth import IsStaff
from core.errors import field_errors

SLUG_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')


def staff_view(methods):
    """@api_view + staff-only permission."""
    def deco(fn):
        return api_view(methods)(permission_classes([IsStaff])(fn))
    return deco


class Form:
    """Small helper that collects field errors with the frontend's {field: [msg]} shape."""

    def __init__(self, data, partial=False):
        self.data = data if isinstance(data, dict) else {}
        self.partial = partial
        self.errors = {}
        self.clean = {}

    def has(self, key):
        return key in self.data

    def skip(self, key):
        return self.partial and key not in self.data

    def err(self, key, msg):
        self.errors.setdefault(key, []).append(msg)

    def text(self, key, attr, *, required=True, min_len=1, max_len=255, blank_ok=False):
        if self.skip(key):
            return
        v = str(self.data.get(key) if self.data.get(key) is not None else '').strip()
        if not v and (blank_ok or not required):
            self.clean[attr] = ''
            return
        if len(v) < min_len:
            self.err(key, 'این فیلد الزامی است.' if not v else f'حداقل {min_len} کاراکتر وارد کنید.')
        elif len(v) > max_len:
            self.err(key, f'حداکثر {max_len} کاراکتر مجاز است.')
        else:
            self.clean[attr] = v

    def slug(self, key, attr):
        if self.skip(key):
            return
        v = str(self.data.get(key) or '').strip().lower()
        if not SLUG_RE.match(v) or len(v) > 120:
            self.err(key, 'فقط حروف کوچک انگلیسی، عدد و خط تیره مجاز است.')
        else:
            self.clean[attr] = v

    def integer(self, key, attr, *, required=True, min_value=None, max_value=None, nullable=False):
        if self.skip(key):
            return
        raw = self.data.get(key)
        if raw is None or str(raw).strip() == '':
            if nullable or not required:
                self.clean[attr] = None if nullable else 0
                return
            self.err(key, 'این فیلد الزامی است.')
            return
        try:
            v = int(str(raw).strip())
        except ValueError:
            self.err(key, 'عدد صحیح وارد کنید.')
            return
        if (min_value is not None and v < min_value) or (max_value is not None and v > max_value):
            self.err(key, 'مقدار خارج از محدوده مجاز است.')
            return
        self.clean[attr] = v

    def datetime(self, key, attr):
        """ISO 8601 date-time or empty (→ None). A value without an offset is read in the site's time zone."""
        if self.skip(key):
            return
        raw = self.data.get(key)
        if raw is None or str(raw).strip() == '':
            self.clean[attr] = None
            return
        try:
            v = parse_datetime(str(raw).strip())
        except ValueError:
            v = None
        if v is None:
            self.err(key, 'تاریخ و زمان معتبر وارد کنید.')
            return
        self.clean[attr] = timezone.make_aware(v) if timezone.is_naive(v) else v

    def boolean(self, key, attr):
        if self.skip(key):
            return
        self.clean[attr] = self.data.get(key) is True or str(self.data.get(key)).lower() in ('true', '1')

    def choice(self, key, attr, choices):
        if self.skip(key):
            return
        v = self.data.get(key)
        if v not in choices:
            self.err(key, 'گزینه نامعتبر است.')
        else:
            self.clean[attr] = v

    def str_list(self, key, attr, max_items=30, max_len=500):
        if self.skip(key):
            return
        v = self.data.get(key) or []
        if not isinstance(v, list) or len(v) > max_items or not all(isinstance(x, str) and len(x) <= max_len for x in v):
            self.err(key, 'فهرست نامعتبر است.')
            return
        self.clean[attr] = [x.strip() for x in v if x.strip()]

    def raise_if_errors(self):
        if self.errors:
            field_errors(self.errors)
        return self.clean
