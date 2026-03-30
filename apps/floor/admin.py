from django.contrib import admin

from .models import DiningTable, Hall, LayoutObject, LayoutTemplate, TableSession, ZoneOrCabin

admin.site.register(Hall)
admin.site.register(ZoneOrCabin)
admin.site.register(DiningTable)
admin.site.register(LayoutTemplate)
admin.site.register(LayoutObject)
admin.site.register(TableSession)

