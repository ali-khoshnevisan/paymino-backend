import logging

from django.conf import settings
from django.core.mail import send_mail

log = logging.getLogger(__name__)


def send(to: str, subject: str, body: str):
    """Plain-text Persian email. Failures are logged, never raised to the customer."""
    try:
        send_mail(f'پی‌مینو | {subject}', body, settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
    except Exception:  # noqa: BLE001
        log.exception('Email to %s failed (%s)', to, subject)


def frontend(path: str) -> str:
    return f'{settings.FRONTEND_URL}{path}'
