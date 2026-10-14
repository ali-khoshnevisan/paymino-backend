from django.contrib import admin

from .models import SiteSettings

admin.site.site_header = 'پی‌مینو — مدیریت فنی'
admin.site.site_title = 'پی‌مینو'
admin.site.register(SiteSettings)
