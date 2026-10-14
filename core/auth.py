from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import BasePermission

from .errors import ApiError


class CookieSessionAuthentication(SessionAuthentication):
    """
    Session-cookie auth for the Nuxt frontend. CSRF tokens are replaced by
    core.middleware.ApiOriginCheckMiddleware (strict Origin allow-list) plus SameSite=Lax cookies.
    """

    def enforce_csrf(self, request):
        return

    def authenticate_header(self, request):
        return 'Session'  # makes DRF answer 401 (not 403) for anonymous users


def require_user(request):
    user = request.user
    if not user or not user.is_authenticated or not user.is_active:
        raise ApiError(401, 'برای ادامه وارد حساب کاربری شوید.', code='not_authenticated')
    return user


class IsStaff(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            raise ApiError(401, 'برای ادامه وارد حساب کاربری شوید.', code='not_authenticated')
        return bool(user.is_active and user.is_staff)
