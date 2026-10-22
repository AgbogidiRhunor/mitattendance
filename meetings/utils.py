from django.core.paginator import Paginator


def paginate(request, queryset, per_page=25):
    """Return (page_obj, querystring-without-page) for the pagination partial."""
    paginator = Paginator(queryset, per_page)
    page_obj = paginator.get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return page_obj, params.urlencode()


def search_users(qs, query):
    """Every whitespace-separated term must match the name or student ID."""
    from django.db.models import Q

    for term in (query or "").split():
        qs = qs.filter(Q(full_name__icontains=term) | Q(student_id__icontains=term))
    return qs
