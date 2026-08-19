from copy import deepcopy

from django.db import migrations
from django.db.models import Max


SERVICE_FEE_VALUES = {
    '{{totals.restaurantServiceFee}}',
    '{{totals.hallServiceFee}}',
    '{{totals.tableServiceFee}}',
}


def _enable_item_headers(layout):
    changed = False
    for block in layout.get('blocks', []):
        if block.get('type') == 'items_table' and block.get('showHeaders') is not True:
            block['showHeaders'] = True
            changed = True
    return changed


def _clean_kitchen_layout(layout):
    changed = _enable_item_headers(layout)
    cleaned = []
    inside_footer = False
    for block in layout.get('blocks', []):
        block_id = str(block.get('id') or '')
        if block_id == 'footer-divider':
            inside_footer = True
            changed = True
            continue
        if inside_footer:
            if block.get('type') in {'feed', 'cut'}:
                cleaned.append(block)
            else:
                changed = True
            continue
        if block_id in {'footer', 'footer-thanks', 'footer-appetite'}:
            changed = True
            continue
        if block.get('type') == 'text' and '{{restaurant.address}}' in str(block.get('text') or ''):
            changed = True
            continue
        rows = block.get('rows')
        if isinstance(rows, list):
            filtered_rows = [
                row for row in rows if row.get('value') != '{{restaurant.address}}'
            ]
            if len(filtered_rows) != len(rows):
                block['rows'] = filtered_rows
                changed = True
        cleaned.append(block)
    layout['blocks'] = cleaned
    return changed


def _reorder_payment_totals(layout):
    changed = _enable_item_headers(layout)
    blocks = layout.get('blocks', [])
    totals_index = next(
        (
            index
            for index, block in enumerate(blocks)
            if block.get('role') == 'totals' or block.get('id') == 'totals'
        ),
        None,
    )
    if totals_index is None:
        return changed

    totals = blocks[totals_index]
    rows = totals.get('rows')
    if not isinstance(rows, list):
        return changed
    service_rows = [row for row in rows if row.get('value') in SERVICE_FEE_VALUES]
    if not service_rows:
        return changed

    total_rows = [row for row in rows if row.get('value') not in SERVICE_FEE_VALUES]
    grand_total_rows = [row for row in total_rows if row.get('value') == '{{totals.total}}']
    totals['rows'] = [
        row for row in total_rows if row.get('value') != '{{totals.total}}'
    ] + grand_total_rows

    if totals_index > 0 and blocks[totals_index - 1].get('type') == 'divider':
        divider = blocks[totals_index - 1]
        divider['id'] = 'service-fees-divider'
        insert_at = totals_index
    else:
        blocks.insert(totals_index, {'id': 'service-fees-divider', 'type': 'divider'})
        insert_at = totals_index + 1
    blocks[insert_at:insert_at] = [
        {'id': 'service-fees', 'type': 'totals', 'rows': service_rows},
        {'id': 'totals-divider', 'type': 'divider'},
    ]
    return True


def _publish_updated_layout(PrintTemplateVersion, template, layout):
    previous = template.published_version
    revision = (template.versions.aggregate(value=Max('revision'))['value'] or 0) + 1
    version = PrintTemplateVersion.objects.create(
        template=template,
        revision=revision,
        schema_version=1,
        status='published',
        preset_key=previous.preset_key,
        layout=layout,
        created_by_id=previous.created_by_id,
        published_at=previous.published_at,
    )
    previous.status = 'retired'
    previous.save(update_fields=('status', 'updated_at'))
    template.published_version = version
    template.save(update_fields=('published_version', 'updated_at'))


def unify_receipt_templates(apps, schema_editor):
    PrintTemplate = apps.get_model('printing', 'PrintTemplate')
    PrintTemplateVersion = apps.get_model('printing', 'PrintTemplateVersion')

    templates = PrintTemplate.objects.filter(
        kind__in=['kitchen_ticket', 'payment_receipt_plain', 'payment_receipt_fiscal'],
        published_version__isnull=False,
    ).select_related('published_version')
    for template in templates.iterator():
        layout = deepcopy(template.published_version.layout)
        changed = (
            _clean_kitchen_layout(layout)
            if template.kind == 'kitchen_ticket'
            else _reorder_payment_totals(layout)
        )
        if changed:
            _publish_updated_layout(PrintTemplateVersion, template, layout)

    prechecks = PrintTemplate.objects.filter(
        kind='order_precheck',
        published_version__isnull=False,
    ).select_related('published_version')
    for template in prechecks.iterator():
        previous = template.published_version
        previous.status = 'retired'
        previous.save(update_fields=('status', 'updated_at'))
        template.published_version = None
        template.save(update_fields=('published_version', 'updated_at'))


class Migration(migrations.Migration):
    dependencies = [('printing', '0009_expand_print_idempotency_keys')]

    operations = [
        migrations.RunPython(unify_receipt_templates, migrations.RunPython.noop),
    ]
