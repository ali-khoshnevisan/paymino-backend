from django.db import transaction
from django.db.models import Count, ProtectedError, Q
from rest_framework.response import Response

from catalog.models import CATEGORY_ICONS, PRODUCT_TYPES, STOCK_MODES, Category, GiftCode, Product, Provider, Variant, products_with_variants, variants_with_stock
from core.errors import ApiError, field_errors
from core.pagination import paginate
from core.utils import normalize_search

from .common import Form, staff_view
from .dto import category_dto, code_dto, product_dto, product_row, provider_dto, variant_dto

ICONS = [c for c, _ in CATEGORY_ICONS]
TYPES = [c for c, _ in PRODUCT_TYPES]
MODES = [c for c, _ in STOCK_MODES]
FIELD_TYPES = ('text', 'email', 'url')
ALLOWED_IMAGE = {b'\x89PNG': 'png', b'\xff\xd8\xff': 'jpg', b'RIFF': 'webp'}


def _protected(fn):
    try:
        fn()
    except ProtectedError:
        raise ApiError(409, 'این مورد به داده‌های دیگری وابسته است و حذف نمی‌شود. به‌جای حذف، آن را غیرفعال کنید.', code='protected')


# ------------------------------------------------------------------ categories

def _category_form(data, partial, instance=None):
    f = Form(data, partial)
    f.slug('slug', 'slug')
    f.text('name', 'name', max_len=120)
    f.text('description', 'description', required=False)
    f.choice('icon', 'icon', ICONS)
    f.integer('sortOrder', 'sort_order', required=False)
    f.boolean('isActive', 'is_active')
    clean = f.raise_if_errors()
    if 'slug' in clean and Category.objects.filter(slug=clean['slug']).exclude(pk=getattr(instance, 'pk', None)).exists():
        field_errors({'slug': ['این نامک قبلاً استفاده شده است.']})
    return clean


@staff_view(['GET', 'POST'])
def categories(request):
    if request.method == 'GET':
        qs = Category.objects.annotate(product_count=Count('products')).order_by('sort_order', 'id')
        return Response({'count': qs.count(), 'results': [category_dto(c) for c in qs]})
    c = Category.objects.create(**_category_form(request.data, False))
    return Response(category_dto(c), status=201)


@staff_view(['PATCH', 'DELETE'])
def category_detail(request, pk):
    c = Category.objects.filter(pk=pk).first()
    if not c:
        raise ApiError(404, 'دسته‌بندی یافت نشد.')
    if request.method == 'DELETE':
        _protected(c.delete)
        return Response(status=204)
    for k, v in _category_form(request.data, True, c).items():
        setattr(c, k, v)
    c.save()
    return Response(category_dto(c))


# ------------------------------------------------------------------ providers

def _provider_form(data, partial, instance=None):
    f = Form(data, partial)
    f.slug('slug', 'slug')
    f.text('name', 'name', max_len=120)
    f.integer('categoryId', 'category_id')
    clean = f.raise_if_errors()
    if 'category_id' in clean and not Category.objects.filter(pk=clean['category_id']).exists():
        field_errors({'categoryId': ['دسته‌بندی نامعتبر است.']})
    if 'slug' in clean and Provider.objects.filter(slug=clean['slug']).exclude(pk=getattr(instance, 'pk', None)).exists():
        field_errors({'slug': ['این نامک قبلاً استفاده شده است.']})
    return clean


@staff_view(['GET', 'POST'])
def providers(request):
    if request.method == 'GET':
        qs = Provider.objects.annotate(product_count=Count('products')).order_by('name')
        return Response({'count': qs.count(), 'results': [provider_dto(p) for p in qs]})
    p = Provider.objects.create(**_provider_form(request.data, False))
    return Response(provider_dto(p), status=201)


@staff_view(['PATCH', 'DELETE'])
def provider_detail(request, pk):
    p = Provider.objects.filter(pk=pk).first()
    if not p:
        raise ApiError(404, 'برند یافت نشد.')
    if request.method == 'DELETE':
        _protected(p.delete)
        return Response(status=204)
    for k, v in _provider_form(request.data, True, p).items():
        setattr(p, k, v)
    p.save()
    return Response(provider_dto(p))


# ------------------------------------------------------------------ products

def _required_fields(value, f: Form):
    if not isinstance(value, list) or len(value) > 10:
        f.err('requiredFields', 'فهرست فیلدها نامعتبر است.')
        return None
    out, keys = [], set()
    for i, rf in enumerate(value):
        if not isinstance(rf, dict):
            f.err('requiredFields', f'فیلد {i + 1} نامعتبر است.')
            return None
        key = str(rf.get('key') or '').strip()
        label = str(rf.get('label') or '').strip()
        typ = rf.get('type') or 'text'
        if not key or not key.replace('_', '').isalnum() or not key.isascii() or key in keys:
            f.err('requiredFields', f'کلید فیلد {i + 1} باید یکتا و فقط شامل حروف انگلیسی، عدد و _ باشد.')
            return None
        if not label or typ not in FIELD_TYPES:
            f.err('requiredFields', f'عنوان یا نوع فیلد {i + 1} نامعتبر است.')
            return None
        keys.add(key)
        item = {'key': key, 'label': label[:120], 'type': typ, 'required': rf.get('required') is not False}
        for opt in ('placeholder', 'help'):
            if str(rf.get(opt) or '').strip():
                item[opt] = str(rf[opt]).strip()[:300]
        out.append(item)
    return out


def _product_form(data, partial, instance=None):
    f = Form(data, partial)
    f.slug('slug', 'slug')
    f.text('name', 'name', max_len=200)
    f.text('brandName', 'brand_name', max_len=200)
    f.integer('categoryId', 'category_id')
    f.integer('providerId', 'provider_id')
    f.choice('type', 'type', TYPES)
    f.text('shortDescription', 'short_description', max_len=255)
    f.text('description', 'description', required=False, max_len=10000)
    f.str_list('regions', 'regions', max_len=120)
    f.str_list('restrictions', 'restrictions')
    f.str_list('redemptionNotes', 'redemption_notes')
    f.text('deliveryMethod', 'delivery_method', required=False, max_len=200)
    f.text('fulfillmentEstimate', 'fulfillment_estimate', required=False, max_len=120)
    f.text('refundPolicy', 'refund_policy', required=False, max_len=5000)
    f.integer('maxQuantityPerItem', 'max_quantity_per_item', min_value=1, max_value=100)
    f.integer('popularity', 'popularity', required=False)
    f.boolean('isActive', 'is_active')
    if not f.skip('requiredFields'):
        rf = _required_fields(data.get('requiredFields', []), f)
        if rf is not None:
            f.clean['required_fields'] = rf
    clean = f.raise_if_errors()
    errors = {}
    if 'category_id' in clean and not Category.objects.filter(pk=clean['category_id']).exists():
        errors['categoryId'] = ['دسته‌بندی نامعتبر است.']
    if 'provider_id' in clean and not Provider.objects.filter(pk=clean['provider_id']).exists():
        errors['providerId'] = ['برند نامعتبر است.']
    if 'slug' in clean and Product.objects.filter(slug=clean['slug']).exclude(pk=getattr(instance, 'pk', None)).exists():
        errors['slug'] = ['این نامک قبلاً استفاده شده است.']
    if errors:
        field_errors(errors)
    return clean


def _load_product(pk):
    p = products_with_variants(Product.objects.filter(pk=pk)).first()
    if not p:
        raise ApiError(404, 'محصول یافت نشد.')
    return p


@staff_view(['GET', 'POST'])
def products(request):
    if request.method == 'POST':
        p = Product.objects.create(**_product_form(request.data, False))
        return Response(product_dto(_load_product(p.pk)), status=201)

    q = request.query_params
    qs = Product.objects.order_by('-popularity', '-created_at')
    if q.get('category'):
        qs = qs.filter(category_id=q.get('category'))
    if q.get('type') in TYPES:
        qs = qs.filter(type=q.get('type'))
    if q.get('active') in ('1', '0'):
        qs = qs.filter(is_active=q.get('active') == '1')
    rows = [product_row(p) for p in products_with_variants(qs)]
    if q.get('q'):
        needle = normalize_search(q['q'])
        rows = [r for r in rows if any(needle in normalize_search(r[k] or '') for k in ('name', 'brandName', 'slug'))]
    if q.get('lowStock') == '1':
        rows = [r for r in rows if r['lowStock']]
    return Response({'count': len(rows), 'results': rows})


@staff_view(['GET', 'PATCH', 'DELETE'])
def product_detail(request, pk):
    p = _load_product(pk)
    if request.method == 'GET':
        return Response(product_dto(p))
    if request.method == 'DELETE':
        if GiftCode.objects.filter(variant__product=p).exists():
            raise ApiError(409, 'این محصول کد ثبت‌شده دارد و حذف نمی‌شود. آن را غیرفعال کنید.', code='protected')
        _protected(p.delete)
        return Response(status=204)
    for k, v in _product_form(request.data, True, p).items():
        setattr(p, k, v)
    p.save()
    return Response(product_dto(_load_product(pk)))


@staff_view(['POST', 'DELETE'])
def product_image(request, pk):
    p = _load_product(pk)
    if request.method == 'DELETE':
        if p.image:
            p.image.delete(save=False)
        p.image = ''
        p.save(update_fields=['image', 'updated_at'])
        return Response(product_dto(_load_product(pk)))
    file = request.FILES.get('image')
    if not file:
        field_errors({'image': ['فایل تصویر را انتخاب کنید.']})
    if file.size > 2 * 1024 * 1024:
        field_errors({'image': ['حجم تصویر باید کمتر از ۲ مگابایت باشد.']})
    head = file.read(12)
    file.seek(0)
    ext = next((e for magic, e in ALLOWED_IMAGE.items() if head.startswith(magic)), None)
    if not ext or (ext == 'webp' and head[8:12] != b'WEBP'):
        field_errors({'image': ['فقط تصاویر PNG، JPG یا WEBP مجاز است.']})
    if p.image:
        p.image.delete(save=False)
    p.image.save(f'{p.slug}.{ext}', file, save=False)
    p.save(update_fields=['image', 'updated_at'])
    return Response(product_dto(_load_product(pk)))


# ------------------------------------------------------------------ variants

def _variant_form(data, partial):
    f = Form(data, partial)
    f.text('label', 'label', max_len=120)
    f.integer('priceToman', 'price_toman', min_value=1000, max_value=10**13)
    f.choice('stockMode', 'stock_mode', MODES)
    f.text('faceCurrency', 'face_currency', required=False, max_len=3)
    f.text('region', 'region', required=False, max_len=120)
    f.integer('durationMonths', 'duration_months', nullable=True, min_value=1, max_value=120)
    f.integer('sortOrder', 'sort_order', required=False)
    f.boolean('isActive', 'is_active')
    if not f.skip('faceValue'):
        raw = data.get('faceValue')
        if raw in (None, ''):
            f.clean['face_value'] = None
        else:
            try:
                fv = float(raw)
                if fv <= 0:
                    raise ValueError
                f.clean['face_value'] = round(fv, 2)
            except (TypeError, ValueError):
                f.err('faceValue', 'عدد معتبر وارد کنید.')
    clean = f.raise_if_errors()
    if 'face_currency' in clean:
        clean['face_currency'] = clean['face_currency'].upper()
    return clean


def _load_variant(pk):
    v = variants_with_stock().select_related('product').filter(pk=pk).first()
    if not v:
        raise ApiError(404, 'گزینه یافت نشد.')
    return v


@staff_view(['POST'])
def product_variants(request, pk):
    p = _load_product(pk)
    v = Variant.objects.create(product=p, **_variant_form(request.data, False))
    return Response(variant_dto(_load_variant(v.pk)), status=201)


@staff_view(['PATCH', 'DELETE'])
def variant_detail(request, pk):
    v = _load_variant(pk)
    if request.method == 'DELETE':
        if v.codes.exists():
            raise ApiError(409, 'این گزینه کد ثبت‌شده دارد و حذف نمی‌شود. آن را غیرفعال کنید.', code='protected')
        v.delete()
        return Response(status=204)
    for k, val in _variant_form(request.data, True).items():
        setattr(v, k, val)
    v.save()
    return Response(variant_dto(_load_variant(pk)))


# ------------------------------------------------------------------ gift codes

@staff_view(['GET', 'POST'])
def variant_codes(request, pk):
    v = _load_variant(pk)
    if request.method == 'GET':
        status = request.query_params.get('status')
        qs = v.codes.select_related('order_item__order').order_by('-created_at', '-id')
        if status in ('available', 'delivered', 'void'):
            qs = qs.filter(status=status)
        count, items = paginate(request, qs, 50, 200)
        counts = dict(v.codes.values_list('status').annotate(n=Count('id')))
        return Response({
            'count': count,
            'results': [code_dto(c, reveal=request.query_params.get('reveal') == '1') for c in items],
            'summary': {k: counts.get(k, 0) for k in ('available', 'delivered', 'void')},
        })

    raw = request.data.get('codes')
    lines = raw if isinstance(raw, list) else str(raw or '').splitlines()
    codes = []
    for line in lines:
        c = str(line).strip()
        if c and c not in codes:
            codes.append(c)
    if not codes:
        field_errors({'codes': ['حداقل یک کد وارد کنید (هر کد در یک خط).']})
    if len(codes) > 2000 or any(len(c) > 255 for c in codes):
        field_errors({'codes': ['حداکثر ۲۰۰۰ کد و هر کد حداکثر ۲۵۵ کاراکتر.']})
    note = str(request.data.get('note') or '').strip()[:255]
    existing = set(v.codes.filter(code__in=codes).values_list('code', flat=True))
    new = [c for c in codes if c not in existing]
    with transaction.atomic():
        GiftCode.objects.bulk_create([GiftCode(variant=v, code=c, note=note, created_by=request.user) for c in new])
        if v.stock_mode != 'codes':
            v.stock_mode = 'codes'
            v.save(update_fields=['stock_mode'])
    return Response({'added': len(new), 'duplicates': len(existing), 'variant': variant_dto(_load_variant(pk))}, status=201)


@staff_view(['POST'])
def code_void(request, pk):
    with transaction.atomic():
        c = GiftCode.objects.select_for_update().filter(pk=pk).first()
        if not c:
            raise ApiError(404, 'کد یافت نشد.')
        if c.status != 'available':
            raise ApiError(409, 'فقط کدهای موجود قابل ابطال هستند.', code='not_available')
        c.status = 'void'
        c.note = (str(request.data.get('note') or '').strip()[:255]) or c.note
        c.save(update_fields=['status', 'note'])
    return Response(code_dto(c))
