from django.conf import settings as django_settings
from decimal import Decimal, InvalidOperation

from django.db.models import ProtectedError
from rest_framework.response import Response

from core.errors import ApiError, field_errors
from core.models import SiteSettings
from core.utils import iso, now
from payments.models import PaymentCurrency, PaymentNetwork

from .common import Form, staff_view


def settings_dto(s):
    return {
        'serviceFeeRate': float(s.service_fee_rate), 'invoiceTtlMinutes': s.invoice_ttl_minutes,
        'ordersEnabled': s.orders_enabled, 'lowStockThreshold': s.low_stock_threshold, 'supportEmail': s.support_email,
        'paymentProvider': django_settings.PAYMENT_PROVIDER,
    }


@staff_view(['GET', 'PATCH'])
def site_settings(request):
    s = SiteSettings.get()
    if request.method == 'PATCH':
        d = request.data
        errors = {}
        if 'serviceFeeRate' in d:
            try:
                rate = Decimal(str(d['serviceFeeRate']))
                if not (Decimal('0') <= rate <= Decimal('0.5')):
                    raise InvalidOperation
                s.service_fee_rate = rate.quantize(Decimal('0.0001'))
            except (InvalidOperation, ValueError):
                errors['serviceFeeRate'] = ['نرخ باید عددی بین ۰ و ۰٫۵ باشد (مثلاً ۰٫۰۲ برای ۲٪).']
        f = Form(d, partial=True)
        f.integer('invoiceTtlMinutes', 'invoice_ttl_minutes', min_value=10, max_value=1440)
        f.integer('lowStockThreshold', 'low_stock_threshold', min_value=0, max_value=10000)
        f.boolean('ordersEnabled', 'orders_enabled')
        f.text('supportEmail', 'support_email', required=False, max_len=254)
        errors.update(f.errors)
        if errors:
            field_errors(errors)
        for k, v in f.clean.items():
            setattr(s, k, v)
        s.save()
    return Response(settings_dto(s))


def network_dto(n):
    return {
        'id': n.id, 'code': n.code, 'name': n.name, 'minAmount': f'{n.min_amount.normalize():f}',
        'confirmationsRequired': n.confirmations_required, 'networkFeeNote': n.network_fee_note,
        'gatewayCode': n.gateway_code, 'explorerTxUrl': n.explorer_tx_url, 'isActive': n.is_active,
    }


def currency_dto(c):
    return {
        'id': c.id, 'code': c.code, 'name': c.name, 'decimals': c.decimals, 'rateToman': int(c.rate_toman),
        'rateUpdatedAt': iso(c.rate_updated_at), 'isActive': c.is_active, 'sortOrder': c.sort_order,
        'networks': [network_dto(n) for n in c.networks.all()],
    }


def _currency_form(d, partial):
    f = Form(d, partial)
    if not f.skip('code'):
        code = str(d.get('code') or '').strip().upper()
        if not code.isalnum() or not code.isascii() or len(code) > 12:
            f.err('code', 'کد ارز نامعتبر است.')
        else:
            f.clean['code'] = code
    f.text('name', 'name', max_len=60)
    f.integer('decimals', 'decimals', min_value=0, max_value=18)
    f.integer('rateToman', 'rate_toman', min_value=1, max_value=10**15)
    f.boolean('isActive', 'is_active')
    f.integer('sortOrder', 'sort_order', required=False)
    return f.raise_if_errors()


def _network_form(d, partial):
    f = Form(d, partial)
    f.text('code', 'code', max_len=20)
    f.text('name', 'name', max_len=60)
    f.integer('confirmationsRequired', 'confirmations_required', min_value=0, max_value=1000)
    f.text('networkFeeNote', 'network_fee_note', required=False)
    f.text('gatewayCode', 'gateway_code', required=False, max_len=30)
    f.text('explorerTxUrl', 'explorer_tx_url', required=False)
    f.boolean('isActive', 'is_active')
    if not f.skip('minAmount'):
        try:
            v = Decimal(str(d.get('minAmount')))
            if v < 0:
                raise InvalidOperation
            f.clean['min_amount'] = v
        except (InvalidOperation, ValueError):
            f.err('minAmount', 'عدد معتبر وارد کنید.')
    return f.raise_if_errors()


def _currencies():
    return PaymentCurrency.objects.prefetch_related('networks').order_by('sort_order', 'id')


@staff_view(['GET', 'POST'])
def currencies(request):
    if request.method == 'POST':
        clean = _currency_form(request.data, False)
        if PaymentCurrency.objects.filter(code=clean['code']).exists():
            field_errors({'code': ['این ارز قبلاً ثبت شده است.']})
        PaymentCurrency.objects.create(**clean)
    return Response({'results': [currency_dto(c) for c in _currencies()]}, status=201 if request.method == 'POST' else 200)


@staff_view(['PATCH', 'DELETE'])
def currency_detail(request, pk):
    c = PaymentCurrency.objects.filter(pk=pk).first()
    if not c:
        raise ApiError(404, 'ارز یافت نشد.')
    if request.method == 'DELETE':
        c.delete()
        return Response({'results': [currency_dto(x) for x in _currencies()]})
    clean = _currency_form(request.data, True)
    if 'code' in clean and PaymentCurrency.objects.filter(code=clean['code']).exclude(pk=c.pk).exists():
        field_errors({'code': ['این ارز قبلاً ثبت شده است.']})
    if 'rate_toman' in clean and clean['rate_toman'] != c.rate_toman:
        c.rate_updated_at = now()
    for k, v in clean.items():
        setattr(c, k, v)
    c.save()
    return Response({'results': [currency_dto(x) for x in _currencies()]})


@staff_view(['POST'])
def currency_networks(request, pk):
    c = PaymentCurrency.objects.filter(pk=pk).first()
    if not c:
        raise ApiError(404, 'ارز یافت نشد.')
    clean = _network_form(request.data, False)
    if c.networks.filter(code=clean['code']).exists():
        field_errors({'code': ['این شبکه برای این ارز ثبت شده است.']})
    PaymentNetwork.objects.create(currency=c, **clean)
    return Response({'results': [currency_dto(x) for x in _currencies()]}, status=201)


@staff_view(['PATCH', 'DELETE'])
def network_detail(request, pk):
    n = PaymentNetwork.objects.filter(pk=pk).first()
    if not n:
        raise ApiError(404, 'شبکه یافت نشد.')
    if request.method == 'DELETE':
        n.delete()
    else:
        clean = _network_form(request.data, True)
        if 'code' in clean and n.currency.networks.filter(code=clean['code']).exclude(pk=n.pk).exists():
            field_errors({'code': ['این شبکه برای این ارز ثبت شده است.']})
        for k, v in clean.items():
            setattr(n, k, v)
        n.save()
    return Response({'results': [currency_dto(x) for x in _currencies()]})
