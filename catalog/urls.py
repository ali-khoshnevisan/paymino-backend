from django.urls import path

from . import views

urlpatterns = [
    path('categories', views.categories),
    path('products', views.products),
    path('products/<slug:slug>', views.product_detail),
]
