from django.db import models
from django.db.models import Count, Prefetch, Q

from core.ids import product_id, variant_id

CATEGORY_ICONS = [('steam', 'Steam'), ('apple', 'Apple'), ('playstation', 'PlayStation'), ('tradingview', 'TradingView'), ('ai', 'AI')]
PRODUCT_TYPES = [('gift_card', 'گیفت کارت'), ('account_recharge', 'شارژ حساب'), ('subscription', 'فعال‌سازی اشتراک')]
STOCK_MODES = [('codes', 'تحویل خودکار از انبار کد'), ('manual', 'انجام دستی توسط مدیر')]


class Category(models.Model):
    slug = models.SlugField('نامک', unique=True, max_length=60)
    name = models.CharField('نام', max_length=120)
    description = models.CharField('توضیح کوتاه', max_length=255, blank=True)
    icon = models.CharField('آیکون', max_length=20, choices=CATEGORY_ICONS, default='ai')
    sort_order = models.IntegerField('ترتیب', default=0)
    is_active = models.BooleanField('فعال', default=True)

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'دسته‌بندی'
        verbose_name_plural = 'دسته‌بندی‌ها'

    def __str__(self):
        return self.name


class Provider(models.Model):
    slug = models.SlugField('نامک', unique=True, max_length=60)
    name = models.CharField('نام لاتین برند', max_length=120)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='providers', verbose_name='دسته‌بندی')

    class Meta:
        ordering = ['name']
        verbose_name = 'برند'
        verbose_name_plural = 'برندها'

    def __str__(self):
        return self.name


class Product(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=product_id, editable=False)
    slug = models.SlugField('نامک', unique=True, max_length=120)
    name = models.CharField('نام فارسی', max_length=200)
    brand_name = models.CharField('نام لاتین', max_length=200)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products', verbose_name='دسته‌بندی')
    provider = models.ForeignKey(Provider, on_delete=models.PROTECT, related_name='products', verbose_name='برند')
    type = models.CharField('نوع', max_length=20, choices=PRODUCT_TYPES)
    short_description = models.CharField('توضیح کوتاه', max_length=255)
    description = models.TextField('توضیحات', blank=True)
    image = models.FileField('تصویر', upload_to='products/', blank=True)
    regions = models.JSONField('مناطق', default=list, blank=True)
    restrictions = models.JSONField('محدودیت‌ها', default=list, blank=True)
    redemption_notes = models.JSONField('راهنمای استفاده', default=list, blank=True)
    delivery_method = models.CharField('روش تحویل', max_length=200, blank=True)
    fulfillment_estimate = models.CharField('زمان تقریبی انجام', max_length=120, blank=True)
    refund_policy = models.TextField('قوانین بازپرداخت', blank=True)
    required_fields = models.JSONField('فیلدهای موردنیاز از مشتری', default=list, blank=True)
    max_quantity_per_item = models.PositiveIntegerField('حداکثر تعداد در هر خرید', default=5)
    popularity = models.IntegerField('محبوبیت (ترتیب پیش‌فرض)', default=0)
    is_active = models.BooleanField('منتشرشده', default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-popularity', '-created_at']
        verbose_name = 'محصول'
        verbose_name_plural = 'محصولات'

    def __str__(self):
        return self.name


class Variant(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=variant_id, editable=False)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    label = models.CharField('عنوان', max_length=120)
    face_value = models.DecimalField('مبلغ اسمی', max_digits=12, decimal_places=2, null=True, blank=True)
    face_currency = models.CharField('ارز اسمی', max_length=3, blank=True)
    region = models.CharField('منطقه', max_length=120, blank=True)
    duration_months = models.PositiveIntegerField('مدت (ماه)', null=True, blank=True)
    price_toman = models.PositiveBigIntegerField('قیمت (تومان)')
    stock_mode = models.CharField('روش تحویل', max_length=10, choices=STOCK_MODES, default='manual')
    is_active = models.BooleanField('فعال', default=True)
    sort_order = models.IntegerField('ترتیب', default=0)

    class Meta:
        ordering = ['sort_order', 'price_toman']
        verbose_name = 'گزینه'
        verbose_name_plural = 'گزینه‌ها'

    def __str__(self):
        return f'{self.product.name} — {self.label}'

    @property
    def stock(self) -> int:
        cached = getattr(self, 'stock_available', None)
        if cached is not None:
            return cached
        return self.codes.filter(status='available').count()

    @property
    def available(self) -> bool:
        return self.is_active and (self.stock_mode != 'codes' or self.stock > 0)


class GiftCode(models.Model):
    STATUSES = [('available', 'موجود'), ('delivered', 'تحویل‌شده'), ('void', 'باطل')]

    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name='codes')
    code = models.CharField('کد', max_length=255)
    status = models.CharField('وضعیت', max_length=10, choices=STATUSES, default='available', db_index=True)
    order_item = models.ForeignKey('orders.OrderItem', on_delete=models.SET_NULL, null=True, blank=True, related_name='codes')
    note = models.CharField('یادداشت', max_length=255, blank=True)
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at', 'id']
        constraints = [models.UniqueConstraint(fields=['variant', 'code'], name='uniq_code_per_variant')]
        verbose_name = 'کد گیفت کارت'
        verbose_name_plural = 'کدهای گیفت کارت'

    def __str__(self):
        return f'{self.variant} — {self.code[:4]}…'


def variants_with_stock():
    return Variant.objects.annotate(stock_available=Count('codes', filter=Q(codes__status='available'))).order_by('sort_order', 'price_toman')


def products_with_variants(qs=None):
    qs = qs if qs is not None else Product.objects.all()
    return qs.select_related('category', 'provider').prefetch_related(Prefetch('variants', queryset=variants_with_stock()))
