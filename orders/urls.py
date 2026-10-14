from django.urls import path

from . import views

urlpatterns = [
    path('', views.orders),
    path('<str:order_id>', views.order_detail),
    path('<str:order_id>/cancel', views.cancel),
    path('<str:order_id>/invoice', views.new_invoice),
]
