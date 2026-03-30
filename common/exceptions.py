from rest_framework import status
from rest_framework.exceptions import APIException
from django.utils.translation import gettext_lazy as _


class BaseAPIException(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = _('A server error occurred.')
    default_code = 'error'


class ValidationError(BaseAPIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = _('Invalid input.')
    default_code = 'invalid'


class AuthenticationError(BaseAPIException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = _('Authentication credentials were not provided.')
    default_code = 'authentication_failed'


class PermissionDenied(BaseAPIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = _('You do not have permission to perform this action.')
    default_code = 'permission_denied'


class NotFoundError(BaseAPIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = _('Not found.')
    default_code = 'not_found'


class ConflictError(BaseAPIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = _('A conflict occurred.')
    default_code = 'conflict'


class ServiceUnavailable(BaseAPIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = _('Service temporarily unavailable.')
    default_code = 'service_unavailable'
