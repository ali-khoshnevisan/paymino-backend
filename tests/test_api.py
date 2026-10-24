import base64
import hashlib
import hmac
import json
import time
from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from catalog.models import GiftCode, Product, Variant
from orders.models import Coupon, Order
from payments.models import PaymentInvoice

ORIGIN = 'http://localhost:3000'


class Client(APIClient):
    def generic(self, method, path, data='', content_type='application/octet-stream', secure=False, **extra):
        extra.setdefault('HTTP_ORIGIN', ORIGIN)
        return super().generic(method, path, data, content_type, secure=secure, **extra)


def tv_item(line='l2'):
    return {'lineId': line, 'productId': 'p_tradingview', 'variantId': 'tv-plus-1', 'quantity': 1,
            'fields': {'tv_username': 'bob', 'account_email': 'bob@x.com'}}


def steam_item(qty=2, line='l1'):
    return {'lineId': line, 'productId': 'p_steam_us', 'variantId': 'steam-us-20', 'quantity': qty, 'fields': {}}


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo', '--codes', stdout=open('/dev/null', 'w'))
        call_command('createcachetable', verbosity=0)

    def setUp(self):
        self.c = Client()
        self.user = User.objects.create_user('u@test.ir', 'Test1234', full_name='کاربر تست')
        self.c.force_login(self.user)

    def place(self, items, currency='USDT', network='TRC20', key=None):
        q = self.c.post('/api/cart/quote', {'items': items}, format='json').json()
        headers = {'HTTP_IDEMPOTENCY_KEY': key} if key else {}
        return self.c.post('/api/orders', {'items': items, 'currency': currency, 'network': network, 'acceptedTerms': True,
                                           'expectedTotalToman': q['totalToman']}, format='json', **headers)

    def simulate(self, order_id, event):
        return self.c.post(f'/api/dev/orders/{order_id}/simulate', {'event': event}, format='json')


@override_settings(DEBUG=True, PAYMENT_PROVIDER='sandbox')
class PublicApiTests(Base):
    def test_origin_check(self):
        anon = APIClient()
        r = anon.post('/api/auth/login', {'identifier': 'x', 'password': 'y'}, format='json')
        self.assertEqual(r.status_code, 403)
        r = anon.post('/api/auth/login', {'identifier': 'x', 'password': 'y'}, format='json', HTTP_ORIGIN='https://evil.example')
        self.assertEqual(r.status_code, 403)

    def test_auth_flow(self):
        anon = Client()
        self.assertEqual(anon.get('/api/auth/me').status_code, 401)
        r = anon.post('/api/auth/register', {'fullName': 'ab', 'email': 'bad', 'password': '123'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(set(r.json()['errors']), {'fullName', 'email', 'password'})
        r = anon.post('/api/auth/register', {'fullName': 'سارا تست', 'email': 'S@x.com', 'phone': '۰۹۱۲۱۲۳۴۵۶۷', 'password': 'Abc12345'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['user']['phone'], '09121234567')
        self.assertFalse(r.json()['user']['emailVerified'])
        u = User.objects.get(email='s@x.com')
        r = anon.post('/api/auth/verify-email', {'code': u.verification_code}, format='json')
        self.assertTrue(r.json()['user']['emailVerified'])
        anon.post('/api/auth/logout')
        self.assertEqual(anon.get('/api/auth/me').status_code, 401)
        r = anon.post('/api/auth/login', {'identifier': '09121234567', 'password': 'wrong1234'}, format='json')
        self.assertEqual(r.json()['code'], 'invalid_credentials')
        r = anon.post('/api/auth/login', {'identifier': '09121234567', 'password': 'Abc12345'}, format='json')
        self.assertEqual(r.status_code, 200)

    def test_password_reset(self):
        from accounts.views import _make_reset_token
        anon = Client()
        self.assertEqual(anon.post('/api/auth/password-reset', {'email': 'nobody@x.com'}, format='json').status_code, 200)
        token = _make_reset_token(self.user)
        r = anon.post('/api/auth/password-reset-confirm', {'token': token, 'password': 'NewPass99'}, format='json')
        self.assertEqual(r.status_code, 200)
        r = anon.post('/api/auth/password-reset-confirm', {'token': token, 'password': 'NewPass99'}, format='json')
        self.assertEqual(r.json()['code'], 'invalid_token')  # single use
        self.assertEqual(self.c.get('/api/auth/me').status_code, 401)  # old sessions invalidated

    def test_catalog(self):
        r = self.c.get('/api/catalog/products?q=استیم&ordering=price_asc').json()
        self.assertEqual(r['count'], 2)
        self.assertEqual(r['facets']['providers'][0]['value'], 'steam')
        p = self.c.get('/api/catalog/products/steam-wallet-eur').json()
        self.assertNotIn('steam-eu-100', [v['id'] for v in p['variants']])  # inactive variant hidden
        self.assertEqual(self.c.get('/api/catalog/products/nope').status_code, 404)

    def test_order_gift_card_auto_delivery(self):
        r = self.place([steam_item(2)], key='abc')
        self.assertEqual(r.status_code, 201, r.content)
        order = r.json()
        self.assertEqual(order['invoice']['amountCrypto'], '43.05')  # 4541000 / 105500 = 43.0426 → rounded up
        self.assertEqual(self.place([steam_item(2)], key='abc').json()['id'], order['id'])  # idempotent
        self.simulate(order['id'], 'detected')
        r = self.simulate(order['id'], 'confirmed').json()
        self.assertEqual(r['status'], 'completed')
        self.assertEqual(len(r['items'][0]['deliveries']), 2)
        self.assertEqual(GiftCode.objects.filter(variant_id='steam-us-20', status='available').count(), 1)

    def test_out_of_stock_variant_unavailable(self):
        GiftCode.objects.filter(variant_id='steam-us-20').update(status='void')
        q = self.c.post('/api/cart/quote', {'items': [steam_item(1)]}, format='json').json()
        self.assertFalse(q['lines'][0]['available'])

    def test_price_change_blocks_order(self):
        items = [steam_item(1)]
        q = self.c.post('/api/cart/quote', {'items': items}, format='json').json()
        Variant.objects.filter(pk='steam-us-20').update(price_toman=9_999_000)
        r = self.c.post('/api/orders', {'items': items, 'currency': 'USDT', 'network': 'TRC20', 'acceptedTerms': True,
                                        'expectedTotalToman': q['totalToman']}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()['code'], 'quote_changed')

    def test_product_discount(self):
        Product.objects.filter(pk='p_steam_us').update(discount_percent=10)
        card = next(i for i in self.c.get('/api/catalog/products?category=steam').json()['results'] if i['slug'] == 'steam-wallet-usd')
        self.assertEqual(card['discountPercent'], 10)
        self.assertLess(card['minPriceToman'], card['minOriginalPriceToman'])
        detail = self.c.get('/api/catalog/products/steam-wallet-usd').json()
        v = next(x for x in detail['variants'] if x['id'] == 'steam-us-20')
        self.assertEqual((v['priceToman'], v['originalPriceToman']), (2_003_000, 2_226_000))  # 2,003,400 → rounded to 1,000

        q = self.c.post('/api/cart/quote', {'items': [steam_item(2)]}, format='json').json()
        line = q['lines'][0]
        self.assertEqual((line['unitPriceToman'], line['listUnitPriceToman'], line['lineTotalToman']), (2_003_000, 2_226_000, 4_006_000))
        self.assertEqual((q['subtotalToman'], q['discountToman']), (4_452_000, 446_000))
        self.assertEqual(q['totalToman'], q['subtotalToman'] - q['discountToman'] + q['serviceFeeToman'])
        r = self.place([steam_item(2)])
        self.assertEqual(r.status_code, 201, r.content)
        order = r.json()
        self.assertEqual((order['discountToman'], order['totalToman']), (446_000, q['totalToman']))
        self.assertEqual(order['items'][0]['unitPriceToman'], 2_003_000)

    def test_discount_window(self):
        past, future = timezone.now() - timedelta(days=1), timezone.now() + timedelta(days=1)
        for starts, ends in ((None, past), (future, None)):
            Product.objects.filter(pk='p_steam_us').update(discount_percent=20, discount_starts_at=starts, discount_ends_at=ends)
            card = next(i for i in self.c.get('/api/catalog/products?category=steam').json()['results'] if i['slug'] == 'steam-wallet-usd')
            self.assertIsNone(card['discountPercent'])
            self.assertIsNone(card['minOriginalPriceToman'])
            q = self.c.post('/api/cart/quote', {'items': [steam_item(1)]}, format='json').json()
            self.assertEqual((q['lines'][0]['unitPriceToman'], q['discountToman']), (2_226_000, 0))

    def test_discount_ending_blocks_stale_order(self):
        Product.objects.filter(pk='p_steam_us').update(discount_percent=10)
        items = [steam_item(1)]
        q = self.c.post('/api/cart/quote', {'items': items}, format='json').json()
        Product.objects.filter(pk='p_steam_us').update(discount_ends_at=timezone.now() - timedelta(seconds=1))
        r = self.c.post('/api/orders', {'items': items, 'currency': 'USDT', 'network': 'TRC20', 'acceptedTerms': True,
                                        'expectedTotalToman': q['totalToman']}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()['code'], 'quote_changed')

    def coupon_quote(self, code, items=None):
        return self.c.post('/api/cart/quote', {'items': items or [steam_item(1)], 'couponCode': code}, format='json').json()

    def place_with(self, code, items=None):
        items = items or [steam_item(1)]
        q = self.coupon_quote(code, items)
        return self.c.post('/api/orders', {'items': items, 'currency': 'USDT', 'network': 'TRC20', 'acceptedTerms': True,
                                           'couponCode': code, 'expectedTotalToman': q['totalToman']}, format='json')

    def test_coupon_quote_and_order(self):
        Coupon.objects.create(code='SAVE10', kind='percent', value=10, max_discount_toman=100_000, per_user_limit=1)
        q = self.coupon_quote(' save۱۰ ')  # any case, Persian digits, stray spaces
        self.assertEqual((q['coupon']['code'], q['coupon']['valid'], q['couponDiscountToman']), ('SAVE10', True, 100_000))  # 10% capped
        payable = sum(l['lineTotalToman'] for l in q['lines'])
        self.assertEqual(q['totalToman'], payable - 100_000 + q['serviceFeeToman'])
        no_code = self.coupon_quote('')
        self.assertLess(q['serviceFeeToman'], no_code['serviceFeeToman'] + 1)  # fee is charged on the reduced amount
        self.assertIsNone(no_code['coupon'])

        r = self.place_with('SAVE10')
        self.assertEqual(r.status_code, 201, r.content)
        order = r.json()
        self.assertEqual((order['couponCode'], order['couponDiscountToman'], order['totalToman']), ('SAVE10', 100_000, q['totalToman']))

        # per-user limit: the same user cannot use it again…
        self.assertEqual(self.coupon_quote('SAVE10')['coupon']['reason'], 'coupon_used_by_user')
        r = self.place_with('SAVE10')
        self.assertEqual((r.status_code, r.json()['code']), (409, 'coupon_invalid'))
        # …until the order that used it is cancelled
        self.c.post(f"/api/orders/{order['id']}/cancel", {}, format='json')
        self.assertTrue(self.coupon_quote('SAVE10')['coupon']['valid'])

    def test_coupon_rejections(self):
        past, future = timezone.now() - timedelta(days=1), timezone.now() + timedelta(days=1)
        Coupon.objects.create(code='OLD', kind='percent', value=10, ends_at=past)
        Coupon.objects.create(code='SOON', kind='percent', value=10, starts_at=future)
        Coupon.objects.create(code='OFF', kind='percent', value=10, is_active=False)
        Coupon.objects.create(code='BIGORDER', kind='percent', value=10, min_order_toman=50_000_000)
        Coupon.objects.create(code='ONCE', kind='fixed', value=50_000, usage_limit=1, per_user_limit=None)
        reasons = {c: self.coupon_quote(c)['coupon']['reason'] for c in ('NOPE', 'OLD', 'SOON', 'OFF', 'BIGORDER', '<script>')}
        self.assertEqual(reasons, {'NOPE': 'coupon_invalid', 'OLD': 'coupon_expired', 'SOON': 'coupon_invalid', 'OFF': 'coupon_invalid',
                                   'BIGORDER': 'coupon_min_order', '<script>': 'coupon_invalid'})
        bad = self.coupon_quote('OLD')
        self.assertEqual((bad['couponDiscountToman'], bad['totalToman']), (0, self.coupon_quote('')['totalToman']))

        # total usage limit is shared between users
        self.assertEqual(self.place_with('ONCE').status_code, 201)
        other = Client()
        other.force_login(User.objects.create_user('o@test.ir', 'Test1234', full_name='دیگری'))
        q = other.post('/api/cart/quote', {'items': [steam_item(1)], 'couponCode': 'ONCE'}, format='json').json()
        self.assertEqual(q['coupon']['reason'], 'coupon_used_up')

    def test_coupon_guessing_is_throttled(self):
        from django.core.cache import cache
        cache.clear()
        codes = [self.c.post('/api/cart/quote', {'items': [steam_item(1)], 'couponCode': f'GUESS{i}'}, format='json').status_code for i in range(22)]
        self.assertEqual(codes[:20], [200] * 20)
        self.assertEqual(codes[-1], 429)
        cache.clear()

    def test_fixed_coupon_never_zeroes_the_total(self):
        Coupon.objects.create(code='HUGE', kind='fixed', value=10**9)
        q = self.coupon_quote('HUGE')
        payable = sum(l['lineTotalToman'] for l in q['lines'])
        self.assertEqual(q['couponDiscountToman'], payable - 1000)
        self.assertGreater(q['totalToman'], 0)

    def test_required_fields_validated(self):
        item = tv_item()
        item['fields'] = {'tv_username': '', 'account_email': 'bad'}
        r = self.place([item])
        self.assertEqual(set(r.json()['errors']), {'l2.tv_username', 'l2.account_email'})

    def test_underpaid_and_reinvoice(self):
        order = self.place([tv_item()]).json()
        r = self.simulate(order['id'], 'underpaid').json()
        self.assertEqual(r['paymentStatus'], 'underpaid')
        self.assertTrue(Order.objects.get(pk=order['id']).needs_review)
        order2 = self.place([tv_item('x')]).json()
        self.simulate(order2['id'], 'expired')
        r = self.c.post(f"/api/orders/{order2['id']}/invoice", {'currency': 'TRX', 'network': 'TRC20'}, format='json').json()
        self.assertEqual(r['invoice']['currency'], 'TRX')
        self.assertEqual(r['paymentStatus'], 'awaiting_payment')

    def test_cancel_and_ownership(self):
        order = self.place([tv_item()]).json()
        other = Client()
        other.force_login(User.objects.create_user('o@test.ir', 'Test1234'))
        self.assertEqual(other.get(f"/api/orders/{order['id']}").status_code, 404)
        r = self.c.post(f"/api/orders/{order['id']}/cancel").json()
        self.assertEqual(r['status'], 'cancelled')
        self.assertEqual(r['invoice']['status'], 'expired')

    def test_lazy_expiry(self):
        order = self.place([tv_item()]).json()
        PaymentInvoice.objects.filter(pk=order['invoice']['id']).update(expires_at=Order.objects.get(pk=order['id']).created_at - timedelta(minutes=1))
        r = self.c.get(f"/api/orders/{order['id']}").json()
        self.assertEqual(r['paymentStatus'], 'expired')

    def test_sandbox_webhook_signature(self):
        order = self.place([tv_item()]).json()
        raw = json.dumps({'eventId': 'e1', 'invoiceId': order['invoice']['id'], 'status': 'detected'}).encode()
        anon = APIClient()
        self.assertEqual(anon.post('/api/payments/webhook', raw, content_type='application/json', HTTP_X_SIGNATURE='00').status_code, 401)
        sig = hmac.new(b'dev-only-webhook-secret', raw, hashlib.sha256).hexdigest()
        r = anon.post('/api/payments/webhook', raw, content_type='application/json', HTTP_X_SIGNATURE=sig)
        self.assertEqual(r.json(), {'ok': True})
        r = anon.post('/api/payments/webhook', raw, content_type='application/json', HTTP_X_SIGNATURE=sig)
        self.assertEqual(r.json(), {'duplicate': True})

    def test_tickets(self):
        order = self.place([tv_item()]).json()
        r = self.c.post('/api/support/tickets', {'subject': 'سوال', 'body': 'سلام، وضعیت سفارش چیست؟', 'orderNumber': order['number']}, format='json')
        self.assertEqual(r.status_code, 201)
        t = r.json()
        r = self.c.post(f"/api/support/tickets/{t['id']}/messages", {'body': 'پیگیری'}, format='json').json()
        self.assertEqual(len(r['messages']), 2)


@override_settings(DEBUG=True, PAYMENT_PROVIDER='plisio', PLISIO_SECRET_KEY='sk_test', API_PUBLIC_URL='https://api.example.com')
class PlisioTests(Base):
    def _create(self):
        fake = mock.Mock()
        fake.json.return_value = {'status': 'success', 'data': {
            'txn_id': 'TXN1', 'wallet_hash': 'TQ1234567890abcdef', 'amount': '75.33', 'invoice_total_sum': '75.70',
            'expire_utc': 4102444800, 'expected_confirmations': 20, 'qr_code': 'data:image/png;base64,AAAA'}}
        with mock.patch('payments.gateways.plisio.requests.get', return_value=fake) as g:
            r = self.place([tv_item()])
        params = g.call_args.kwargs['params']
        self.assertEqual(params['currency'], 'USDT_TRX')
        self.assertTrue(params['callback_url'].endswith('/api/payments/plisio/callback?json=true'))
        return r.json()

    def _callback(self, inv_id, status, **extra):
        data = {'txn_id': 'TXN1', 'ipn_type': 'invoice', 'order_number': inv_id, 'order_name': 'PM', 'status': status,
                'currency': 'USDT_TRX', 'amount': '75.70', 'confirmations': '20', 'source_currency': 'USDT', **extra}
        data['verify_hash'] = hmac.new(b'sk_test', json.dumps(data, separators=(',', ':'), ensure_ascii=False).encode(), hashlib.sha1).hexdigest()
        return APIClient().post('/api/payments/plisio/callback?json=true', data, format='json')

    def test_invoice_and_callback(self):
        order = self._create()
        inv = order['invoice']
        self.assertEqual((inv['address'], inv['amountCrypto'], inv['confirmationsRequired'], inv['sandbox']), ('TQ1234567890abcdef', '75.70', 20, False))
        bad = {'order_number': inv['id'], 'status': 'completed', 'verify_hash': 'deadbeef'}
        self.assertEqual(APIClient().post('/api/payments/plisio/callback?json=true', bad, format='json').status_code, 422)
        self.assertEqual(Order.objects.get(pk=order['id']).payment_status, 'awaiting_payment')
        self.assertEqual(self._callback(inv['id'], 'completed', tx_urls=['https://tronscan.org/#/transaction/abc']).status_code, 200)
        o = self.c.get(f"/api/orders/{order['id']}").json()
        self.assertEqual((o['status'], o['paymentStatus']), ('processing', 'confirmed'))
        self.assertEqual(o['invoice']['explorerUrl'], 'https://tronscan.org/#/transaction/abc')

    def test_partial_then_expired_is_underpaid(self):
        order = self._create()
        self._callback(order['invoice']['id'], 'expired', pending_amount='30.00')
        o = Order.objects.get(pk=order['id'])
        self.assertEqual(o.payment_status, 'underpaid')
        self.assertTrue(o.needs_review)

    def test_no_wallet_hash_is_config_error(self):
        fake = mock.Mock()
        fake.json.return_value = {'status': 'success', 'data': {'txn_id': 'X', 'invoice_url': 'https://plisio.net/invoice/X'}}
        with mock.patch('payments.gateways.plisio.requests.get', return_value=fake):
            r = self.place([tv_item()])
        self.assertEqual(r.json()['code'], 'gateway_misconfigured')
        self.assertEqual(Order.objects.count(), 0)  # rolled back


@override_settings(DEBUG=True, PAYMENT_PROVIDER='sandbox')
class AdminApiTests(Base):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user('a@test.ir', 'Test1234', full_name='مدیر', is_staff=True)
        self.a = Client()
        self.a.force_login(self.admin)

    def test_requires_staff(self):
        self.assertEqual(self.c.get('/api/admin/dashboard').status_code, 403)
        self.assertEqual(Client().get('/api/admin/dashboard').status_code, 401)
        self.assertEqual(self.a.get('/api/admin/dashboard').status_code, 200)

    def test_product_crud_and_codes(self):
        cat = self.a.get('/api/admin/categories').json()['results'][0]
        prov = self.a.get('/api/admin/providers').json()['results'][0]
        body = {'slug': 'new-card', 'name': 'کارت جدید', 'brandName': 'New Card', 'categoryId': cat['id'], 'providerId': prov['id'],
                'type': 'gift_card', 'shortDescription': 'توضیح', 'maxQuantityPerItem': 3, 'isActive': True,
                'requiredFields': [{'key': 'acc', 'label': 'حساب', 'type': 'text'}], 'regions': ['جهانی']}
        r = self.a.post('/api/admin/products', body, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        pid = r.json()['id']
        self.assertEqual(self.a.post('/api/admin/products', body, format='json').json()['errors']['slug'][0], 'این نامک قبلاً استفاده شده است.')
        v = self.a.post(f'/api/admin/products/{pid}/variants', {'label': '$5', 'priceToman': 600000, 'stockMode': 'codes', 'isActive': True}, format='json').json()
        self.assertFalse(v['available'])
        r = self.a.post(f"/api/admin/variants/{v['id']}/codes", {'codes': 'AAA\nBBB\nAAA\n'}, format='json').json()
        self.assertEqual((r['added'], r['variant']['stock']), (2, 2))
        r = self.a.post(f"/api/admin/variants/{v['id']}/codes", {'codes': 'BBB\nCCC'}, format='json').json()
        self.assertEqual((r['added'], r['duplicates']), (1, 1))
        codes = self.a.get(f"/api/admin/variants/{v['id']}/codes").json()
        self.assertEqual(codes['summary']['available'], 3)
        self.a.post(f"/api/admin/codes/{codes['results'][0]['id']}/void", {}, format='json')
        self.assertEqual(self.a.delete(f'/api/admin/products/{pid}').status_code, 409)  # has codes
        r = self.a.patch(f'/api/admin/products/{pid}', {'isActive': False}, format='json').json()
        self.assertFalse(r['isActive'])
        self.assertEqual(self.c.get('/api/catalog/products/new-card').status_code, 404)

    def test_product_discount_admin(self):
        url = '/api/admin/products/p_steam_us'
        self.assertIn('discountPercent', self.a.patch(url, {'discountPercent': 95}, format='json').json()['errors'])
        r = self.a.patch(url, {'discountStartsAt': '2030-01-02T00:00:00Z', 'discountEndsAt': '2030-01-01T00:00:00Z'}, format='json')
        self.assertIn('discountEndsAt', r.json()['errors'])
        self.assertIn('discountStartsAt', self.a.patch(url, {'discountStartsAt': 'tomorrow'}, format='json').json()['errors'])
        r = self.a.patch(url, {'discountPercent': 15, 'discountStartsAt': None, 'discountEndsAt': '2099-01-01T00:00:00Z'}, format='json').json()
        self.assertEqual((r['discountPercent'], r['discountEndsAt'], r['discountActive']), (15, '2099-01-01T00:00:00Z', True))
        row = next(x for x in self.a.get('/api/admin/products').json()['results'] if x['id'] == 'p_steam_us')
        self.assertEqual(row['discountPercent'], 15)
        r = self.a.patch(url, {'discountPercent': 0}, format='json').json()
        self.assertFalse(r['discountActive'])

    def test_product_seo_content(self):
        url = '/api/admin/products/p_steam_us'
        r = self.a.patch(url, {'faqs': [{'question': 'سؤال؟', 'answer': ''}]}, format='json')
        self.assertIn('faqs', r.json()['errors'])
        self.assertIn('seoTitle', self.a.patch(url, {'seoTitle': 'x' * 71}, format='json').json()['errors'])
        body = {'article': 'پاراگراف اول\n\n## عنوان', 'seoTitle': 'عنوان سئو', 'seoDescription': 'توضیح',
                'faqs': [{'question': 'سؤال؟', 'answer': 'پاسخ.'}, {'question': '', 'answer': ''}]}
        r = self.a.patch(url, body, format='json').json()
        self.assertEqual(r['faqs'], [{'question': 'سؤال؟', 'answer': 'پاسخ.'}])  # empty editor row dropped
        p = self.c.get('/api/catalog/products/steam-wallet-usd').json()
        self.assertEqual((p['article'], p['seoTitle'], p['seoDescription'], len(p['faqs'])), (body['article'], 'عنوان سئو', 'توضیح', 1))
        # seeding fills only empty fields
        call_command('seed_seo_content', stdout=open('/dev/null', 'w'))
        self.assertEqual(self.c.get('/api/catalog/products/steam-wallet-usd').json()['seoTitle'], 'عنوان سئو')

    def test_coupon_admin(self):
        body = {'code': 'welcome-1', 'kind': 'percent', 'value': 15, 'maxDiscountToman': 200000, 'isActive': True}
        r = self.a.post('/api/admin/coupons', body, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        c = r.json()
        self.assertEqual((c['code'], c['usedCount'], c['perUserLimit']), ('WELCOME-1', 0, None))
        self.assertIn('code', self.a.post('/api/admin/coupons', body, format='json').json()['errors'])  # duplicate
        self.assertIn('value', self.a.post('/api/admin/coupons', dict(body, code='X150', value=150), format='json').json()['errors'])
        self.assertIn('code', self.a.post('/api/admin/coupons', dict(body, code='a b!'), format='json').json()['errors'])
        r = self.a.patch(f"/api/admin/coupons/{c['id']}", {'startsAt': '2030-01-02T00:00:00Z', 'endsAt': '2030-01-01T00:00:00Z'}, format='json')
        self.assertIn('endsAt', r.json()['errors'])
        self.assertEqual(self.c.get('/api/admin/coupons').status_code, 403)

        self.assertEqual(self.place_with_admin_code('WELCOME-1').status_code, 201)
        row = next(x for x in self.a.get('/api/admin/coupons').json()['results'] if x['id'] == c['id'])
        self.assertEqual(row['usedCount'], 1)
        self.assertEqual(self.a.delete(f"/api/admin/coupons/{c['id']}").status_code, 409)  # used → deactivate instead
        self.assertFalse(self.a.patch(f"/api/admin/coupons/{c['id']}", {'isActive': False}, format='json').json()['isActive'])

    def place_with_admin_code(self, code):
        items = [steam_item(1)]
        q = self.c.post('/api/cart/quote', {'items': items, 'couponCode': code}, format='json').json()
        return self.c.post('/api/orders', {'items': items, 'currency': 'USDT', 'network': 'TRC20', 'acceptedTerms': True,
                                           'couponCode': code, 'expectedTotalToman': q['totalToman']}, format='json')

    def test_image_upload_rejects_non_images(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        r = self.a.post('/api/admin/products/p_steam_us/image', {'image': SimpleUploadedFile('x.svg', b'<svg onload=alert(1)>')}, format='multipart')
        self.assertEqual(r.status_code, 400)
        png = b'\x89PNG\r\n\x1a\n' + b'\x00' * 50
        r = self.a.post('/api/admin/products/p_steam_us/image', {'image': SimpleUploadedFile('x.png', png)}, format='multipart')
        self.assertTrue(r.json()['imageUrl'].endswith('.png'))
        self.a.delete('/api/admin/products/p_steam_us/image')

    def test_manual_fulfillment_flow(self):
        order = self.place([tv_item()]).json()
        self.simulate(order['id'], 'confirmed')
        d = self.a.get(f"/api/admin/orders/{order['id']}").json()
        self.assertEqual(d['status'], 'processing')
        self.assertEqual(d['items'][0]['fields']['tv_username'], 'bob')
        r = self.a.post(f"/api/admin/orders/{order['id']}/deliveries", {'itemId': d['items'][0]['id'], 'kind': 'service_note', 'value': 'فعال شد'}, format='json').json()
        self.assertEqual(r['status'], 'completed')
        self.assertTrue(any(e['internal'] for e in r['allEvents']))
        customer = self.c.get(f"/api/orders/{order['id']}").json()
        self.assertEqual(customer['items'][0]['deliveries'][0]['value'], 'فعال شد')
        self.assertFalse(any('تحویل دستی' in e['message'] for e in customer['events']))  # internal hidden

    def test_status_transitions(self):
        order = self.place([tv_item()]).json()
        r = self.a.post(f"/api/admin/orders/{order['id']}/status", {'status': 'completed'}, format='json')
        self.assertEqual(r.json()['code'], 'invalid_transition')
        r = self.a.post(f"/api/admin/orders/{order['id']}/status", {'status': 'paid'}, format='json')
        self.assertEqual(r.json()['code'], 'payment_not_confirmed')
        r = self.a.post(f"/api/admin/orders/{order['id']}/status", {'status': 'paid', 'confirmPayment': True}, format='json').json()
        self.assertEqual((r['status'], r['paymentStatus']), ('paid', 'confirmed'))
        for s in ('refund_pending', 'refunded'):
            r = self.a.post(f"/api/admin/orders/{order['id']}/status", {'status': s}, format='json').json()
        self.assertEqual((r['status'], r['paymentStatus']), ('refunded', 'refunded'))

    def test_users_admin(self):
        r = self.a.get('/api/admin/users?q=u@test').json()
        self.assertEqual(r['count'], 1)
        r = self.a.patch(f'/api/admin/users/{self.user.pk}', {'isStaff': True}, format='json')
        self.assertIn('isStaff', r.json()['errors'])  # only superusers grant staff
        r = self.a.patch(f'/api/admin/users/{self.admin.pk}', {'isActive': False}, format='json')
        self.assertIn('isActive', r.json()['errors'])
        r = self.a.patch(f'/api/admin/users/{self.user.pk}', {'isActive': False}, format='json').json()
        self.assertFalse(r['isActive'])
        self.assertEqual(self.c.get('/api/auth/me').status_code, 401)

    def test_ticket_reply_and_settings(self):
        t = self.c.post('/api/support/tickets', {'subject': 'سوال', 'body': 'سلام، یک سوال دارم دربارهٔ خرید.'}, format='json').json()
        r = self.a.post(f"/api/admin/tickets/{t['id']}/reply", {'body': 'سلام، بفرمایید.'}, format='json').json()
        self.assertEqual(r['status'], 'answered')
        mine = self.c.get(f"/api/support/tickets/{t['id']}").json()
        self.assertEqual(mine['messages'][-1]['from'], 'support')
        self.assertIn('serviceFeeRate', self.a.patch('/api/admin/settings', {'serviceFeeRate': 2}, format='json').json()['errors'])
        self.a.patch('/api/admin/settings', {'serviceFeeRate': 0.05}, format='json')
        q = self.c.post('/api/cart/quote', {'items': [tv_item()]}, format='json').json()
        self.assertEqual(q['serviceFeeRate'], 0.05)
        cur = self.a.get('/api/admin/currencies').json()['results'][0]
        r = self.a.patch(f"/api/admin/currencies/{cur['id']}", {'rateToman': 110000}, format='json').json()
        self.assertEqual(r['results'][0]['rateToman'], 110000)
        self.assertEqual(self.c.get('/api/payments/currencies').json()['currencies'][0]['rateToman'], 110000)

    def test_dashboard(self):
        order = self.place([tv_item()]).json()
        self.simulate(order['id'], 'confirmed')
        d = self.a.get('/api/admin/dashboard').json()
        self.assertEqual(d['needsAction']['count'], 1)
        self.assertEqual(len(d['series']), 30)
        self.assertGreater(d['revenue']['today'], 0)


def fake_id_token(**claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b'=').decode()  # noqa: E731
    return f"{enc({'alg': 'RS256'})}.{enc(claims)}.sig"


@override_settings(DEBUG=True, GOOGLE_CLIENT_ID='cid.apps.googleusercontent.com', GOOGLE_CLIENT_SECRET='secret',
                   FRONTEND_URL='http://localhost:3000', API_PUBLIC_URL='http://localhost:8000')
class GoogleSignInTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.c = Client()

    def start(self, next_path='/checkout?step=4'):
        r = self.c.get('/api/auth/google/start', {'next': next_path})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].startswith('https://accounts.google.com/o/oauth2/v2/auth?'))
        return self.c.session['google_oauth']

    def callback(self, flow, token_status=200, **claims):
        base = {'iss': 'https://accounts.google.com', 'aud': 'cid.apps.googleusercontent.com', 'sub': 'g-123',
                'email': 'Ali@Example.com', 'email_verified': True, 'name': 'علی', 'exp': int(time.time()) + 300,
                'nonce': flow['nonce']}
        resp = mock.Mock(status_code=token_status, text='')
        resp.json.return_value = {'id_token': fake_id_token(**{**base, **claims})}
        with mock.patch('accounts.google.requests.post', return_value=resp) as post:
            r = self.c.get('/api/auth/google/callback', {'state': flow['state'], 'code': 'abc'})
        return r, post

    def test_disabled_without_credentials(self):
        with override_settings(GOOGLE_CLIENT_ID='', GOOGLE_CLIENT_SECRET=''):
            self.assertEqual(self.c.get('/api/auth/providers').json(), {'google': False})
            r = self.c.get('/api/auth/google/start')
            self.assertIn('/auth/login?error=google_unavailable', r['Location'])
        self.assertEqual(self.c.get('/api/auth/providers').json(), {'google': True})

    def test_new_user_signs_up_and_returns_to_page(self):
        flow = self.start()
        r, post = self.callback(flow)
        self.assertEqual(r['Location'], 'http://localhost:3000/checkout?step=4')
        self.assertEqual(post.call_args.kwargs['data']['code_verifier'], flow['verifier'])  # PKCE
        user = User.objects.get(email='ali@example.com')
        self.assertTrue(user.email_verified)
        self.assertFalse(user.has_usable_password())
        self.assertEqual((user.google_sub, user.full_name), ('g-123', 'علی'))
        self.assertEqual(self.c.get('/api/auth/me').json()['user']['email'], 'ali@example.com')

    def test_existing_account_is_linked(self):
        user = User.objects.create_user('ali@example.com', 'Test1234', full_name='علی')
        r, _ = self.callback(self.start())
        self.assertEqual(r['Location'], 'http://localhost:3000/checkout?step=4')
        user.refresh_from_db()
        self.assertEqual((user.google_sub, user.email_verified, user.check_password('Test1234')), ('g-123', True, True))
        self.assertEqual(User.objects.count(), 1)

    def test_rejections(self):
        cases = [
            ({'aud': 'someone-else'}, 'google_failed'),
            ({'nonce': 'replayed'}, 'google_failed'),
            ({'iss': 'https://evil.example'}, 'google_failed'),
            ({'exp': int(time.time()) - 10}, 'google_failed'),
            ({'email_verified': False}, 'google_email_unverified'),
        ]
        for claims, error in cases:
            r, _ = self.callback(self.start(), **claims)
            self.assertIn(f'error={error}', r['Location'], claims)
        r, _ = self.callback(self.start(), token_status=400)
        self.assertIn('error=google_failed', r['Location'])
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(self.c.get('/api/auth/me').status_code, 401)

    def test_state_must_match_and_is_single_use(self):
        flow = self.start()
        r = self.c.get('/api/auth/google/callback', {'state': 'forged', 'code': 'abc'})
        self.assertIn('error=google_expired', r['Location'])
        r, _ = self.callback(flow)  # the flow was consumed by the forged attempt
        self.assertIn('error=google_expired', r['Location'])
        r = self.c.get('/api/auth/google/callback', {'error': 'access_denied', 'state': 'x'})
        self.assertIn('error=google_cancelled', r['Location'])

    def test_disabled_account_and_conflicting_link(self):
        User.objects.create_user('ali@example.com', 'Test1234', full_name='علی', is_active=False)
        r, _ = self.callback(self.start())
        self.assertIn('error=google_disabled', r['Location'])
        User.objects.filter(email='ali@example.com').update(is_active=True, google_sub='g-other')
        r, _ = self.callback(self.start())
        self.assertIn('error=google_conflict', r['Location'])

    def test_next_must_stay_on_site(self):
        for bad in ('//evil.example/x', 'https://evil.example', '/\\evil.example', 'javascript:alert(1)'):
            self.assertEqual(self.start(bad)['next'], '/account', bad)
