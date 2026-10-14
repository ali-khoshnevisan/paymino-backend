import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings

from core.utils import now

from . import GatewayInvoice


class SandboxGateway:
    """Fake gateway for development. Addresses are obviously not payable."""

    name = 'sandbox'
    sandbox = True

    def create_invoice(self, invoice, network, ttl_minutes, order, user) -> GatewayInvoice:
        return GatewayInvoice(
            address=f'TEST-ONLY-{network.code}-{invoice.id[4:16].upper()}',
            amount_crypto=invoice.amount_crypto,
            expires_at=now() + timedelta(minutes=ttl_minutes),
            confirmations_required=network.confirmations_required,
            memo=str(10_000_000 + secrets.randbelow(89_999_999)) if network.code == 'TON' else None,
        )


def sign(raw: bytes) -> str:
    return hmac.new(settings.SANDBOX_WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()


def verify(raw: bytes, signature: str | None) -> bool:
    return bool(signature) and hmac.compare_digest(sign(raw), signature)
