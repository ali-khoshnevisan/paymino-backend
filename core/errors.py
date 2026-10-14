"""DRF-shaped errors: { detail, code, errors } — matches the frontend's normalizeApiError."""
from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response


class ApiError(exceptions.APIException):
    def __init__(self, status_code: int, detail: str, code: str | None = None, **extra):
        self.status_code = status_code
        self.payload = {'detail': detail}
        if code:
            self.payload['code'] = code
        self.payload.update(extra)
        super().__init__(detail=detail, code=code)


def field_errors(errors: dict[str, list[str]]):
    raise ApiError(400, 'اطلاعات واردشده معتبر نیست.', code='validation_error', errors=errors)


def exception_handler(exc, context):
    if isinstance(exc, ApiError):
        return Response(exc.payload, status=exc.status_code)
    if isinstance(exc, Http404):
        return Response({'detail': 'موردی یافت نشد.', 'code': 'not_found'}, status=404)
    if isinstance(exc, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed)):
        return Response({'detail': 'برای ادامه وارد حساب کاربری شوید.', 'code': 'not_authenticated'}, status=401)
    if isinstance(exc, (exceptions.PermissionDenied, PermissionDenied)):
        return Response({'detail': 'اجازه دسترسی به این بخش را ندارید.', 'code': 'permission_denied'}, status=403)
    if isinstance(exc, exceptions.ParseError):
        return Response({'detail': 'درخواست نامعتبر است.', 'code': 'parse_error'}, status=400)
    if isinstance(exc, exceptions.MethodNotAllowed):
        return Response({'detail': 'Method not allowed', 'code': 'method_not_allowed'}, status=405)
    if isinstance(exc, exceptions.UnsupportedMediaType):
        return Response({'detail': 'Unsupported media type', 'code': 'unsupported_media_type'}, status=415)
    if isinstance(exc, exceptions.ValidationError):
        detail = exc.detail
        errors = {k: [str(m) for m in (v if isinstance(v, list) else [v])] for k, v in detail.items()} if isinstance(detail, dict) else {}
        return Response({'detail': 'اطلاعات واردشده معتبر نیست.', 'code': 'validation_error', 'errors': errors}, status=400)
    if isinstance(exc, exceptions.APIException):
        return Response({'detail': str(exc.detail)}, status=exc.status_code)
    return None  # unhandled → 500 (logged by Django)
