from modeltranslation.translator import TranslationOptions, register

from .models import CatalogCategory, CatalogItem


@register(CatalogCategory)
class CatalogCategoryTranslationOptions(TranslationOptions):
    fields = ('name',)


@register(CatalogItem)
class CatalogItemTranslationOptions(TranslationOptions):
    fields = ('name', 'description')

