from modeltranslation.translator import TranslationOptions, register

from .models import CatalogCategory, CatalogItem, ModifierGroup, ModifierOption


@register(CatalogCategory)
class CatalogCategoryTranslationOptions(TranslationOptions):
    fields = ('name',)


@register(CatalogItem)
class CatalogItemTranslationOptions(TranslationOptions):
    fields = ('name', 'description')


@register(ModifierGroup)
class ModifierGroupTranslationOptions(TranslationOptions):
    fields = ('name',)


@register(ModifierOption)
class ModifierOptionTranslationOptions(TranslationOptions):
    fields = ('name',)
