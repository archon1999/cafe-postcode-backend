from copy import deepcopy
import re

from django.db import migrations
from django.db.models import Max
from django.utils import timezone


def replace_item_prices(layout):
    changed = False
    for block in layout.get('blocks', []):
        if block.get('type') != 'items_table':
            continue
        for column in block.get('columns', []):
            value = column.get('value')
            if not isinstance(value, str):
                continue
            updated = re.sub(r'\{\{\s*item\.unitPrice\s*\}\}', '{{item.lineTotal}}', value)
            if updated != value:
                column['value'] = updated
                changed = True
    return changed


def publish_item_line_totals(apps, schema_editor):
    PrintTemplate = apps.get_model('printing', 'PrintTemplate')
    PrintTemplateVersion = apps.get_model('printing', 'PrintTemplateVersion')
    alias = schema_editor.connection.alias

    # Keep draft edits, and preserve published history by issuing a new revision.
    for draft in PrintTemplateVersion.objects.using(alias).filter(status='draft').iterator():
        if replace_item_prices(draft.layout):
            draft.save(using=alias, update_fields=('layout', 'updated_at'))

    templates = PrintTemplate.objects.using(alias).filter(
        published_version__isnull=False,
    ).select_related('published_version')
    for template in templates.iterator():
        previous = template.published_version
        layout = deepcopy(previous.layout)
        if not replace_item_prices(layout):
            continue
        revision = (template.versions.using(alias).aggregate(value=Max('revision'))['value'] or 0) + 1
        version = PrintTemplateVersion.objects.using(alias).create(
            template=template,
            revision=revision,
            schema_version=previous.schema_version,
            status='published',
            preset_key=previous.preset_key,
            layout=layout,
            created_by_id=previous.created_by_id,
            published_at=timezone.now(),
        )
        previous.status = 'retired'
        previous.save(using=alias, update_fields=('status', 'updated_at'))
        template.published_version = version
        template.save(using=alias, update_fields=('published_version', 'updated_at'))


class Migration(migrations.Migration):
    dependencies = [('printing', '0013_publish_service_fee_rate_labels')]

    operations = [migrations.RunPython(publish_item_line_totals, migrations.RunPython.noop)]
