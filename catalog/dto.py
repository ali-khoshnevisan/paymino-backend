from core.utils import iso, media_url


def _num(v):
    if v is None:
        return None
    f = float(v)
    return int(f) if f.is_integer() else f


def variant_dto(v, percent=0):
    # priceToman is always what the customer pays; originalPriceToman only appears when a discount lowers it.
    final = v.final_price(percent)
    d = {'id': v.id, 'label': v.label, 'priceToman': final, 'available': v.available}
    if final < int(v.price_toman):
        d['originalPriceToman'] = int(v.price_toman)
    if v.face_value is not None:
        d['faceValue'] = _num(v.face_value)
    if v.face_currency:
        d['faceCurrency'] = v.face_currency
    if v.region:
        d['region'] = v.region
    if v.duration_months:
        d['durationMonths'] = v.duration_months
    return d


def active_variants(p):
    return [v for v in p.variants.all() if v.is_active]


def _discount_fields(p, percent):
    return {
        'discountPercent': percent or None,
        'discountEndsAt': iso(p.discount_ends_at) if percent else None,
    }


def product_dto(p):
    percent = p.active_discount_percent()
    return {
        'id': p.id,
        'slug': p.slug,
        'name': p.name,
        'brandName': p.brand_name,
        'categorySlug': p.category.slug,
        'providerSlug': p.provider.slug,
        'type': p.type,
        'shortDescription': p.short_description,
        'description': p.description,
        'imageUrl': media_url(p.image),
        'regions': p.regions or [],
        'restrictions': p.restrictions or [],
        'redemptionNotes': p.redemption_notes or [],
        'deliveryMethod': p.delivery_method,
        'fulfillmentEstimate': p.fulfillment_estimate or None,
        'refundPolicy': p.refund_policy,
        'requiredFields': p.required_fields or [],
        'maxQuantityPerItem': p.max_quantity_per_item,
        'variants': [variant_dto(v, percent) for v in active_variants(p)],
        'available': p.is_active,
        'createdAt': iso(p.created_at),
        **_discount_fields(p, percent),
        'article': p.article,
        'faqs': p.faqs or [],
        'seoTitle': p.seo_title or None,
        'seoDescription': p.seo_description or None,
    }


def product_list_item(p):
    percent = p.active_discount_percent()
    variants = active_variants(p)
    # (price paid, list price) of each variant that can be bought; the cheapest one is the card's "from" price
    offers = [(v.final_price(percent), int(v.price_toman)) for v in variants if v.available]
    cheapest = min(offers) if offers else None
    discounted = any(final < listed for final, listed in offers)
    durations = []
    for v in variants:
        if v.duration_months and v.duration_months not in durations:
            durations.append(v.duration_months)
    return {
        'id': p.id,
        'slug': p.slug,
        'name': p.name,
        'brandName': p.brand_name,
        'categorySlug': p.category.slug,
        'providerSlug': p.provider.slug,
        'type': p.type,
        'shortDescription': p.short_description,
        'imageUrl': media_url(p.image),
        'regions': p.regions or [],
        'available': p.is_active and bool(offers),
        'createdAt': iso(p.created_at),
        'minPriceToman': cheapest[0] if cheapest else None,
        'minOriginalPriceToman': cheapest[1] if cheapest and cheapest[0] < cheapest[1] else None,
        'variantCount': len(variants),
        'durations': durations,
        **_discount_fields(p, percent if discounted else 0),
    }
