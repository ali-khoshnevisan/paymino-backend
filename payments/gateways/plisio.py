"""
Plisio white-label integration.
Docs: https://plisio.net/documentation  (White-label must be enabled for the shop so the API
returns wallet_hash; otherwise customers would have to leave the site.)
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

import requests
from django.conf import settings

from core.errors import ApiError
from core.utils import now

from . import GatewayInvoice

log = logging.getLogger(__name__)


class PlisioGateway:
    name = 'plisio'
    sandbox = False

    def create_invoice(self, invoice, network, ttl_minutes, order, user) -> GatewayInvoice:
        if not network.gateway_code:
            raise ApiError(400, 'ارز یا شبکه انتخاب‌شده پشتیبانی نمی‌شود.', code='unsupported_currency')
        params = {
            'api_key': settings.PLISIO_SECRET_KEY,
            'currency': network.gateway_code,
            'amount': invoice.amount_crypto,
            'order_number': invoice.id,
            'order_name': order.number,
            'description': f'Order {order.number}',
            'callback_url': f'{settings.API_PUBLIC_URL}/api/payments/plisio/callback?json=true',
            'expire_min': ttl_minutes,
        }
        try:
            res = requests.get(f'{settings.PLISIO_API_BASE}/invoices/new', params=params, timeout=20)
            body = res.json()
        except (requests.RequestException, ValueError):
            log.exception('Plisio invoice request failed')
            raise ApiError(502, 'ارتباط با درگاه پرداخت برقرار نشد. چند لحظه بعد دوباره تلاش کنید.', code='gateway_unavailable')

        if body.get('status') != 'success':
            log.error('Plisio invoice error: %s', body)
            raise ApiError(502, 'درگاه پرداخت فاکتور را صادر نکرد. چند لحظه بعد دوباره تلاش کنید.', code='gateway_error')

        data = body.get('data') or {}
        address = data.get('wallet_hash')
        if not address:
            log.error('Plisio returned no wallet_hash — enable White-label in the Plisio shop settings. %s', data)
            raise ApiError(502, 'درگاه پرداخت به‌درستی پیکربندی نشده است.', code='gateway_misconfigured')

        expire_utc = data.get('expire_utc')
        expires_at = (
            datetime.fromtimestamp(int(expire_utc), tz=timezone.utc) if expire_utc else now() + timedelta(minutes=ttl_minutes)
        )
        # invoice_total_sum includes the gateway commission when the customer pays it
        amount = str(data.get('invoice_total_sum') or data.get('amount') or invoice.amount_crypto)
        data.pop('qr_code', None)  # large base64 image; the frontend renders its own QR
        return GatewayInvoice(
            address=address,
            amount_crypto=amount,
            expires_at=expires_at,
            confirmations_required=int(data.get('expected_confirmations') or network.confirmations_required),
            provider_ref=str(data.get('txn_id') or ''),
            payment_uri=None,
            raw=data,
        )


# Plisio status → our payment status
STATUS_MAP = {
    'new': 'awaiting_payment',
    'pending': 'confirming',
    'pending internal': 'confirming',
    'completed': 'confirmed',
    'expired': 'expired',
    'cancelled': 'expired',
    'cancelled duplicate': 'expired',
    'error': 'failed',
}


def verify_callback(data: dict) -> bool:
    """
    verify_hash = HMAC-SHA1(secret, JSON of the callback data without verify_hash).
    Plisio's docs differ between examples on exact serialization, so accept the common
    encodings of the SAME data; every candidate still requires the secret key.
    """
    given = str(data.get('verify_hash') or '')
    if not given:
        return False
    payload = {k: v for k, v in data.items() if k != 'verify_hash'}
    candidates = set()
    for ordered in (payload, dict(sorted(payload.items()))):
        for ascii_ in (False, True):
            s = json.dumps(ordered, separators=(',', ':'), ensure_ascii=ascii_)
            candidates.add(s)
            candidates.add(s.replace('/', '\\/'))
    key = settings.PLISIO_SECRET_KEY.encode()
    return any(hmac.compare_digest(hmac.new(key, c.encode(), hashlib.sha1).hexdigest(), given) for c in candidates)
