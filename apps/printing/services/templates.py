from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.printing.models import PrintTemplate, PrintTemplateVersion
from apps.printing.presets import PRINT_KINDS, get_preset_layout, get_shift_report_layout

from .validation import validate_template_layout


DEFAULT_PRESET_KEY = 'legacy_80'
SHIFT_REPORT_PRESET_KEY = 'internal_shift_report_80'


def _shift_report_layout_is_current(layout: dict) -> bool:
    values = {
        row.get('value')
        for block in layout.get('blocks', [])
        for row in block.get('rows', [])
    }
    return {
        '{{report.expenseTotal}}',
        '{{report.cashPrecheckSale}}',
        '{{report.cashReceiptSale}}',
        '{{report.cardPrecheckSale}}',
        '{{report.cardReceiptSale}}',
    }.issubset(values)


@transaction.atomic
def ensure_restaurant_templates(*, restaurant) -> list[PrintTemplate]:
    templates: list[PrintTemplate] = []
    for kind in PRINT_KINDS:
        template, _created = PrintTemplate.objects.get_or_create(restaurant=restaurant, kind=kind)
        if template.published_version_id is None:
            layout = get_preset_layout(DEFAULT_PRESET_KEY, kind)
            version = PrintTemplateVersion.objects.create(
                template=template,
                revision=1,
                schema_version=1,
                status=PrintTemplateVersion.Status.PUBLISHED,
                preset_key=DEFAULT_PRESET_KEY,
                layout=layout,
                published_at=timezone.now(),
            )
            template.published_version = version
            template.save(update_fields=('published_version', 'updated_at'))
        templates.append(template)
    return templates


@transaction.atomic
def ensure_shift_report_template(*, restaurant) -> PrintTemplate:
    template, _created = PrintTemplate.objects.get_or_create(
        restaurant=restaurant,
        kind=PrintTemplate.Kind.SHIFT_REPORT,
    )
    if template.published_version_id is None:
        version = PrintTemplateVersion.objects.create(
            template=template,
            revision=1,
            schema_version=1,
            status=PrintTemplateVersion.Status.PUBLISHED,
            preset_key=SHIFT_REPORT_PRESET_KEY,
            layout=get_shift_report_layout(),
            published_at=timezone.now(),
        )
        template.published_version = version
        template.save(update_fields=('published_version', 'updated_at'))
    elif (
        template.published_version.preset_key == SHIFT_REPORT_PRESET_KEY
        and not _shift_report_layout_is_current(template.published_version.layout)
    ):
        template.versions.filter(status=PrintTemplateVersion.Status.PUBLISHED).update(
            status=PrintTemplateVersion.Status.RETIRED,
            updated_at=timezone.now(),
        )
        revision = (template.versions.aggregate(value=Max('revision'))['value'] or 0) + 1
        version = PrintTemplateVersion.objects.create(
            template=template,
            revision=revision,
            schema_version=1,
            status=PrintTemplateVersion.Status.PUBLISHED,
            preset_key=SHIFT_REPORT_PRESET_KEY,
            layout=get_shift_report_layout(),
            published_at=timezone.now(),
        )
        template.published_version = version
        template.save(update_fields=('published_version', 'updated_at'))
    return template


@transaction.atomic
def create_template_version(*, template: PrintTemplate, layout: dict | None, preset_key: str = '', created_by=None):
    locked_template = PrintTemplate.objects.select_for_update().get(pk=template.pk)
    if layout is None:
        if not preset_key:
            raise ValueError('Either layout or preset_key is required.')
        layout = get_preset_layout(preset_key, locked_template.kind)
    validate_template_layout(kind=locked_template.kind, layout=layout)
    next_revision = (locked_template.versions.aggregate(value=Max('revision'))['value'] or 0) + 1
    return PrintTemplateVersion.objects.create(
        template=locked_template,
        revision=next_revision,
        schema_version=int(layout.get('schemaVersion') or 1),
        status=PrintTemplateVersion.Status.DRAFT,
        preset_key=preset_key,
        layout=layout,
        created_by=created_by,
    )


@transaction.atomic
def publish_template_version(*, template: PrintTemplate, version: PrintTemplateVersion):
    locked_template = PrintTemplate.objects.select_for_update().get(pk=template.pk)
    locked_version = PrintTemplateVersion.objects.select_for_update().get(pk=version.pk, template=locked_template)
    validate_template_layout(kind=locked_template.kind, layout=locked_version.layout)

    if locked_template.published_version_id == locked_version.id:
        return locked_version

    locked_template.versions.filter(status=PrintTemplateVersion.Status.PUBLISHED).exclude(pk=locked_version.pk).update(
        status=PrintTemplateVersion.Status.RETIRED,
        updated_at=timezone.now(),
    )
    locked_version.status = PrintTemplateVersion.Status.PUBLISHED
    locked_version.published_at = timezone.now()
    locked_version.save(update_fields=('status', 'published_at', 'updated_at'))
    locked_template.published_version = locked_version
    locked_template.save(update_fields=('published_version', 'updated_at'))
    return locked_version
