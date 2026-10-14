from django.urls import path

from . import views

urlpatterns = [
    path('register', views.register),
    path('login', views.login_view),
    path('logout', views.logout_view),
    path('me', views.me),
    path('change-password', views.change_password),
    path('verify-email', views.verify_email),
    path('resend-verification', views.resend_verification),
    path('password-reset', views.password_reset),
    path('password-reset-confirm', views.password_reset_confirm),
]
