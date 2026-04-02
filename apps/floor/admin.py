from django.contrib import admin

from .models import DiningTable, Hall, TableSession, ZoneOrCabin

admin.site.register(Hall)
admin.site.register(ZoneOrCabin)
admin.site.register(DiningTable)
admin.site.register(TableSession)
