from django.urls import path

from . import views

urlpatterns = [
    path('currencies', views.currencies),
    path('webhook', views.sandbox_webhook),
    path('plisio/callback', views.plisio_callback),
]
