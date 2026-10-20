from django.contrib import admin

from .models import Coupon, Delivery, Order, OrderEvent, OrderItem


class ItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ['product_name', 'variant_label', 'quantity', 'unit_price_toman', 'line_total_toman', 'fields']
    exclude = ['product', 'variant']


class EventInline(admin.TabularInline):
    model = OrderEvent
    extra = 0
    readonly_fields = ['at', 'status', 'payment_status', 'message', 'internal', 'actor']


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['number', 'user', 'status', 'payment_status', 'total_toman', 'needs_review', 'created_at']
    list_filter = ['status', 'payment_status', 'needs_review']
    search_fields = ['number', 'user__email', 'id']
    raw_id_fields = ['user', 'current_invoice']
    inlines = [ItemInline, EventInline]


admin.site.register(Delivery)


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ['code', 'kind', 'value', 'is_active', 'usage_limit', 'per_user_limit', 'ends_at']
    list_filter = ['kind', 'is_active']
    search_fields = ['code', 'note']
