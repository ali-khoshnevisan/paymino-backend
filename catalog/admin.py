from django.contrib import admin

from .models import Category, GiftCode, Product, Provider, Variant


class VariantInline(admin.TabularInline):
    model = Variant
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'brand_name', 'category', 'type', 'is_active', 'popularity']
    list_filter = ['category', 'type', 'is_active']
    search_fields = ['name', 'brand_name', 'slug']
    inlines = [VariantInline]


admin.site.register(Category)
admin.site.register(Provider)


@admin.register(GiftCode)
class GiftCodeAdmin(admin.ModelAdmin):
    list_display = ['variant', 'status', 'created_at', 'delivered_at']
    list_filter = ['status', 'variant__product']
    raw_id_fields = ['order_item']
