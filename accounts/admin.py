from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ['-created_at']
    list_display = ['email', 'full_name', 'phone', 'email_verified', 'is_staff', 'is_active', 'created_at']
    search_fields = ['email', 'full_name', 'phone']
    list_filter = ['is_staff', 'is_active', 'email_verified']
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('اطلاعات', {'fields': ('full_name', 'phone', 'email_verified', 'admin_note')}),
        ('دسترسی', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
    )
    add_fieldsets = ((None, {'classes': ('wide',), 'fields': ('email', 'full_name', 'password1', 'password2')}),)
