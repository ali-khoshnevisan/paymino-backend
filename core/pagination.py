from .utils import as_int


def paginate(request, queryset, default_size=25, max_size=100):
    page = max(1, as_int(request.query_params.get('page'), 1))
    size = min(max_size, max(1, as_int(request.query_params.get('pageSize'), default_size)))
    count = queryset.count()
    items = list(queryset[(page - 1) * size: page * size])
    return count, items
