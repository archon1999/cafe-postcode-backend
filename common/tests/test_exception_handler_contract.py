from django.core.exceptions import RequestDataTooBig
from django.test import SimpleTestCase
from django.utils import translation
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound

from common.api.error_codes import ErrorCode
from common.api.exception_handler import custom_exception_handler
from common.exceptions import (
    AuthenticationError,
    BaseAPIException,
    ConflictError,
    NotFoundError,
    PermissionDenied,
    ServiceUnavailable,
    ValidationError,
)


class ExceptionHandlerContractTests(SimpleTestCase):
    def test_backend_owned_error_code_values_are_unique_plain_strings(self):
        exception_codes = (
            BaseAPIException.default_code,
            ValidationError.default_code,
            AuthenticationError.default_code,
            PermissionDenied.default_code,
            NotFoundError.default_code,
            ConflictError.default_code,
            ServiceUnavailable.default_code,
        )
        handler_codes = (
            custom_exception_handler(RequestDataTooBig(), {}).data['code'],
            custom_exception_handler(RuntimeError('failure'), {}).data['code'],
        )
        codes = exception_codes + handler_codes

        self.assertEqual(codes, ErrorCode.ALL)
        self.assertEqual(
            codes,
            (
                'error',
                'invalid',
                'authentication_failed',
                'permission_denied',
                'not_found',
                'conflict',
                'service_unavailable',
                'request_too_large',
                'server_error',
            ),
        )
        self.assertTrue(all(type(code) is str for code in codes))
        self.assertEqual(len(codes), len(set(codes)))

    def test_custom_and_drf_detail_errors_expose_message_and_stable_code(self):
        conflict = custom_exception_handler(ConflictError('Already exists.'), {})
        not_found = custom_exception_handler(NotFound('Missing.'), {})

        self.assertEqual(conflict.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            conflict.data,
            {
                'detail': 'Already exists.',
                'message': 'Already exists.',
                'code': 'conflict',
            },
        )
        self.assertEqual(not_found.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            not_found.data,
            {
                'detail': 'Missing.',
                'message': 'Missing.',
                'code': 'not_found',
            },
        )

    def test_nested_serializer_field_errors_keep_their_field_shape(self):
        response = custom_exception_handler(
            serializers.ValidationError({'name': ['Required.'], 'items': {0: ['Invalid.']}}),
            {},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn('message', response.data)
        self.assertNotIn('code', response.data)
        self.assertEqual(str(response.data['name'][0]), 'Required.')
        self.assertEqual(response.data['name'][0].code, 'invalid')
        self.assertEqual(str(response.data['items'][0][0]), 'Invalid.')
        self.assertEqual(response.data['items'][0][0].code, 'invalid')

    def test_request_too_large_has_an_explicit_envelope(self):
        response = custom_exception_handler(RequestDataTooBig('raw detail is hidden'), {})

        self.assertEqual(response.status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        self.assertEqual(response.data['status'], status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        self.assertEqual(response.data['code'], 'request_too_large')
        self.assertNotEqual(response.data['message'], 'raw detail is hidden')

    def test_unhandled_exception_has_server_error_envelope(self):
        response = custom_exception_handler(RuntimeError('unexpected failure'), {})

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(
            response.data,
            {
                'status': status.HTTP_500_INTERNAL_SERVER_ERROR,
                'message': 'unexpected failure',
                'code': 'server_error',
            },
        )

    def test_error_codes_do_not_change_with_locale(self):
        codes = []
        for language in ('uz', 'ru', 'uz-crl'):
            with translation.override(language):
                codes.append(custom_exception_handler(ConflictError(), {}).data['code'])
                codes.append(custom_exception_handler(RequestDataTooBig(), {}).data['code'])

        self.assertEqual(codes, ['conflict', 'request_too_large'] * 3)
