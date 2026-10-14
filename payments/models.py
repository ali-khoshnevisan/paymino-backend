from django.db import models

from core.ids import invoice_id
from orders.status import PAYMENT_STATUSES


class PaymentCurrency(models.Model):
    code = models.CharField('کد', max_length=12, unique=True)
    name = models.CharField('نام', max_length=60)
    decimals = models.PositiveSmallIntegerField('تعداد اعشار', default=2)
    rate_toman = models.PositiveBigIntegerField('نرخ (تومان برای هر واحد)')
    rate_updated_at = models.DateTimeField('زمان به‌روزرسانی نرخ', auto_now_add=True)
    is_active = models.BooleanField('فعال', default=True)
    sort_order = models.IntegerField('ترتیب', default=0)

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'ارز پرداخت'
        verbose_name_plural = 'ارزهای پرداخت'

    def __str__(self):
        return self.code


class PaymentNetwork(models.Model):
    currency = models.ForeignKey(PaymentCurrency, on_delete=models.CASCADE, related_name='networks')
    code = models.CharField('کد شبکه', max_length=20)
    name = models.CharField('نام شبکه', max_length=60)
    min_amount = models.DecimalField('حداقل مبلغ', max_digits=20, decimal_places=8, default=1)
    confirmations_required = models.PositiveIntegerField('تأییدهای لازم', default=1)
    network_fee_note = models.CharField('توضیح کارمزد شبکه', max_length=255, blank=True)
    gateway_code = models.CharField('شناسه در درگاه (Plisio)', max_length=30, blank=True, help_text='مثلاً USDT_TRX، USDT_BSC، TRX، BTC، TON')
    explorer_tx_url = models.CharField('الگوی لینک تراکنش', max_length=255, blank=True, help_text='مثلاً https://tronscan.org/#/transaction/{tx}')
    is_active = models.BooleanField('فعال', default=True)

    class Meta:
        ordering = ['id']
        constraints = [models.UniqueConstraint(fields=['currency', 'code'], name='uniq_network_per_currency')]

    def __str__(self):
        return f'{self.currency.code}/{self.code}'


class PaymentInvoice(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=invoice_id, editable=False)
    order = models.ForeignKey('orders.Order', on_delete=models.CASCADE, related_name='invoices')
    provider = models.CharField(max_length=20)
    provider_ref = models.CharField('شناسه درگاه', max_length=80, blank=True, db_index=True)
    currency = models.CharField(max_length=12)
    network = models.CharField(max_length=20)
    amount_crypto = models.CharField(max_length=40)
    amount_received = models.CharField(max_length=40, null=True, blank=True)
    rate_toman = models.PositiveBigIntegerField()
    total_toman = models.PositiveBigIntegerField()
    address = models.CharField(max_length=200)
    memo = models.CharField(max_length=100, null=True, blank=True)
    payment_uri = models.CharField(max_length=500, null=True, blank=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=PAYMENT_STATUSES, default='awaiting_payment')
    confirmations = models.PositiveIntegerField(default=0)
    confirmations_required = models.PositiveIntegerField(default=1)
    tx_hash = models.CharField(max_length=200, null=True, blank=True)
    explorer_url = models.CharField(max_length=500, null=True, blank=True)
    sandbox = models.BooleanField(default=False)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']


class ProcessedEvent(models.Model):
    """Gateway events already applied (idempotency)."""

    event_id = models.CharField(max_length=200, unique=True)
    invoice = models.ForeignKey(PaymentInvoice, on_delete=models.SET_NULL, null=True, related_name='+')
    payload = models.JSONField(default=dict)
    result = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)
