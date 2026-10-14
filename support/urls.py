from django.urls import path

from . import views

urlpatterns = [
    path('tickets', views.tickets),
    path('tickets/<str:ticket_id>', views.ticket_detail),
    path('tickets/<str:ticket_id>/messages', views.ticket_message),
]
