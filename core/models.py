from decimal import Decimal

from django.db import models, transaction


class SiteSettings(models.Model):
    """Singleton store settings, editable from the admin panel."""

    service_fee_rate = models.DecimalField('نرخ کارمزد خدمات', max_digits=5, decimal_places=4, default=Decimal('0.02'))
    invoice_ttl_minutes = models.PositiveIntegerField('مهلت پرداخت فاکتور (دقیقه)', default=30)
    orders_enabled = models.BooleanField('ثبت سفارش فعال است', default=True)
    low_stock_threshold = models.PositiveIntegerField('هشدار کمبود موجودی کد', default=5)
    support_email = models.EmailField('ایمیل اعلان‌های مدیر', blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'تنظیمات فروشگاه'
        verbose_name_plural = 'تنظیمات فروشگاه'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls) -> 'SiteSettings':
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Counter(models.Model):
    """Monotonic counters for human-readable numbers (PM-10241, T-501)."""

    name = models.CharField(max_length=32, primary_key=True)
    value = models.BigIntegerField(default=0)

    @classmethod
    def next(cls, name: str, start: int) -> int:
        with transaction.atomic():
            obj, _ = cls.objects.select_for_update().get_or_create(name=name, defaults={'value': start})
            obj.value += 1
            obj.save(update_fields=['value'])
            return obj.value
