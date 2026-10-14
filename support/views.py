from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core import mail
from core.auth import require_user
from core.errors import ApiError, field_errors
from core.models import Counter, SiteSettings
from core.utils import as_str, throttle
from orders.models import Order

from .dto import ticket_dto
from .models import Ticket, TicketMessage


def _qs():
    return Ticket.objects.select_related('order').prefetch_related('messages')


def _owned(user, ticket_id):
    t = _qs().filter(pk=ticket_id, user=user).first()
    if not t:
        raise ApiError(404, 'درخواست یافت نشد.', code='ticket_not_found')
    return t


@api_view(['GET', 'POST'])
def tickets(request):
    user = require_user(request)
    if request.method == 'GET':
        results = [ticket_dto(t) for t in _qs().filter(user=user)[:200]]
        return Response({'count': len(results), 'results': results})

    throttle(f'ticket:{user.pk}', 10, 3600)
    subject = as_str(request.data.get('subject')).strip()
    body = as_str(request.data.get('body')).strip()
    order_number = as_str(request.data.get('orderNumber')).strip() or None

    errors = {}
    if len(subject) < 3:
        errors['subject'] = ['موضوع درخواست را وارد کنید.']
    elif len(subject) > 200:
        errors['subject'] = ['موضوع بیش از حد طولانی است.']
    if len(body) < 10:
        errors['body'] = ['توضیحات باید حداقل ۱۰ کاراکتر باشد.']
    if len(body) > 3000:
        errors['body'] = ['توضیحات بیش از حد طولانی است.']
    order = None
    if order_number:
        order = Order.objects.filter(user=user, number=order_number).first()
        if not order:
            errors['orderNumber'] = ['سفارشی با این شماره در حساب شما یافت نشد.']
    if errors:
        field_errors(errors)

    with transaction.atomic():
        t = Ticket.objects.create(number=f'T-{Counter.next("ticket", 500)}', user=user, subject=subject, order=order)
        TicketMessage.objects.create(ticket=t, author=user, body=body)
    admin_email = SiteSettings.get().support_email
    if admin_email:
        mail.send(admin_email, f'درخواست جدید {t.number}', f'{user.email}\n{subject}\n\n{body}')
    return Response(ticket_dto(_owned(user, t.pk)), status=201)


@api_view(['GET'])
def ticket_detail(request, ticket_id):
    user = require_user(request)
    return Response(ticket_dto(_owned(user, ticket_id)))


@api_view(['POST'])
def ticket_message(request, ticket_id):
    user = require_user(request)
    throttle(f'ticket-msg:{user.pk}', 30, 3600)
    t = _owned(user, ticket_id)
    if t.status == 'closed':
        raise ApiError(409, 'این درخواست بسته شده است.', code='ticket_closed')
    body = as_str(request.data.get('body')).strip()
    if len(body) < 2:
        field_errors({'body': ['پیام را وارد کنید.']})
    if len(body) > 3000:
        field_errors({'body': ['پیام بیش از حد طولانی است.']})
    TicketMessage.objects.create(ticket=t, author=user, body=body)
    t.status = 'open'
    t.save(update_fields=['status', 'updated_at'])
    return Response(ticket_dto(_owned(user, t.pk)))
