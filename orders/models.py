from django.conf import settings
from django.db import models

from core.ids import order_id, order_item_id

from .status import ORDER_STATUSES, PAYMENT_STATUSES


class Order(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=order_id, editable=False)
    number = models.CharField('شماره سفارش', max_length=20, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='orders', verbose_name='کاربر')
    idempotency_key = models.CharField(max_length=80, null=True, blank=True)
    status = models.CharField('وضعیت', max_length=30, choices=ORDER_STATUSES, default='pending_payment', db_index=True)
    payment_status = models.CharField('وضعیت پرداخت', max_length=20, choices=PAYMENT_STATUSES, null=True, blank=True)
    subtotal_toman = models.PositiveBigIntegerField(default=0)
    service_fee_toman = models.PositiveBigIntegerField(default=0)
    discount_toman = models.PositiveBigIntegerField(default=0)
    total_toman = models.PositiveBigIntegerField(default=0)
    payment_currency = models.CharField(max_length=12, blank=True)
    payment_network = models.CharField(max_length=20, blank=True)
    current_invoice = models.ForeignKey('payments.PaymentInvoice', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    needs_review = models.BooleanField('نیازمند بررسی مدیر', default=False, db_index=True)
    admin_note = models.TextField('یادداشت داخلی', blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'idempotency_key'], name='uniq_order_idempotency', condition=models.Q(idempotency_key__isnull=False)),
        ]
        verbose_name = 'سفارش'
        verbose_name_plural = 'سفارش‌ها'

    def __str__(self):
        return self.number


class OrderItem(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=order_item_id, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('catalog.Product', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    variant = models.ForeignKey('catalog.Variant', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    # Snapshots: what the customer bought, even if the catalog changes later
    product_slug = models.CharField(max_length=120)
    product_name = models.CharField(max_length=200)
    brand_name = models.CharField(max_length=200)
    variant_label = models.CharField(max_length=120)
    type = models.CharField(max_length=20)
    stock_mode = models.CharField(max_length=10, default='manual')
    quantity = models.PositiveIntegerField()
    unit_price_toman = models.PositiveBigIntegerField()
    line_total_toman = models.PositiveBigIntegerField()
    fields = models.JSONField(default=dict, blank=True)
    field_labels = models.JSONField(default=dict, blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']


class Delivery(models.Model):
    KINDS = [('code', 'کد'), ('service_note', 'یادداشت انجام سرویس')]
    item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name='deliveries')
    kind = models.CharField(max_length=20, choices=KINDS)
    value = models.TextField()
    delivered_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        ordering = ['delivered_at', 'id']


class OrderEvent(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='events')
    at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=30, null=True, blank=True)
    payment_status = models.CharField(max_length=20, null=True, blank=True)
    message = models.TextField()
    internal = models.BooleanField(default=False)  # visible in admin only
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        ordering = ['at', 'id']
