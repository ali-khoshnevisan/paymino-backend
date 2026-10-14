from django.conf import settings
from django.db import models

from core.ids import ticket_id

TICKET_STATUSES = [('open', 'باز'), ('answered', 'پاسخ داده شد'), ('closed', 'بسته')]


class Ticket(models.Model):
    id = models.CharField(primary_key=True, max_length=40, default=ticket_id, editable=False)
    number = models.CharField(max_length=20, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tickets')
    subject = models.CharField(max_length=200)
    order = models.ForeignKey('orders.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='tickets')
    status = models.CharField(max_length=10, choices=TICKET_STATUSES, default='open', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'درخواست پشتیبانی'
        verbose_name_plural = 'درخواست‌های پشتیبانی'


class TicketMessage(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='messages')
    from_staff = models.BooleanField(default=False)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    body = models.TextField()
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['at', 'id']
