from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.response import Response

from accounts.models import User
from catalog.models import variants_with_stock
from core.models import SiteSettings
from orders.models import Order
from support.models import Ticket

from .common import staff_view
from .dto import admin_order_row

PAID_STATES = ['paid', 'processing', 'awaiting_customer_info', 'completed']


@staff_view(['GET'])
def dashboard(request):
    now = timezone.now()
    local_today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    since30 = local_today - timedelta(days=29)

    def revenue(since):
        return int(Order.objects.filter(status__in=PAID_STATES, created_at__gte=since).aggregate(s=Sum('total_toman'))['s'] or 0)

    def orders_count(since):
        return Order.objects.filter(created_at__gte=since).count()

    by_status = dict(Order.objects.values_list('status').annotate(n=Count('id')))
    daily = {
        row['d']: (int(row['rev'] or 0), row['n'])
        for row in Order.objects.filter(created_at__gte=since30)
        .annotate(d=TruncDate('created_at', tzinfo=timezone.get_current_timezone()))
        .values('d').annotate(n=Count('id'), rev=Sum('total_toman', filter=Q(status__in=PAID_STATES)))
    }
    series = []
    for i in range(30):
        day = (since30 + timedelta(days=i)).date()
        rev, n = daily.get(day, (0, 0))
        series.append({'date': day.isoformat(), 'revenueToman': rev, 'orders': n})

    threshold = SiteSettings.get().low_stock_threshold
    low_stock = [
        {'variantId': v.id, 'productId': v.product_id, 'productName': v.product.name, 'label': v.label, 'stock': v.stock_available}
        for v in variants_with_stock().select_related('product').filter(stock_mode='codes', is_active=True, product__is_active=True)
        if v.stock_available <= threshold
    ]
    action_qs = Order.objects.select_related('user').prefetch_related('items').filter(
        Q(status__in=['paid', 'processing', 'awaiting_customer_info', 'refund_pending', 'payment_verification']) | Q(needs_review=True)
    ).order_by('created_at')

    return Response({
        'revenue': {'today': revenue(local_today), 'last7Days': revenue(local_today - timedelta(days=6)), 'last30Days': revenue(since30)},
        'orders': {'today': orders_count(local_today), 'last30Days': orders_count(since30), 'byStatus': by_status},
        'users': {'total': User.objects.count(), 'newLast30Days': User.objects.filter(created_at__gte=since30).count()},
        'openTickets': Ticket.objects.filter(status='open').count(),
        'needsAction': {'count': action_qs.count(), 'results': [admin_order_row(o) for o in action_qs[:10]]},
        'lowStock': sorted(low_stock, key=lambda x: x['stock'])[:20],
        'series': series,
    })
