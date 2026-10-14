from core.utils import iso, media_url


def _num(v):
    if v is None:
        return None
    f = float(v)
    return int(f) if f.is_integer() else f


def variant_dto(v):
    d = {'id': v.id, 'label': v.label, 'priceToman': int(v.price_toman), 'available': v.available}
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


def product_dto(p):
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
        'variants': [variant_dto(v) for v in active_variants(p)],
        'available': p.is_active,
        'createdAt': iso(p.created_at),
    }


def product_list_item(p):
    variants = active_variants(p)
    prices = [int(v.price_toman) for v in variants if v.available]
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
        'available': p.is_active and bool(prices),
        'createdAt': iso(p.created_at),
        'minPriceToman': min(prices) if prices else None,
        'variantCount': len(variants),
        'durations': durations,
    }
