import json
from urllib.parse import urlparse

from django.conf import settings
from django.http import HttpResponse

SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS', 'TRACE'}
# Server-to-server endpoints (authenticated by signatures instead)
EXEMPT_PREFIXES = ('/api/payments/webhook', '/api/payments/plisio/')


def _origin_of(url: str) -> str | None:
    try:
        u = urlparse(url)
    except ValueError:
        return None
    if not u.scheme or not u.netloc:
        return None
    return f'{u.scheme}://{u.netloc}'


class ApiOriginCheckMiddleware:
    """
    CSRF protection for the cookie-authenticated JSON API: state-changing requests to /api/
    must come from an allowed browser origin. (The Django admin keeps Django's normal CSRF.)
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith('/api/') and request.method not in SAFE_METHODS and not path.startswith(EXEMPT_PREFIXES):
            origin = request.headers.get('Origin') or _origin_of(request.headers.get('Referer', ''))
            if not origin or origin not in settings.API_ALLOWED_ORIGINS:
                body = json.dumps({'detail': 'درخواست از مبدأ نامعتبر ارسال شده است.', 'code': 'bad_origin'}, ensure_ascii=False)
                return HttpResponse(body, status=403, content_type='application/json; charset=utf-8')
        return self.get_response(request)
