from core.utils import iso, media_url


def money(v):
    return int(v or 0)


def category_dto(c):
    return {'id': c.id, 'slug': c.slug, 'name': c.name, 'description': c.description, 'icon': c.icon,
            'sortOrder': c.sort_order, 'isActive': c.is_active, 'productCount': getattr(c, 'product_count', None)}


def provider_dto(p):
    return {'id': p.id, 'slug': p.slug, 'name': p.name, 'categoryId': p.category_id, 'productCount': getattr(p, 'product_count', None)}


def variant_dto(v):
    return {
        'id': v.id, 'label': v.label, 'faceValue': float(v.face_value) if v.face_value is not None else None,
        'faceCurrency': v.face_currency, 'region': v.region, 'durationMonths': v.duration_months,
        'priceToman': money(v.price_toman), 'stockMode': v.stock_mode, 'isActive': v.is_active, 'sortOrder': v.sort_order,
        'stock': getattr(v, 'stock_available', None) if getattr(v, 'stock_available', None) is not None else v.stock,
        'available': v.available,
    }


def product_dto(p, with_variants=True):
    d = {
        'id': p.id, 'slug': p.slug, 'name': p.name, 'brandName': p.brand_name,
        'categoryId': p.category_id, 'categoryName': p.category.name, 'providerId': p.provider_id, 'providerName': p.provider.name,
        'type': p.type, 'shortDescription': p.short_description, 'description': p.description, 'imageUrl': media_url(p.image),
        'regions': p.regions or [], 'restrictions': p.restrictions or [], 'redemptionNotes': p.redemption_notes or [],
        'deliveryMethod': p.delivery_method, 'fulfillmentEstimate': p.fulfillment_estimate, 'refundPolicy': p.refund_policy,
        'requiredFields': p.required_fields or [], 'maxQuantityPerItem': p.max_quantity_per_item, 'popularity': p.popularity,
        'isActive': p.is_active, 'createdAt': iso(p.created_at), 'updatedAt': iso(p.updated_at),
        'discountPercent': p.discount_percent, 'discountStartsAt': iso(p.discount_starts_at), 'discountEndsAt': iso(p.discount_ends_at),
        'discountActive': p.active_discount_percent() > 0,
        'article': p.article, 'faqs': p.faqs or [], 'seoTitle': p.seo_title, 'seoDescription': p.seo_description,
    }
    if with_variants:
        d['variants'] = [variant_dto(v) for v in p.variants.all()]
    return d


def product_row(p):
    variants = list(p.variants.all())
    prices = [money(v.price_toman) for v in variants if v.is_active]
    code_variants = [v for v in variants if v.stock_mode == 'codes' and v.is_active]
    return {
        'id': p.id, 'slug': p.slug, 'name': p.name, 'brandName': p.brand_name, 'categoryName': p.category.name,
        'type': p.type, 'isActive': p.is_active, 'imageUrl': media_url(p.image), 'variantCount': len(variants),
        'minPriceToman': min(prices) if prices else None,
        'stock': sum(v.stock for v in code_variants) if code_variants else None,
        'lowStock': any(v.stock == 0 for v in code_variants),
        'popularity': p.popularity, 'createdAt': iso(p.created_at),
        'discountPercent': p.active_discount_percent() or None,
    }


def code_dto(c, reveal=False):
    return {
        'id': c.id, 'code': c.code if reveal or c.status == 'available' else c.code[:4] + '••••',
        'status': c.status, 'note': c.note, 'createdAt': iso(c.created_at), 'deliveredAt': iso(c.delivered_at),
        'orderNumber': c.order_item.order.number if c.order_item_id else None,
        'orderId': c.order_item.order_id if c.order_item_id else None,
    }


def user_row(u):
    return {
        'id': u.id, 'fullName': u.full_name, 'email': u.email, 'phone': u.phone, 'emailVerified': u.email_verified,
        'isActive': u.is_active, 'isStaff': u.is_staff, 'isSuperuser': u.is_superuser, 'createdAt': iso(u.created_at),
        'lastLogin': iso(u.last_login), 'orderCount': getattr(u, 'order_count', None), 'totalSpentToman': money(getattr(u, 'total_spent', 0)),
    }


def admin_order_row(o):
    items = list(o.items.all())
    return {
        'id': o.id, 'number': o.number, 'status': o.status, 'paymentStatus': o.payment_status,
        'totalToman': money(o.total_toman), 'itemCount': sum(i.quantity for i in items),
        'firstItemName': items[0].product_name if items else '', 'needsReview': o.needs_review,
        'user': {'id': o.user_id, 'fullName': o.user.full_name, 'email': o.user.email},
        'createdAt': iso(o.created_at), 'updatedAt': iso(o.updated_at),
    }


def ticket_row(t):
    last = list(t.messages.all())[-1:] or [None]
    return {
        'id': t.id, 'number': t.number, 'subject': t.subject, 'status': t.status,
        'orderNumber': t.order.number if t.order_id else None, 'orderId': t.order_id,
        'user': {'id': t.user_id, 'fullName': t.user.full_name, 'email': t.user.email},
        'lastMessageFrom': ('support' if last[0].from_staff else 'user') if last[0] else None,
        'createdAt': iso(t.created_at), 'updatedAt': iso(t.updated_at),
    }
