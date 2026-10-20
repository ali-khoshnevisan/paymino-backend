"""
Load SAMPLE catalog + payment currencies (same data as the frontend mock API).
Every price and rate is a placeholder — edit them in the admin panel before going live.
Usage: python manage.py seed_demo [--codes]
"""
from decimal import ROUND_HALF_UP, Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Category, GiftCode, Product, Provider, Variant
from catalog.seo_content import fill_seo_content
from core.models import SiteSettings
from payments.models import PaymentCurrency, PaymentNetwork

FX = {'USD': 105_000, 'EUR': 114_000, 'GBP': 133_000}
MARGIN = Decimal('1.06')
SYM = {'USD': '$', 'EUR': '€', 'GBP': '£'}


def r1000(n):
    return int((Decimal(n) / 1000).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * 1000)


def gift(prefix, cur, values, region, unavailable=()):
    return [dict(id=f'{prefix}-{v}', label=f'{SYM[cur]}{v}', face_value=v, face_currency=cur, region=region,
                 price_toman=r1000(v * FX[cur] * MARGIN), is_active=v not in unavailable, stock_mode='codes', sort_order=i)
            for i, v in enumerate(values)]


def plan(id, label, months, usd, region='جهانی'):
    return dict(id=id, label=label, duration_months=months, region=region, price_toman=r1000(usd * FX['USD'] * MARGIN), stock_mode='manual')


ACCOUNT_EMAIL = {'key': 'account_email', 'label': 'ایمیل حساب کاربری سرویس', 'type': 'email', 'placeholder': 'name@example.com',
                 'help': 'ایمیلی که با آن در این سرویس ثبت‌نام کرده‌اید. رمز عبور حساب هرگز از شما خواسته نمی‌شود.', 'required': True}
GIFT_REFUND = 'به دلیل ماهیت دیجیتال، کد گیفت کارت پس از ارسال قابل بازگشت نیست. اگر پیش از ارسال کد امکان تأمین سفارش وجود نداشته باشد، طبق قوانین بازپرداخت پی‌مینو اقدام می‌شود.'
SERVICE_REFUND = 'اگر پیش از شروع انجام سفارش درخواست لغو بدهید یا انجام سفارش ممکن نباشد، طبق قوانین بازپرداخت پی‌مینو اقدام می‌شود. پس از فعال‌سازی اشتراک، امکان لغو وجود ندارد.'
GIFT_NOTES = ['کد پس از تأیید پرداخت در بخش «سفارش‌های من» نمایش داده می‌شود.', 'پیش از خرید، کشور یا منطقه حساب خود را بررسی کنید.']
SERVICE_NOTES = ['پس از فعال‌سازی، وضعیت سفارش به «تکمیل‌شده» تغییر می‌کند.']
AI_RESTRICT = ['ارائه این سرویس منوط به قوانین و مناطق پشتیبانی‌شده ارائه‌دهنده است.']
AI_REGION = 'طبق مناطق پشتیبانی‌شده'

CATEGORIES = [
    ('steam', 'گیفت کارت استیم', 'شارژ کیف پول استیم برای خرید بازی و آیتم', 'steam'),
    ('apple', 'گیفت کارت اپل', 'اعتبار اپ استور، اپل موزیک و iCloud', 'apple'),
    ('playstation', 'گیفت کارت پلی‌استیشن', 'اعتبار PlayStation Store برای بازی و اشتراک', 'playstation'),
    ('tradingview', 'اشتراک تریدینگ‌ویو', 'فعال‌سازی پلن‌های حرفه‌ای تحلیل بازار', 'tradingview'),
    ('ai', 'سرویس‌های هوش مصنوعی', 'اشتراک دستیارها و ابزارهای هوش مصنوعی', 'ai'),
]
PROVIDERS = [('steam', 'Steam', 'steam'), ('apple', 'Apple', 'apple'), ('playstation', 'PlayStation', 'playstation'),
             ('tradingview', 'TradingView', 'tradingview'), ('openai', 'OpenAI', 'ai'), ('perplexity', 'Perplexity', 'ai'),
             ('midjourney', 'Midjourney', 'ai')]

GIFT = dict(type='gift_card', delivery_method='ارسال کد دیجیتال در پنل کاربری', refund_policy=GIFT_REFUND, max_quantity_per_item=5)
SUB = dict(type='subscription', delivery_method='فعال‌سازی روی حساب شما', refund_policy=SERVICE_REFUND, max_quantity_per_item=1, redemption_notes=SERVICE_NOTES)

PRODUCTS = [
    dict(GIFT, id='p_steam_us', slug='steam-wallet-usd', name='گیفت کارت استیم آمریکا', brand_name='Steam Wallet Gift Card (USD)', cat='steam', prov='steam',
         short_description='شارژ کیف پول استیم با واحد دلار آمریکا', description='با این گیفت کارت می‌توانید کیف پول حساب استیم خود را شارژ کنید و از آن برای خرید بازی، DLC و آیتم‌های بازار استیم استفاده کنید.',
         regions=['ایالات متحده'], restrictions=['فقط برای حساب‌هایی که واحد پول کیف پولشان دلار آمریکا (USD) است قابل استفاده است.', 'پس از ثبت کد، اعتبار قابل انتقال به حساب دیگر نیست.'],
         redemption_notes=GIFT_NOTES + ['برای ثبت کد: Steam ← Games ← Redeem a Steam Wallet Code'], popularity=98, variants=gift('steam-us', 'USD', [5, 10, 20, 50, 100], 'ایالات متحده')),
    dict(GIFT, id='p_steam_eu', slug='steam-wallet-eur', name='گیفت کارت استیم اروپا', brand_name='Steam Wallet Gift Card (EUR)', cat='steam', prov='steam',
         short_description='شارژ کیف پول استیم با واحد یورو', description='مناسب حساب‌های استیم با واحد پول یورو. برای خرید بازی و آیتم در فروشگاه استیم.',
         regions=['اتحادیه اروپا'], restrictions=['فقط برای حساب‌هایی که واحد پول کیف پولشان یورو (EUR) است قابل استفاده است.'],
         redemption_notes=GIFT_NOTES, popularity=70, variants=gift('steam-eu', 'EUR', [5, 10, 20, 50, 100], 'اتحادیه اروپا', [100])),
    dict(GIFT, id='p_apple_us', slug='apple-gift-card-usd', name='گیفت کارت اپل آمریکا', brand_name='Apple Gift Card (US)', cat='apple', prov='apple',
         short_description='اعتبار اپل آیدی آمریکا برای اپ استور و سرویس‌های اپل', description='اعتبار این کارت به Apple ID اضافه می‌شود و برای خرید از App Store، اشتراک iCloud+، Apple Music و سایر سرویس‌های اپل قابل استفاده است.',
         regions=['ایالات متحده'], restrictions=['کشور یا منطقه Apple ID شما باید ایالات متحده باشد؛ در غیر این صورت کد ثبت نمی‌شود.', 'اعتبار ثبت‌شده قابل انتقال یا تبدیل به وجه نقد نیست.'],
         redemption_notes=GIFT_NOTES + ['برای ثبت کد: App Store ← حساب کاربری ← Redeem Gift Card or Code'], popularity=95, variants=gift('apple-us', 'USD', [10, 25, 50, 100], 'ایالات متحده')),
    dict(GIFT, id='p_apple_uk', slug='apple-gift-card-gbp', name='گیفت کارت اپل انگلستان', brand_name='Apple Gift Card (UK)', cat='apple', prov='apple',
         short_description='اعتبار اپل آیدی انگلستان با واحد پوند', description='برای Apple IDهایی با منطقه بریتانیا. قابل استفاده در App Store و سرویس‌های اپل.',
         regions=['بریتانیا'], restrictions=['کشور یا منطقه Apple ID شما باید بریتانیا باشد.'], redemption_notes=GIFT_NOTES, popularity=52,
         variants=gift('apple-uk', 'GBP', [10, 25, 50], 'بریتانیا')),
    dict(GIFT, id='p_psn_us', slug='playstation-gift-card-usd', name='گیفت کارت پلی‌استیشن آمریکا', brand_name='PlayStation Store Gift Card (US)', cat='playstation', prov='playstation',
         short_description='اعتبار PlayStation Store برای حساب‌های آمریکا', description='اعتبار کیف پول حساب PlayStation Network برای خرید بازی، افزودنی‌ها و اشتراک PlayStation Plus.',
         regions=['ایالات متحده'], restrictions=['منطقه حساب PSN شما باید ایالات متحده باشد.', 'محدودیت سقف کیف پول PSN برای هر حساب اعمال می‌شود.'],
         redemption_notes=GIFT_NOTES, popularity=90, variants=gift('psn-us', 'USD', [10, 25, 50, 100], 'ایالات متحده')),
    dict(GIFT, id='p_psn_uk', slug='playstation-gift-card-gbp', name='گیفت کارت پلی‌استیشن انگلستان', brand_name='PlayStation Store Gift Card (UK)', cat='playstation', prov='playstation',
         short_description='اعتبار PlayStation Store برای حساب‌های بریتانیا', description='برای حساب‌های PSN با منطقه بریتانیا.',
         regions=['بریتانیا'], restrictions=['منطقه حساب PSN شما باید بریتانیا باشد.'], redemption_notes=GIFT_NOTES, popularity=40,
         variants=gift('psn-uk', 'GBP', [10, 20, 50], 'بریتانیا')),
    dict(SUB, id='p_tradingview', slug='tradingview-subscription', name='اشتراک تریدینگ‌ویو', brand_name='TradingView', cat='tradingview', prov='tradingview',
         short_description='فعال‌سازی پلن‌های Essential، Plus و Premium روی حساب شما', description='پلن انتخابی روی حساب تریدینگ‌ویوی خودتان فعال می‌شود. فقط نام کاربری و ایمیل حساب لازم است و رمز عبور شما هرگز درخواست نمی‌شود.',
         regions=['جهانی'], restrictions=['اگر حساب شما اشتراک فعال دیگری دارد، پیش از ثبت سفارش با پشتیبانی هماهنگ کنید.', 'شرایط استفاده از سرویس طبق قوانین تریدینگ‌ویو است.'],
         required_fields=[{'key': 'tv_username', 'label': 'نام کاربری تریدینگ‌ویو', 'type': 'text', 'placeholder': 'username', 'help': 'نام کاربری نمایش‌داده‌شده در پروفایل تریدینگ‌ویو.', 'required': True},
                          dict(ACCOUNT_EMAIL, label='ایمیل حساب تریدینگ‌ویو')],
         popularity=80, variants=[plan('tv-essential-1', 'Essential — ماهانه', 1, 15), plan('tv-essential-12', 'Essential — سالانه', 12, 155),
                                  plan('tv-plus-1', 'Plus — ماهانه', 1, 30), plan('tv-plus-12', 'Plus — سالانه', 12, 300),
                                  plan('tv-premium-1', 'Premium — ماهانه', 1, 60), plan('tv-premium-12', 'Premium — سالانه', 12, 600)]),
    dict(SUB, id='p_chatgpt_plus', slug='chatgpt-plus', name='اشتراک ChatGPT Plus', brand_name='ChatGPT Plus', cat='ai', prov='openai',
         short_description='فعال‌سازی اشتراک پلاس روی حساب ChatGPT شما', description='اشتراک ماهانه ChatGPT Plus روی حساب خودتان فعال می‌شود. فقط ایمیل حساب لازم است.',
         regions=['طبق مناطق پشتیبانی‌شده سرویس'], restrictions=AI_RESTRICT, required_fields=[ACCOUNT_EMAIL], popularity=99,
         variants=[plan('gpt-plus-1', 'Plus — ماهانه', 1, 20, AI_REGION)]),
    dict(SUB, id='p_perplexity_pro', slug='perplexity-pro', name='اشتراک Perplexity Pro', brand_name='Perplexity Pro', cat='ai', prov='perplexity',
         short_description='جست‌وجوی هوشمند با اشتراک ماهانه یا سالانه', description='پلن Pro روی حساب Perplexity شما فعال می‌شود.',
         regions=['طبق مناطق پشتیبانی‌شده سرویس'], restrictions=AI_RESTRICT, required_fields=[ACCOUNT_EMAIL], popularity=60,
         variants=[plan('pplx-pro-1', 'Pro — ماهانه', 1, 20, AI_REGION), plan('pplx-pro-12', 'Pro — سالانه', 12, 200, AI_REGION)]),
    dict(SUB, id='p_midjourney', slug='midjourney-subscription', name='اشتراک Midjourney', brand_name='Midjourney', cat='ai', prov='midjourney',
         short_description='ساخت تصویر با هوش مصنوعی؛ پلن‌های Basic و Standard', description='پلن انتخابی روی حساب Midjourney شما فعال می‌شود.',
         regions=['طبق مناطق پشتیبانی‌شده سرویس'], restrictions=AI_RESTRICT, required_fields=[ACCOUNT_EMAIL], popularity=55,
         variants=[plan('mj-basic-1', 'Basic — ماهانه', 1, 10, AI_REGION), plan('mj-standard-1', 'Standard — ماهانه', 1, 30, AI_REGION)]),
]

CURRENCIES = [
    ('USDT', 'Tether', 2, 105_500, [('TRC20', 'Tron (TRC20)', '1', 19, 'کارمزد شبکه ترون را کیف پول شما دریافت می‌کند.', 'USDT_TRX', 'https://tronscan.org/#/transaction/{tx}'),
                                    ('BEP20', 'BNB Smart Chain (BEP20)', '1', 15, 'کارمزد شبکه BSC را کیف پول شما دریافت می‌کند.', 'USDT_BSC', 'https://bscscan.com/tx/{tx}')]),
    ('TRX', 'Tron', 2, 31_800, [('TRC20', 'Tron', '10', 19, 'کارمزد شبکه ترون را کیف پول شما دریافت می‌کند.', 'TRX', 'https://tronscan.org/#/transaction/{tx}')]),
    ('BTC', 'Bitcoin', 8, 6_850_000_000, [('BTC', 'Bitcoin', '0.0001', 2, 'کارمزد شبکه بیت‌کوین ممکن است قابل توجه باشد و به عهده پرداخت‌کننده است.', 'BTC', 'https://mempool.space/tx/{tx}')]),
    ('TON', 'Toncoin', 4, 330_000, [('TON', 'The Open Network', '1', 1, 'کارمزد شبکه TON را کیف پول شما دریافت می‌کند.', 'TON', 'https://tonviewer.com/transaction/{tx}')]),
]


class Command(BaseCommand):
    help = 'Load sample catalog and payment currencies (placeholders).'

    def add_arguments(self, parser):
        parser.add_argument('--codes', action='store_true', help='Also add 3 FAKE gift codes per gift-card variant (dev only).')

    @transaction.atomic
    def handle(self, *args, codes=False, **opts):
        SiteSettings.get()
        cats = {}
        for i, (slug, name, desc, icon) in enumerate(CATEGORIES):
            cats[slug], _ = Category.objects.update_or_create(slug=slug, defaults=dict(name=name, description=desc, icon=icon, sort_order=i))
        provs = {}
        for slug, name, cat in PROVIDERS:
            provs[slug], _ = Provider.objects.update_or_create(slug=slug, defaults=dict(name=name, category=cats[cat]))
        for data in PRODUCTS:
            data = dict(data)
            variants = data.pop('variants')
            cat, prov, pid = data.pop('cat'), data.pop('prov'), data.pop('id')
            p, _ = Product.objects.update_or_create(id=pid, defaults=dict(data, category=cats[cat], provider=provs[prov]))
            fill_seo_content(p)
            for v in variants:
                v = dict(v)
                vid = v.pop('id')
                var, _ = Variant.objects.update_or_create(id=vid, defaults=dict(v, product=p))
                if codes and var.stock_mode == 'codes' and not var.codes.exists():
                    for n in range(3):
                        GiftCode.objects.create(variant=var, code=f'FAKE-{vid.upper()}-{n + 1:04d}', note='sample')
        for i, (code, name, dec, rate, nets) in enumerate(CURRENCIES):
            c, _ = PaymentCurrency.objects.update_or_create(code=code, defaults=dict(name=name, decimals=dec, rate_toman=rate, sort_order=i))
            for ncode, nname, nmin, conf, note, gw, explorer in nets:
                PaymentNetwork.objects.update_or_create(currency=c, code=ncode, defaults=dict(
                    name=nname, min_amount=Decimal(nmin), confirmations_required=conf, network_fee_note=note, gateway_code=gw, explorer_tx_url=explorer))
        self.stdout.write(self.style.SUCCESS(f'Seeded {len(PRODUCTS)} products and {len(CURRENCIES)} currencies (sample data).'))
