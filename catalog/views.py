from django.db.models import Count, Q
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.errors import ApiError
from core.utils import as_int, normalize_search

from .dto import product_dto, product_list_item
from .models import Category, Product, products_with_variants


@api_view(['GET'])
def categories(request):
    qs = Category.objects.filter(is_active=True).annotate(
        product_count=Count('products', filter=Q(products__is_active=True))
    ).order_by('sort_order', 'id')
    return Response([
        {'slug': c.slug, 'name': c.name, 'description': c.description, 'icon': c.icon, 'productCount': c.product_count}
        for c in qs
    ])


def _duration_label(v: str):
    return 'سالانه' if v == '12' else 'ماهانه' if v == '1' else f'{v} ماهه'


@api_view(['GET'])
def products(request):
    q = request.query_params
    s = lambda k: (q.get(k) or '').strip() or None  # noqa: E731
    search, category, provider, region = s('q'), s('category'), s('provider'), s('region')
    duration, min_price, max_price = as_int(q.get('duration')), as_int(q.get('minPrice')), as_int(q.get('maxPrice'))
    ordering = s('ordering') or 'popular'
    page = max(1, as_int(q.get('page'), 1))
    page_size = min(48, max(1, as_int(q.get('pageSize'), 24)))

    qs = Product.objects.filter(is_active=True, category__is_active=True)
    if category:
        qs = qs.filter(category__slug=category)
    base = list(products_with_variants(qs))  # catalog is small; Persian-aware filtering in Python

    if search:
        needle = normalize_search(search)
        base = [
            p for p in base
            if any(needle in normalize_search(t) for t in (p.name, p.brand_name, p.short_description, p.provider.name))
        ]

    filtered = base
    if provider:
        filtered = [p for p in filtered if p.provider.slug == provider]
    if region:
        filtered = [p for p in filtered if region in (p.regions or [])]
    if duration:
        filtered = [p for p in filtered if any(v.is_active and v.duration_months == duration for v in p.variants.all())]

    items = [(product_list_item(p), p.popularity) for p in filtered]
    if min_price is not None:
        items = [x for x in items if x[0]['minPriceToman'] is not None and x[0]['minPriceToman'] >= min_price]
    if max_price is not None:
        items = [x for x in items if x[0]['minPriceToman'] is not None and x[0]['minPriceToman'] <= max_price]

    big = 10**18
    price = lambda x: x[0]['minPriceToman'] if x[0]['minPriceToman'] is not None else big  # noqa: E731
    if ordering == 'newest':
        items.sort(key=lambda x: x[0]['createdAt'], reverse=True)
    elif ordering == 'price_asc':
        items.sort(key=price)
    elif ordering == 'price_desc':
        items.sort(key=price, reverse=True)
    else:
        items.sort(key=lambda x: x[1], reverse=True)

    count = len(items)
    results = [x[0] for x in items[(page - 1) * page_size: page * page_size]]

    def tally(values, label):
        counts = {}
        for v in values:
            counts[v] = counts.get(v, 0) + 1
        return [{'value': v, 'label': label(v), 'count': c} for v, c in counts.items()]

    base_items = [product_list_item(p) for p in base]
    prices = [i['minPriceToman'] for i in base_items if i['minPriceToman'] is not None]
    provider_names = {p.provider.slug: p.provider.name for p in base}
    facets = {
        'providers': tally([p.provider.slug for p in base], lambda v: provider_names.get(v, v)),
        'regions': tally([r for p in base for r in (p.regions or [])], lambda v: v),
        'durations': tally([str(d) for i in base_items for d in i['durations']], _duration_label),
        'priceRange': {'min': min(prices), 'max': max(prices)} if prices else None,
    }
    return Response({'count': count, 'results': results, 'facets': facets})


@api_view(['GET'])
def product_detail(request, slug):
    p = products_with_variants(Product.objects.filter(slug=slug, is_active=True, category__is_active=True)).first()
    if not p:
        raise ApiError(404, 'محصول یافت نشد.', code='product_not_found')
    return Response(product_dto(p))
