from django.contrib import admin

from .models import CatalogCategory, CatalogItem

admin.site.register(CatalogCategory)
admin.site.register(CatalogItem)
