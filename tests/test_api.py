import hashlib
import hmac
import json
from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User
from catalog.models import GiftCode, Variant
from orders.models import Order
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
