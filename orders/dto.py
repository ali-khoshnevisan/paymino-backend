from core.utils import iso
from payments.services import invoice_dto


def item_dto(it):
    return {
        'id': it.id,
        'productId': it.product_id or '',
        'productSlug': it.product_slug,
        'productName': it.product_name,
        'brandName': it.brand_name,
        'variantLabel': it.variant_label,
        'type': it.type,
        'quantity': it.quantity,
        'unitPriceToman': int(it.unit_price_toman),
        'lineTotalToman': int(it.line_total_toman),
        'fields': it.fields or {},
        'fieldLabels': it.field_labels or {},
        'deliveries': [{'kind': d.kind, 'value': d.value, 'deliveredAt': iso(d.delivered_at)} for d in it.deliveries.all()],
    }


def event_dto(e):
    return {'at': iso(e.at), 'status': e.status, 'paymentStatus': e.payment_status, 'message': e.message}


def order_dto(o):
    return {
        'id': o.id,
        'number': o.number,
        'status': o.status,
        'paymentStatus': o.payment_status,
        'items': [item_dto(i) for i in o.items.all()],
        'subtotalToman': int(o.subtotal_toman),
        'serviceFeeToman': int(o.service_fee_toman),
        'discountToman': int(o.discount_toman),
        'couponCode': o.coupon_code or None,
        'couponDiscountToman': int(o.coupon_discount_toman),
        'totalToman': int(o.total_toman),
        'paymentMethod': {'currency': o.payment_currency, 'network': o.payment_network} if o.payment_currency else None,
        'invoice': invoice_dto(o.current_invoice),
        'events': [event_dto(e) for e in o.events.all() if not e.internal],
        'createdAt': iso(o.created_at),
        'updatedAt': iso(o.updated_at),
    }


def order_list_item(o):
    items = list(o.items.all())
    return {
        'id': o.id,
        'number': o.number,
        'status': o.status,
        'paymentStatus': o.payment_status,
        'totalToman': int(o.total_toman),
        'itemCount': sum(i.quantity for i in items),
        'firstItemName': items[0].product_name if items else '',
        'createdAt': iso(o.created_at),
    }
