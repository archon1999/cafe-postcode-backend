import logging

from django.core.exceptions import RequestDataTooBig
from django.utils.translation import gettext as _
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from common.api.error_codes import ErrorCode


logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    if isinstance(exc, RequestDataTooBig):
        return Response(
            {
                'status': status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                'message': _('Uploaded file is too large.'),
                'code': ErrorCode.REQUEST_TOO_LARGE,
            },
            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    response = exception_handler(exc, context)

    if response is not None:
        if isinstance(response.data, dict):
            detail = response.data.get('detail')
            if detail and 'message' not in response.data:
                response.data['message'] = str(detail)
            if detail and 'code' not in response.data and hasattr(detail, 'code'):
                response.data['code'] = detail.code
        return response

    view = context.get('view')
    request = context.get('request')
    path = request.path if request else 'unknown path'
    view_name = view.__class__.__name__ if view else 'unknown view'

    logger.exception('Unhandled API exception in %s on %s', view_name, path, exc_info=exc)

    message = str(exc).strip() or _('Internal server error')

    return Response(
        {
            'status': status.HTTP_500_INTERNAL_SERVER_ERROR,
            'message': message,
            'code': ErrorCode.SERVER_ERROR,
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
