from django.urls import path

from . import catalog_views as c
from . import dashboard_views as d
from . import order_views as o
from . import settings_views as s
from . import support_views as t
from . import user_views as u

urlpatterns = [
    path('dashboard', d.dashboard),
    path('categories', c.categories),
    path('categories/<int:pk>', c.category_detail),
    path('providers', c.providers),
    path('providers/<int:pk>', c.provider_detail),
    path('products', c.products),
    path('products/<str:pk>', c.product_detail),
    path('products/<str:pk>/image', c.product_image),
    path('products/<str:pk>/variants', c.product_variants),
    path('variants/<str:pk>', c.variant_detail),
    path('variants/<str:pk>/codes', c.variant_codes),
    path('codes/<int:pk>/void', c.code_void),
    path('orders', o.orders),
    path('orders/<str:pk>', o.order_detail),
    path('orders/<str:pk>/status', o.order_status),
    path('orders/<str:pk>/deliveries', o.order_delivery),
    path('orders/<str:pk>/notes', o.order_note),
    path('orders/<str:pk>/fulfill', o.order_autofulfill),
    path('users', u.users),
    path('users/<str:pk>', u.user_detail),
    path('users/<str:pk>/password', u.user_password),
    path('tickets', t.tickets),
    path('tickets/<str:pk>', t.ticket_detail),
    path('tickets/<str:pk>/reply', t.ticket_reply),
    path('settings', s.site_settings),
    path('currencies', s.currencies),
    path('currencies/<int:pk>', s.currency_detail),
    path('currencies/<int:pk>/networks', s.currency_networks),
    path('networks/<int:pk>', s.network_detail),
]
