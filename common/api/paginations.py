from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from common.constants import (
    DEFAULT_PAGE_SIZE,
    LARGE_PAGE_SIZE,
    MAX_PAGE_SIZE,
    MINI_PAGE_SIZE,
    PAGE_SIZE_QUERY_PARAM,
    STANDARD_PAGE_SIZE,
)


class Pagination(PageNumberPagination):
    page_size = DEFAULT_PAGE_SIZE
    page_size_query_param = PAGE_SIZE_QUERY_PARAM
    max_page_size = MAX_PAGE_SIZE

    def get_paginated_response(self, data):
        return Response({
            'page': self.page.number,
            'pageSize': self.page.paginator.per_page,
            'count': len(data),
            'total': self.page.paginator.count,
            'pagesCount': self.page.paginator.num_pages,
            'data': data,
        })


class LargeResultsSetPagination(Pagination):
    page_size = LARGE_PAGE_SIZE


class StandardResultsSetPagination(Pagination):
    page_size = STANDARD_PAGE_SIZE


class SmallResultsSetPagination(Pagination):
    page_size = DEFAULT_PAGE_SIZE


class MiniResultsSetPagination(Pagination):
    page_size = MINI_PAGE_SIZE
