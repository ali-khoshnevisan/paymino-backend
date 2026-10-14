from django.db.models import Q
from rest_framework.response import Response

from core import mail
from core.errors import ApiError, field_errors
from core.pagination import paginate
from core.utils import iso
from support.models import Ticket, TicketMessage

from .common import staff_view
from .dto import ticket_row


def _qs():
    return Ticket.objects.select_related('user', 'order').prefetch_related('messages__author').order_by('-updated_at')


def _detail(t):
    d = ticket_row(t)
    d['messages'] = [
        {'id': m.id, 'from': 'support' if m.from_staff else 'user', 'body': m.body, 'at': iso(m.at),
         'author': m.author.full_name if m.author_id else None}
        for m in t.messages.all()
    ]
    return d


def _load(pk):
    t = _qs().filter(pk=pk).first()
    if not t:
        raise ApiError(404, 'درخواست یافت نشد.')
    return t


@staff_view(['GET'])
def tickets(request):
    q = request.query_params
    qs = _qs()
    if q.get('status') in ('open', 'answered', 'closed'):
        qs = qs.filter(status=q['status'])
    if q.get('user'):
        qs = qs.filter(user_id=q['user'])
    if q.get('q'):
        t = q['q'].strip()
        qs = qs.filter(Q(number__iexact=t) | Q(subject__icontains=t) | Q(user__email__icontains=t) | Q(order__number__iexact=t))
    count, items = paginate(request, qs, 25, 100)
    return Response({'count': count, 'results': [ticket_row(t) for t in items]})


@staff_view(['GET', 'PATCH'])
def ticket_detail(request, pk):
    t = _load(pk)
    if request.method == 'PATCH':
        status = request.data.get('status')
        if status not in ('open', 'answered', 'closed'):
            field_errors({'status': ['وضعیت نامعتبر است.']})
        t.status = status
        t.save(update_fields=['status', 'updated_at'])
        t = _load(pk)
    return Response(_detail(t))


@staff_view(['POST'])
def ticket_reply(request, pk):
    t = _load(pk)
    body = str(request.data.get('body') or '').strip()
    if len(body) < 2 or len(body) > 5000:
        field_errors({'body': ['متن پاسخ را وارد کنید.']})
    close = request.data.get('close') is True
    TicketMessage.objects.create(ticket=t, from_staff=True, author=request.user, body=body)
    t.status = 'closed' if close else 'answered'
    t.save(update_fields=['status', 'updated_at'])
    mail.send(t.user.email, f'پاسخ به درخواست {t.number}',
              f'سلام {t.user.full_name}\n\nبه درخواست «{t.subject}» پاسخ داده شد:\n\n{body}\n\n{mail.frontend(f"/account/support/{t.id}")}')
    return Response(_detail(_load(pk)))
