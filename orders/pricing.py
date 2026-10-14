"""Server-side price calculation. The client never decides prices or totals."""
from datetime import timedelta
from decimal import Decimal

from catalog.models import Product, products_with_variants
from core.models import SiteSettings
from core.utils import iso, now, round_to_1000

QUOTE_TTL = timedelta(minutes=10)


def build_quote(items: list[dict]):
    product_ids = {i['productId'] for i in items}
    products = {p.id: p for p in products_with_variants(Product.objects.filter(pk__in=product_ids))}
    rate = SiteSettings.get().service_fee_rate

    lines = []
    for item in items:
        p = products.get(item['productId'])
        v = next((x for x in p.variants.all() if x.id == item['variantId']), None) if p else None
        if not p or not v:
            lines.append({
                'lineId': item['lineId'], 'productId': item['productId'], 'variantId': item['variantId'],
                'productName': 'محصول نامشخص', 'brandName': '', 'variantLabel': '', 'quantity': 0,
                'unitPriceToman': 0, 'lineTotalToman': 0, 'available': False,
                'issue': {'code': 'not_found', 'message': 'این محصول دیگر در فروشگاه موجود نیست.'},
            })
            continue

        available = p.is_active and p.category.is_active and v.available
        requested = item['quantity']
        max_qty = p.max_quantity_per_item
        if v.stock_mode == 'codes':
            max_qty = min(max_qty, max(1, v.stock))
        quantity = min(max(requested, 1), max_qty)
        unit = int(v.price_toman)
        line = {
            'lineId': item['lineId'], 'productId': p.id, 'variantId': v.id, 'productName': p.name,
            'brandName': p.brand_name, 'variantLabel': v.label, 'quantity': quantity, 'unitPriceToman': unit,
            'lineTotalToman': unit * quantity if available else 0, 'available': available,
        }
        if not available:
            line['issue'] = {'code': 'unavailable', 'message': 'این گزینه در حال حاضر موجود نیست و در مبلغ نهایی محاسبه نمی‌شود.'}
        elif item.get('knownUnitPriceToman') is not None and item['knownUnitPriceToman'] != unit:
            line['issue'] = {'code': 'price_changed', 'message': 'قیمت این مورد از آخرین بازدید شما تغییر کرده است.'}
        elif quantity != requested:
            line['issue'] = {'code': 'quantity_adjusted', 'message': f'حداکثر تعداد قابل خرید برای این مورد {max_qty} عدد است.'}
        lines.append(line)

    subtotal = sum(l['lineTotalToman'] for l in lines)
    fee = round_to_1000(Decimal(subtotal) * rate) if subtotal > 0 else 0
    discount = 0  # no discount system yet — never show fake discounts
    return {
        'lines': lines,
        'subtotalToman': subtotal,
        'serviceFeeToman': fee,
        'serviceFeeRate': float(rate),
        'discountToman': discount,
        'totalToman': subtotal + fee - discount,
        'validUntil': iso(now() + QUOTE_TTL),
    }


def parse_cart_items(raw) -> list[dict]:
    items = raw if isinstance(raw, list) else []
    out = []
    for i in items[:50]:
        if not isinstance(i, dict):
            continue
        try:
            qty = int(float(i.get('quantity', 1)))
        except (TypeError, ValueError):
            qty = 1
        known = i.get('knownUnitPriceToman')
        out.append({
            'lineId': str(i.get('lineId') or '')[:64],
            'productId': str(i.get('productId') or '')[:40],
            'variantId': str(i.get('variantId') or '')[:40],
            'quantity': qty,
            'knownUnitPriceToman': int(known) if isinstance(known, (int, float)) and not isinstance(known, bool) else None,
            'fields': i.get('fields') if isinstance(i.get('fields'), dict) else {},
        })
    return out
