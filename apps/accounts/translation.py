from modeltranslation.translator import TranslationOptions, register

from .models import Permission, Role


@register(Permission)
class PermissionTranslationOptions(TranslationOptions):
    fields = ('name', 'description')


@register(Role)
class RoleTranslationOptions(TranslationOptions):
    fields = ('name', 'description')
