import logging
import threading

import requests
from django.conf import settings
from django.db import transaction

log = logging.getLogger(__name__)


def _post(text: str):
    try:
        r = requests.post(
            f'https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage',
            json={'chat_id': settings.TELEGRAM_CHAT_ID, 'text': text[:4096], 'disable_web_page_preview': True},
            timeout=10,
        )
        if not r.ok:
            log.error('Telegram notify failed: %s %s', r.status_code, r.text[:300])
    except Exception:  # noqa: BLE001
        log.exception('Telegram notify failed')


def notify(text: str):
    """Admin notification. Sent after commit, in the background; failures are logged, never raised to the customer."""
    if not (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID):
        return
    transaction.on_commit(lambda: threading.Thread(target=_post, args=(text,), daemon=True).start())


def _user_block(user) -> str:
    return '\n'.join([
        f'👤 نام: {user.full_name}',
        f'📧 ایمیل: {user.email}',
        f'📱 موبایل: {user.phone or "—"}',
        f'🆔 کاربر: {user.pk}',
    ])


def notify_order_paid(order):
    lines = [f'🛒 خرید جدید — سفارش {order.number}', '', _user_block(order.user), '', '📦 محصولات:']
    for it in order.items.all():
        lines.append(f'• {it.product_name} — {it.variant_label} × {it.quantity} = {it.line_total_toman:,} تومان')
        for key, val in (it.fields or {}).items():
            lines.append(f'    {(it.field_labels or {}).get(key, key)}: {val}')
    lines += ['', f'💰 مبلغ کل: {order.total_toman:,} تومان']
    if order.coupon_code:
        lines.append(f'🏷 کد تخفیف: {order.coupon_code}')
    if order.payment_currency:
        lines.append(f'💳 پرداخت: {order.payment_currency} ({order.payment_network})')
    notify('\n'.join(lines))


def notify_ticket(ticket, user, body: str, new: bool):
    head = f'🎫 درخواست پشتیبانی جدید {ticket.number}' if new else f'💬 پیام جدید در درخواست {ticket.number}'
    lines = [head, '', _user_block(user), '', f'📝 موضوع: {ticket.subject}']
    if ticket.order_id:
        lines.append(f'🧾 سفارش: {ticket.order.number}')
    lines += ['', body]
    notify('\n'.join(lines))
