from modeltranslation.translator import TranslationOptions, register

from .models import DistributionPoint, PrepStation, Restaurant


@register(Restaurant)
class RestaurantTranslationOptions(TranslationOptions):
    fields = ('name', 'legal_name', 'address')


@register(PrepStation)
class PrepStationTranslationOptions(TranslationOptions):
    fields = ('name',)


@register(DistributionPoint)
class DistributionPointTranslationOptions(TranslationOptions):
    fields = ('name',)

