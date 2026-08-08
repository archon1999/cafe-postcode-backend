from django.contrib import admin

from .models import (
    CatalogCategory,
    CatalogItem,
    CatalogItemGroup,
    CatalogItemGroupMember,
    CatalogItemModifierGroup,
    ModifierGroup,
    ModifierOption,
)

admin.site.register(CatalogCategory)
admin.site.register(CatalogItem)
admin.site.register(CatalogItemGroup)
admin.site.register(CatalogItemGroupMember)
admin.site.register(ModifierGroup)
admin.site.register(ModifierOption)
admin.site.register(CatalogItemModifierGroup)
