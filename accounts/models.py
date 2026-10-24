from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models

from core.ids import user_id


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email).lower()
        extra.setdefault('full_name', email.split('@')[0])
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.update(is_staff=True, is_superuser=True, email_verified=True)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.CharField(primary_key=True, max_length=40, default=user_id, editable=False)
    email = models.EmailField('ایمیل', unique=True)
    full_name = models.CharField('نام و نام خانوادگی', max_length=120)
    phone = models.CharField('موبایل', max_length=11, unique=True, null=True, blank=True)
    email_verified = models.BooleanField('ایمیل تأیید شده', default=False)
    google_sub = models.CharField('شناسه گوگل', max_length=255, unique=True, null=True, blank=True, editable=False)
    verification_code = models.CharField(max_length=6, blank=True, default='')
    verification_sent_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField('فعال', default=True)
    is_staff = models.BooleanField('مدیر', default=False)
    admin_note = models.TextField('یادداشت مدیر', blank=True)
    created_at = models.DateTimeField('تاریخ عضویت', auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    EMAIL_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = 'کاربر'
        verbose_name_plural = 'کاربران'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.full_name} <{self.email}>'
