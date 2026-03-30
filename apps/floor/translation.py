from modeltranslation.translator import TranslationOptions, register

from .models import Hall, ZoneOrCabin


@register(Hall)
class HallTranslationOptions(TranslationOptions):
    fields = ('name', 'description')


@register(ZoneOrCabin)
class ZoneOrCabinTranslationOptions(TranslationOptions):
    fields = ('name',)

