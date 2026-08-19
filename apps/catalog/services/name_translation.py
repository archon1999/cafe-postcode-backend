from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import httpx
from django.conf import settings


class CatalogNameTranslationError(Exception):
    """Base error for catalog-name translation failures."""


class CatalogNameTranslationConfigurationError(CatalogNameTranslationError):
    """Raised when the Yandex Translate integration is not configured."""


class CatalogNameTranslationUpstreamError(CatalogNameTranslationError):
    """Raised when Yandex Translate rejects or cannot complete a request."""


def _match_case(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


_APOSTROPHES = "'`´ʻʼ‘’"
_LATIN_MULTI = (
    ("g'", "ғ"),
    ("o'", "ў"),
    ("sh", "ш"),
    ("ch", "ч"),
    ("yo", "ё"),
    ("yu", "ю"),
    ("ya", "я"),
    ("ye", "е"),
    ("ts", "ц"),
)
_LATIN_SINGLE = {
    "a": "а",
    "b": "б",
    "d": "д",
    "e": "е",
    "f": "ф",
    "g": "г",
    "h": "ҳ",
    "i": "и",
    "j": "ж",
    "k": "к",
    "l": "л",
    "m": "м",
    "n": "н",
    "o": "о",
    "p": "п",
    "q": "қ",
    "r": "р",
    "s": "с",
    "t": "т",
    "u": "у",
    "v": "в",
    "x": "х",
    "y": "й",
    "z": "з",
}


def uzbek_latin_to_cyrillic(value: str) -> str:
    normalized = value
    for apostrophe in _APOSTROPHES:
        normalized = normalized.replace(apostrophe, "'")

    output: list[str] = []
    index = 0
    while index < len(normalized):
        matched = False
        for source, replacement in _LATIN_MULTI:
            candidate = normalized[index : index + len(source)]
            if candidate.lower() == source:
                output.append(_match_case(candidate, replacement))
                index += len(source)
                matched = True
                break
        if matched:
            continue

        character = normalized[index]
        replacement = _LATIN_SINGLE.get(character.lower())
        output.append(_match_case(character, replacement) if replacement else character)
        index += 1

    return "".join(output)


_CYRILLIC_MULTI = {
    "ё": "yo",
    "ю": "yu",
    "я": "ya",
    "ш": "sh",
    "ч": "ch",
    "щ": "shch",
}
_CYRILLIC_SINGLE = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "ғ": "g‘",
    "д": "d",
    "е": "e",
    "ж": "j",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "қ": "q",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ў": "o‘",
    "ф": "f",
    "х": "x",
    "ҳ": "h",
    "ц": "ts",
    "ъ": "’",
    "ы": "i",
    "э": "e",
}


def uzbek_cyrillic_to_latin(value: str) -> str:
    output: list[str] = []
    for character in value:
        lowered = character.lower()
        replacement = _CYRILLIC_MULTI.get(lowered) or _CYRILLIC_SINGLE.get(lowered)
        if replacement is None:
            output.append("" if lowered == "ь" else character)
            continue
        output.append(_match_case(character, replacement))
    return "".join(output)


class YandexTranslateClient:
    endpoint = "https://translate.api.cloud.yandex.net/translate/v2/translate"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        folder_id: str | None = None,
        timeout: float | None = None,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
    ):
        self.api_key = api_key if api_key is not None else settings.YANDEX_TRANSLATE_API_KEY
        self.folder_id = folder_id if folder_id is not None else settings.YANDEX_TRANSLATE_FOLDER_ID
        self.timeout = timeout if timeout is not None else settings.YANDEX_TRANSLATE_TIMEOUT
        self.client_factory = client_factory

        if not self.api_key or not self.folder_id:
            raise CatalogNameTranslationConfigurationError(
                "Yandex Translate API key yoki folder ID sozlanmagan."
            )

    def translate(self, text: str, *, source_language: str, target_language: str) -> str:
        try:
            with self.client_factory(timeout=self.timeout) as client:
                response = client.post(
                    self.endpoint,
                    headers={
                        "Authorization": f"Api-Key {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "folderId": self.folder_id,
                        "sourceLanguageCode": source_language,
                        "targetLanguageCode": target_language,
                        "format": "PLAIN_TEXT",
                        "texts": [text],
                    },
                )
            response.raise_for_status()
            payload = response.json()
            translated = payload["translations"][0]["text"].strip()
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise CatalogNameTranslationUpstreamError(
                "Yandex Translate orqali tarjima qilib bo‘lmadi."
            ) from error

        if not translated:
            raise CatalogNameTranslationUpstreamError("Yandex Translate bo‘sh tarjima qaytardi.")
        if len(translated) > 255:
            raise CatalogNameTranslationUpstreamError("Tarjima qilingan nom 255 belgidan oshib ketdi.")
        return translated


@dataclass(frozen=True)
class LocalizedCatalogName:
    name_uz: str
    name_uz_crl: str
    name_ru: str

    def as_dict(self) -> dict[str, str]:
        return {
            "name_uz": self.name_uz,
            "name_uz_crl": self.name_uz_crl,
            "name_ru": self.name_ru,
        }


def translate_catalog_name(
    values: dict[str, str],
    *,
    client: YandexTranslateClient | None = None,
) -> LocalizedCatalogName:
    normalized = {
        key: str(values.get(key) or "").strip()
        for key in ("name_uz", "name_uz_crl", "name_ru")
    }
    filled = [(key, value) for key, value in normalized.items() if value]
    if len(filled) != 1:
        raise ValueError("Tarjima uchun aynan bitta tildagi nom to‘ldirilishi kerak.")

    source_key, source_text = filled[0]
    translator = client or YandexTranslateClient()

    if source_key == "name_ru":
        name_uz = translator.translate(source_text, source_language="ru", target_language="uz")
        return LocalizedCatalogName(
            name_uz=name_uz,
            name_uz_crl=uzbek_latin_to_cyrillic(name_uz),
            name_ru=source_text,
        )

    if source_key == "name_uz_crl":
        name_uz = uzbek_cyrillic_to_latin(source_text)
        return LocalizedCatalogName(
            name_uz=name_uz,
            name_uz_crl=source_text,
            name_ru=translator.translate(name_uz, source_language="uz", target_language="ru"),
        )

    return LocalizedCatalogName(
        name_uz=source_text,
        name_uz_crl=uzbek_latin_to_cyrillic(source_text),
        name_ru=translator.translate(source_text, source_language="uz", target_language="ru"),
    )
