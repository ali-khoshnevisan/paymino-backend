from django.contrib import admin

from .models import PaymentCurrency, PaymentInvoice, PaymentNetwork, ProcessedEvent


class NetworkInline(admin.TabularInline):
    model = PaymentNetwork
    extra = 0


@admin.register(PaymentCurrency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'rate_toman', 'rate_updated_at', 'is_active']
    inlines = [NetworkInline]


@admin.register(PaymentInvoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['id', 'order', 'provider', 'currency', 'network', 'amount_crypto', 'status', 'created_at']
    list_filter = ['provider', 'status', 'currency']
    search_fields = ['id', 'provider_ref', 'order__number', 'address', 'tx_hash']
    readonly_fields = [f.name for f in PaymentInvoice._meta.fields]


@admin.register(ProcessedEvent)
class ProcessedEventAdmin(admin.ModelAdmin):
    list_display = ['event_id', 'invoice', 'result', 'created_at']
    readonly_fields = ['event_id', 'invoice', 'payload', 'result', 'created_at']
