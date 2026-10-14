from django.contrib import admin

from .models import Ticket, TicketMessage


class MessageInline(admin.TabularInline):
    model = TicketMessage
    extra = 0


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ['number', 'user', 'subject', 'status', 'updated_at']
    list_filter = ['status']
    search_fields = ['number', 'subject', 'user__email']
    raw_id_fields = ['user', 'order']
    inlines = [MessageInline]
