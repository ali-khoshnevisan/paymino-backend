# Paymino backend (Django REST)

Implements the API contract in the Nuxt repo (`paymino/shared/types/index.ts` and `admin.ts`) — same JSON shapes as the mock, so the frontend only needs `NUXT_PUBLIC_API_BASE` pointed here.

Apps: `accounts` (users, session auth) · `catalog` (categories, brands, products, variants, gift-code stock) · `orders` (quote, orders, fulfilment) · `payments` (currencies/rates, invoices, Plisio + sandbox gateways) · `support` (tickets) · `adminapi` (staff API for the Nuxt admin panel).

## Local development

```bash
pip install -r requirements.txt
cp .env.example .env    # then set: DEBUG=1, PAYMENT_PROVIDER=sandbox, local DATABASE_URL, http://localhost URLs, SESSION_COOKIE_DOMAIN empty
python manage.py migrate
python manage.py createcachetable
python manage.py seed_demo --codes        # SAMPLE catalog, rates and fake codes
python manage.py createsuperuser          # your admin login
python manage.py runserver 8000
```

Frontend: `NUXT_PUBLIC_API_BASE=http://localhost:8000/api npm run dev` → shop at `/`, admin panel at `/admin`.
Tests: `python manage.py test tests` (needs Postgres; 24 tests).

## How the important parts work

- **Auth**: Django session cookie `pm_session` (HttpOnly, SameSite=Lax). No CSRF token needed by the frontend — state-changing `/api/` calls must carry an `Origin` from `CORS_ALLOWED_ORIGINS`/`FRONTEND_URL`. Login/register/reset are throttled.
- **Prices**: always computed server-side (`orders/pricing.py`). Orders are rejected (409 `quote_changed`) if price/stock changed since the customer's quote. `Idempotency-Key` prevents double orders.
- **Payments**: each invoice locks the Toman total and converts it at the admin-set rate, rounding *up*. Payment state changes only via verified gateway events (`payments/services.apply_payment_event`), idempotent per event. Under/over/late payments mark the order **needs review**.
- **Delivery**: variants with stock mode *codes* auto-deliver from the code stock right after payment confirms; if stock runs short the order stays *processing* and is flagged. *Manual* variants (subscriptions) are delivered from the admin order page.
- **Admin**: everything under `/api/admin/` requires `is_staff`. Only superusers can grant/revoke staff. The Django admin is still at `/django-admin/` for emergencies.

## Plisio setup

1. In Plisio → API settings: copy the **Secret key** into `PLISIO_SECRET_KEY`, set `PAYMENT_PROVIDER=plisio`.
2. Enable **White-label** for the shop. Without it Plisio returns no wallet address and invoice creation fails with `gateway_misconfigured`.
3. Each payment network needs its Plisio ID (`gatewayCode`) in Admin → Settings: `USDT_TRX`, `USDT_BSC`, `TRX`, `BTC`, `TON`, …
4. Callbacks go to `https://api.paymino.ir/api/payments/plisio/callback?json=true` (sent automatically per invoice). The `verify_hash` is checked with the secret key.
5. **Before going live, make one small real payment** and confirm the order moves to *processing*. Plisio's docs are inconsistent about the exact callback signature format; the code accepts the documented variants, and a rejected callback is logged as `Plisio callback with invalid verify_hash`.
6. Keep the Toman rates in Admin → Settings current — they are manual.

## Production (Ubuntu + nginx + gunicorn)

```bash
python manage.py migrate && python manage.py createcachetable && python manage.py collectstatic --noinput
gunicorn config.wsgi:application --bind 127.0.0.1:8001 --workers 3
```

nginx for `api.paymino.ir`: proxy `/` to `127.0.0.1:8001` with `X-Forwarded-For` and `X-Forwarded-Proto`, serve `/static/` from `staticfiles/` and `/media/` from `media/`. Nuxt: `NUXT_PUBLIC_API_BASE=https://api.paymino.ir/api`. Site and API must share the parent domain (`SESSION_COOKIE_DOMAIN=.paymino.ir`) so the session cookie works for both browser calls and SSR.

## Notes

- Gift codes are stored in plaintext in Postgres. Restrict DB access, encrypt backups, and only give staff access to people you trust — staff can see codes.
- `seed_demo` data (prices, rates, fake `FAKE-…` codes) is placeholder: replace or delete before launch.
