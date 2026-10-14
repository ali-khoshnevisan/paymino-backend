from dataclasses import dataclass, field
from datetime import datetime

from django.conf import settings


@dataclass
class GatewayInvoice:
    address: str
    amount_crypto: str
    expires_at: datetime
    confirmations_required: int
    provider_ref: str = ''
    memo: str | None = None
    payment_uri: str | None = None
    raw: dict = field(default_factory=dict)


def get_gateway():
    if settings.PAYMENT_PROVIDER == 'plisio':
        from .plisio import PlisioGateway
        return PlisioGateway()
    from .sandbox import SandboxGateway
    return SandboxGateway()
