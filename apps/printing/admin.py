from django.contrib import admin

from .models import PrintDocument, PrintJob, PrintTemplate, PrintTemplateVersion

admin.site.register(PrintTemplate)
admin.site.register(PrintTemplateVersion)
admin.site.register(PrintDocument)
admin.site.register(PrintJob)
