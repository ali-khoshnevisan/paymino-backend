from core.utils import iso


def ticket_dto(t):
    return {
        'id': t.id,
        'number': t.number,
        'subject': t.subject,
        'orderNumber': t.order.number if t.order_id else None,
        'status': t.status,
        'messages': [{'from': 'support' if m.from_staff else 'user', 'body': m.body, 'at': iso(m.at)} for m in t.messages.all()],
        'createdAt': iso(t.created_at),
        'updatedAt': iso(t.updated_at),
    }
