from unittest.mock import Mock, patch

import httpx
from django.test import SimpleTestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.catalog.serializers.name_translation import CatalogNameTranslationSerializer
from apps.catalog.services.name_translation import (
    YandexTranslateClient,
    translate_catalog_name,
    uzbek_cyrillic_to_latin,
    uzbek_latin_to_cyrillic,
)


class UzbekTransliterationTests(SimpleTestCase):
    def test_latin_to_cyrillic_handles_uzbek_letters_and_title_case(self):
        self.assertEqual(
            uzbek_latin_to_cyrillic("Sho‘rva va G‘ijduvon choyi"),
            "Шўрва ва Ғиждувон чойи",
        )

    def test_cyrillic_to_latin_handles_uzbek_letters(self):
        self.assertEqual(
            uzbek_cyrillic_to_latin("Қовурилган гўшт ва чой"),
            "Qovurilgan go‘sht va choy",
        )


class CatalogNameTranslationTests(SimpleTestCase):
    def test_serializer_requires_exactly_one_source_language(self):
        empty = CatalogNameTranslationSerializer(data={})
        two_languages = CatalogNameTranslationSerializer(
            data={"name_uz": "Choy", "name_ru": "Чай"}
        )

        self.assertFalse(empty.is_valid())
        self.assertFalse(two_languages.is_valid())

    def test_russian_source_uses_one_yandex_call_and_transliterates_uzbek(self):
        client = Mock()
        client.translate.return_value = "Ko‘k choy"

        result = translate_catalog_name(
            {"name_uz": "", "name_uz_crl": "", "name_ru": "Зелёный чай"},
            client=client,
        )

        self.assertEqual(result.name_uz, "Ko‘k choy")
        self.assertEqual(result.name_uz_crl, "Кўк чой")
        self.assertEqual(result.name_ru, "Зелёный чай")
        client.translate.assert_called_once_with(
            "Зелёный чай", source_language="ru", target_language="uz"
        )

    def test_cyrillic_source_transliterates_before_yandex(self):
        client = Mock()
        client.translate.return_value = "Горячий чай"

        result = translate_catalog_name(
            {"name_uz": "", "name_uz_crl": "Иссиқ чой", "name_ru": ""},
            client=client,
        )

        self.assertEqual(result.name_uz, "Issiq choy")
        self.assertEqual(result.name_uz_crl, "Иссиқ чой")
        client.translate.assert_called_once_with(
            "Issiq choy", source_language="uz", target_language="ru"
        )

    def test_yandex_client_sends_scoped_api_request(self):
        response = httpx.Response(
            200,
            json={"translations": [{"text": "Чай", "detectedLanguageCode": "uz"}]},
            request=httpx.Request("POST", YandexTranslateClient.endpoint),
        )
        http_client = Mock()
        http_client.__enter__ = Mock(return_value=http_client)
        http_client.__exit__ = Mock(return_value=False)
        http_client.post.return_value = response
        client_factory = Mock(return_value=http_client)

        translated = YandexTranslateClient(
            api_key="secret",
            folder_id="folder-id",
            timeout=5,
            client_factory=client_factory,
        ).translate("Choy", source_language="uz", target_language="ru")

        self.assertEqual(translated, "Чай")
        request = http_client.post.call_args
        self.assertEqual(request.kwargs["headers"]["Authorization"], "Api-Key secret")
        self.assertEqual(request.kwargs["json"]["folderId"], "folder-id")
        self.assertEqual(request.kwargs["json"]["texts"], ["Choy"])


class CatalogNameTranslationApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="catalog-translator",
            password="test-password",
        )
        self.client.force_authenticate(self.user)

    @patch("apps.catalog.api.admin.views.translations.translate_catalog_name")
    def test_endpoint_returns_all_localized_names(self, translate_mock):
        translate_mock.return_value.as_dict.return_value = {
            "name_uz": "Issiq choy",
            "name_uz_crl": "Иссиқ чой",
            "name_ru": "Горячий чай",
        }

        response = self.client.post(
            "/api/v1/admin/catalog/translations/name/",
            {"name_uz": "Issiq choy", "name_uz_crl": "", "name_ru": ""},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name_ru"], "Горячий чай")

    def test_endpoint_rejects_more_than_one_source_language(self):
        response = self.client.post(
            "/api/v1/admin/catalog/translations/name/",
            {"name_uz": "Choy", "name_uz_crl": "", "name_ru": "Чай"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
