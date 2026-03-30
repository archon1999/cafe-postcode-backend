from collections import OrderedDict

from drf_yasg import openapi
from drf_yasg.app_settings import swagger_settings
from drf_yasg.inspectors import NotHandled, PaginatorInspector, SwaggerAutoSchema

from common.api.paginations import Pagination


class ModuleTaggedSwaggerAutoSchema(SwaggerAutoSchema):
    def get_tags(self, operation_keys=None):
        if 'tags' in self.overrides:
            return self.overrides['tags']

        module = getattr(self.view, '__module__', '')
        if module.startswith('apps.'):
            module_name = module.split('.')[1]
            return [module_name]

        return super().get_tags(operation_keys)


class CamelCasePaginationInspector(PaginatorInspector):
    def get_paginator_parameters(self, paginator):
        if not isinstance(paginator, Pagination):
            return NotHandled

        return [
            openapi.Parameter(
                'page',
                openapi.IN_QUERY,
                type=openapi.TYPE_INTEGER,
                description='Page number',
            ),
            openapi.Parameter(
                'pageSize',
                openapi.IN_QUERY,
                type=openapi.TYPE_INTEGER,
                description='Items per page',
            ),
        ]

    def get_paginated_response(self, paginator, response_schema):
        if not isinstance(paginator, Pagination):
            return NotHandled

        return openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties=OrderedDict(
                [
                    ('page', openapi.Schema(type=openapi.TYPE_INTEGER)),
                    ('pageSize', openapi.Schema(type=openapi.TYPE_INTEGER)),
                    ('count', openapi.Schema(type=openapi.TYPE_INTEGER)),
                    ('total', openapi.Schema(type=openapi.TYPE_INTEGER)),
                    ('pagesCount', openapi.Schema(type=openapi.TYPE_INTEGER)),
                    ('data', response_schema),
                ]
            ),
            required=['page', 'pageSize', 'count', 'total', 'pagesCount', 'data'],
        )


class CamelCaseSwaggerAutoSchema(ModuleTaggedSwaggerAutoSchema):
    paginator_inspectors = [
        CamelCasePaginationInspector,
        *swagger_settings.DEFAULT_PAGINATOR_INSPECTORS,
    ]
