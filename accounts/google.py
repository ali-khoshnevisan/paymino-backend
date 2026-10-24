"""Sign in with Google: OAuth 2.0 authorization-code flow with PKCE, run entirely on the server.

/api/auth/google/start     → redirects the browser to Google (state, nonce and PKCE verifier kept in the session)
/api/auth/google/callback  → exchanges the code for Google's ID token, signs the user in, redirects to the site

The ID token comes straight from Google's token endpoint over TLS in exchange for our client secret, so its
claims are checked (issuer, audience, expiry, nonce) without a separate signature check (OpenID Connect Core §3.1.3.7).
"""
import base64
import hashlib
import json
import logging
import secrets
import time
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.contrib.auth import login
from django.db import IntegrityError, transaction
from django.shortcuts import redirect
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.errors import ApiError
from core.utils import client_ip, throttle

from .models import User

log = logging.getLogger(__name__)

AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
ISSUERS = {'accounts.google.com', 'https://accounts.google.com'}
SESSION_KEY = 'google_oauth'
FLOW_TTL = 600  # seconds the visitor has to finish at Google


class GoogleError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def enabled() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def _redirect_uri() -> str:
    return f'{settings.API_PUBLIC_URL}/api/auth/google/callback'


def safe_next(value) -> str:
    """Only a path on our own site: no scheme, no host, no protocol-relative or backslash tricks."""
    v = str(value or '')
    if not v.startswith('/') or v.startswith('//') or '\\' in v or len(v) > 500 or any(ord(c) < 32 for c in v):
        return '/account'
    return v


def _to_site(path: str):
    return redirect(f'{settings.FRONTEND_URL}{path}')


def _to_login(error: str, next_path: str):
    return _to_site('/auth/login?' + urlencode({'error': f'google_{error}', 'redirect': next_path}))


@api_view(['GET'])
def providers(request):
    """Which extra sign-in options the site should offer."""
    return Response({'google': enabled()})


@api_view(['GET'])
def google_start(request):
    next_path = safe_next(request.query_params.get('next'))
    if not enabled():
        return _to_login('unavailable', next_path)
    try:
        throttle(f'google-start:{client_ip(request)}', 30, 600)
    except ApiError:
        return _to_login('throttled', next_path)

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    flow = {'state': secrets.token_urlsafe(32), 'nonce': secrets.token_urlsafe(32), 'verifier': verifier,
            'next': next_path, 'at': int(time.time())}
    request.session[SESSION_KEY] = flow
    params = {
        'client_id': settings.GOOGLE_CLIENT_ID,
        'redirect_uri': _redirect_uri(),
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': flow['state'],
        'nonce': flow['nonce'],
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
        'prompt': 'select_account',
    }
    return redirect(f'{AUTH_URL}?{urlencode(params)}')


def _decode_claims(id_token: str) -> dict:
    try:
        payload = id_token.split('.')[1]
        return json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
    except (IndexError, ValueError):
        raise GoogleError('failed')


def _exchange(code: str, flow: dict) -> dict:
    try:
        r = requests.post(TOKEN_URL, data={
            'code': code,
            'client_id': settings.GOOGLE_CLIENT_ID,
            'client_secret': settings.GOOGLE_CLIENT_SECRET,
            'redirect_uri': _redirect_uri(),
            'grant_type': 'authorization_code',
            'code_verifier': flow['verifier'],
        }, timeout=10)
    except requests.RequestException:
        log.warning('Google token endpoint unreachable')
        raise GoogleError('failed')
    if r.status_code != 200 or 'id_token' not in r.json():
        log.warning('Google token exchange failed: %s %s', r.status_code, r.text[:200])
        raise GoogleError('failed')
    claims = _decode_claims(r.json()['id_token'])
    if (claims.get('iss') not in ISSUERS or claims.get('aud') != settings.GOOGLE_CLIENT_ID
            or int(claims.get('exp', 0)) < time.time() or claims.get('nonce') != flow['nonce'] or not claims.get('sub')):
        log.warning('Google ID token rejected (iss/aud/exp/nonce)')
        raise GoogleError('failed')
    if claims.get('email_verified') is not True or not claims.get('email'):
        raise GoogleError('email_unverified')
    return claims


@transaction.atomic
def user_for_claims(claims: dict) -> User:
    """The account for this Google identity: linked before, or the account with the same (verified) email, or a new one."""
    sub, email = str(claims['sub']), str(claims['email']).strip().lower()
    user = User.objects.select_for_update().filter(google_sub=sub).first()
    if not user:
        user = User.objects.select_for_update().filter(email=email).first()
        if user and user.google_sub and user.google_sub != sub:
            raise GoogleError('conflict')  # this email is already linked to a different Google account
    if not user:
        name = str(claims.get('name') or '').strip()[:120] or email.split('@')[0]
        try:
            user = User.objects.create_user(email=email, password=None, full_name=name, email_verified=True, google_sub=sub)
        except IntegrityError:
            raise GoogleError('failed')
        return user  # create_user() leaves an unusable password: the account signs in with Google until one is set
    if not user.is_active:
        raise GoogleError('disabled')
    changed = []
    if user.google_sub != sub:
        user.google_sub = sub
        changed.append('google_sub')
    if not user.email_verified:
        user.email_verified = True  # Google has verified this address
        changed.append('email_verified')
    if changed:
        user.save(update_fields=changed)
    return user


@api_view(['GET'])
def google_callback(request):
    flow = request.session.pop(SESSION_KEY, None) or {}
    next_path = safe_next(flow.get('next'))
    q = request.query_params
    if q.get('error'):
        return _to_login('cancelled' if q.get('error') == 'access_denied' else 'failed', next_path)
    # The state proves this callback answers the request this browser started (no login CSRF)
    if not flow or not q.get('state') or not secrets.compare_digest(str(q.get('state')), flow.get('state', '')) \
            or time.time() - flow.get('at', 0) > FLOW_TTL or not q.get('code'):
        return _to_login('expired', next_path)
    try:
        throttle(f'google-callback:{client_ip(request)}', 30, 600)
        user = user_for_claims(_exchange(str(q['code']), flow))
    except GoogleError as e:
        return _to_login(e.code, next_path)
    except ApiError:  # throttled
        return _to_login('throttled', next_path)

    request.session.cycle_key()
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    return _to_site(next_path)
