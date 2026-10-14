"""Mirror of shared/utils/status.ts in the frontend. Keep both tables in sync."""

ORDER_STATUSES = [
    ('pending_payment', 'در انتظار پرداخت'),
    ('payment_verification', 'بررسی پرداخت'),
    ('paid', 'پرداخت‌شده'),
    ('processing', 'در حال انجام'),
    ('awaiting_customer_info', 'نیازمند اطلاعات مشتری'),
    ('completed', 'تکمیل‌شده'),
    ('failed', 'ناموفق'),
    ('cancelled', 'لغوشده'),
    ('refund_pending', 'در انتظار بازپرداخت'),
    ('refunded', 'بازپرداخت‌شده'),
]
PAYMENT_STATUSES = [
    ('awaiting_payment', 'در انتظار پرداخت'),
    ('detected', 'شناسایی شد'),
    ('confirming', 'در حال تأیید'),
    ('confirmed', 'تأییدشده'),
    ('expired', 'منقضی‌شده'),
    ('underpaid', 'کم‌پرداخت'),
    ('failed', 'ناموفق'),
    ('refunded', 'بازگشت‌داده‌شده'),
]

ORDER_TRANSITIONS = {
    'pending_payment': ['payment_verification', 'paid', 'cancelled', 'failed'],
    'payment_verification': ['paid', 'pending_payment', 'failed', 'cancelled'],
    'paid': ['processing', 'awaiting_customer_info', 'refund_pending'],
    'processing': ['awaiting_customer_info', 'completed', 'failed', 'refund_pending'],
    'awaiting_customer_info': ['processing', 'cancelled', 'refund_pending'],
    'completed': ['refund_pending'],
    'failed': ['refund_pending'],
    'cancelled': [],
    'refund_pending': ['refunded'],
    'refunded': [],
}

PAYMENT_TRANSITIONS = {
    'awaiting_payment': ['detected', 'confirming', 'confirmed', 'underpaid', 'expired', 'failed'],
    'detected': ['confirming', 'confirmed', 'underpaid', 'failed'],
    'confirming': ['confirmed', 'underpaid', 'failed'],
    'underpaid': ['confirming', 'confirmed', 'failed', 'refunded'],
    'confirmed': ['refunded'],
    # Backend-only: money that arrives after expiry must never be ignored.
    'expired': ['detected', 'confirming', 'confirmed', 'underpaid'],
    'failed': [],
    'refunded': [],
}

ACTIVE_ORDER_STATES = ['pending_payment', 'payment_verification', 'paid', 'processing', 'awaiting_customer_info', 'refund_pending']
FINAL_PAYMENT_STATES = ['confirmed', 'expired', 'failed', 'refunded']


def can_transition_order(frm: str, to: str) -> bool:
    return frm == to or to in ORDER_TRANSITIONS.get(frm, [])


def can_transition_payment(frm: str, to: str) -> bool:
    return frm == to or to in PAYMENT_TRANSITIONS.get(frm, [])


def is_payable(order_status: str, payment_status: str | None) -> bool:
    return order_status == 'pending_payment' and payment_status in (None, 'awaiting_payment', 'expired', 'failed')
