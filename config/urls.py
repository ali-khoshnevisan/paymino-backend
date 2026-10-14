from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from orders.views import orders, quote
from payments.views import dev_simulate

urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('api/auth/', include('accounts.urls')),
    path('api/catalog/', include('catalog.urls')),
    path('api/cart/quote', quote),
    path('api/orders/', include('orders.urls')),
    path('api/orders', orders),
    path('api/payments/', include('payments.urls')),
    path('api/support/', include('support.urls')),
    path('api/admin/', include('adminapi.urls')),
    path('api/dev/orders/<str:order_id>/simulate', dev_simulate),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
