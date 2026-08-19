import logging

from django.core.exceptions import RequestDataTooBig
from django.utils.translation import gettext as _
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from common.api.error_codes import ErrorCode
from core.observability import normalize_request_id, request_id_context


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

    # Exception messages may contain database details, credentials or provider
    # payloads. Correlate by request ID and type without copying the exception
    # text into either the response or application logs.
    logger.error(
        'Unhandled API exception in %s on %s (type=%s)',
        view_name,
        path,
        type(exc).__name__,
    )

    request_id = normalize_request_id(
        getattr(request, 'request_id', '') if request is not None else request_id_context.get()
    )

    return Response(
        {
            'status': status.HTTP_500_INTERNAL_SERVER_ERROR,
            'message': _('Internal server error'),
            'code': ErrorCode.SERVER_ERROR,
            'requestId': request_id,
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
