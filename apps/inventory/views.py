import csv
from datetime import datetime, time, timedelta
from decimal import Decimal
import io
import re
from pathlib import Path

from django.utils.translation import gettext as _
from django.db import IntegrityError, transaction
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import CatalogItem
from apps.restaurants.models import Restaurant
from common.api.admin_permissions import AdminPermissionRequiredMixin
from common.api.permissions import has_permission_code, require_any_permission_code
from common.api.scopes import get_request_restaurant
from . import reports, services
from .models import InventoryAttachment, InventoryItem, Recipe, StockDocument, Supplier, Warehouse
from .serializers import (COST_FIELDS, PRIVATE_DOCUMENT_FIELDS, DocumentInputSerializer, DocumentSerializer, ItemSerializer,
                          RecipeInputSerializer, RecipeSerializer, SupplierSerializer, WarehouseSerializer,
                          redact_costs)


class InventoryView(AdminPermissionRequiredMixin, APIView):
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.restaurant = get_request_restaurant(request)
        require_any_permission_code(request.user, 'admin.inventory.view')
        self.can_view_cost = has_permission_code(request.user, 'admin.inventory.view_cost')

    def response(self, data, status=200):
        if not self.can_view_cost and isinstance(data, dict) and data.get('mode') == 'rules':
            data = {**data, 'items': [row for row in data.get('items', []) if not row['id'].startswith('price:')]}
        return Response(redact_costs(data, self.can_view_cost), status=status)

    def serializer_context(self):
        return {'request': self.request, 'restaurant': self.restaurant}

    def manage(self):
        require_any_permission_code(self.request.user, 'admin.inventory.manage')

    def cost_input(self, data):
        if self.can_view_cost:
            return
        if isinstance(data, dict):
            for field, value in data.items():
                if field in COST_FIELDS and value not in (None, '', 0, '0', '0.00', '0.000000'):
                    raise PermissionDenied(_('Tannarx kiritish uchun tannarxni ko‘rish ruxsati kerak.'))
                self.cost_input(value)
        elif isinstance(data, list):
            for value in data:
                self.cost_input(value)

    def warehouse(self):
        value = self.request.query_params.get('warehouse')
        return services.scoped(Warehouse, self.restaurant, value, 'warehouse') if value else None

    def dates(self):
        result = []
        for key in ('from', 'to'):
            value = self.request.query_params.get(key)
            parsed = None
            if value:
                try:
                    day = parse_date(value)
                except ValueError:
                    day = None
                if not day:
                    raise ValidationError({key: _('YYYY-MM-DD formatida sana kiriting.')})
                if key == 'to':
                    day += timedelta(days=1)
                parsed = timezone.make_aware(datetime.combine(day, time.min))
            result.append(parsed)
        if all(result) and result[0] >= result[1]:
            raise ValidationError(_('Davr boshlanishi tugashidan keyin bo‘lmasin.'))
        return result

    def page(self):
        try:
            limit = min(1000, max(1, int(self.request.query_params.get('limit', 200))))
            offset = max(0, int(self.request.query_params.get('offset', 0)))
        except (ValueError, TypeError):
            raise ValidationError(_('limit va offset butun son bo‘lishi kerak.'))
        return limit, offset


class ReferencesView(InventoryView):
    model = InventoryItem
    serializer_class = ItemSerializer

    def get(self, request, pk=None):
        if self.model is Warehouse:
            services.default_warehouse(self.restaurant)
        queryset = self.model.objects.filter(restaurant=self.restaurant)
        if pk:
            obj = get_object_or_404(queryset, pk=pk)
            return self.response(self.serializer_class(obj).data)
        search = request.query_params.get('search', '').strip()
        if search:
            queryset = queryset.filter(name__icontains=search)
        return self.response(self.serializer_class(queryset, many=True).data)

    def write(self, request, pk=None):
        self.manage()
        self.cost_input(request.data)
        with transaction.atomic():
            Restaurant.objects.select_for_update().get(pk=self.restaurant.pk)
            instance = get_object_or_404(self.model.objects.filter(restaurant=self.restaurant), pk=pk) if pk else None
            serializer = self.serializer_class(instance, data=request.data, partial=bool(pk), context=self.serializer_context())
            serializer.is_valid(raise_exception=True)
            if self.model is Warehouse and serializer.validated_data.get('is_default'):
                Warehouse.objects.filter(restaurant=self.restaurant, is_default=True).update(is_default=False)
            try:
                instance = serializer.save(restaurant=self.restaurant)
            except IntegrityError:
                raise ValidationError(_('Bu nom yoki kod allaqachon mavjud.'))
        return self.response(self.serializer_class(instance).data, 200 if pk else 201)


class ItemsView(ReferencesView):
    pass


class ItemsListView(ItemsView):
    post = ReferencesView.write


class ItemsDetailView(ItemsView):
    patch = ReferencesView.write


class WarehousesView(ReferencesView):
    model, serializer_class = Warehouse, WarehouseSerializer


class WarehousesListView(WarehousesView):
    post = ReferencesView.write


class WarehousesDetailView(WarehousesView):
    patch = ReferencesView.write


class SuppliersView(ReferencesView):
    model, serializer_class = Supplier, SupplierSerializer


class SuppliersListView(SuppliersView):
    post = ReferencesView.write


class SuppliersDetailView(SuppliersView):
    patch = ReferencesView.write


class CatalogOptionsView(InventoryView):
    def get(self, request):
        queryset = CatalogItem.objects.filter(restaurant=self.restaurant, item_type='product', is_active=True,
                                              archived_at__isnull=True).select_related('category').prefetch_related('modifier_groups__options')
        return self.response([{'id': str(item.pk), 'name': item.name, 'sale_unit': item.sale_unit,
            'category_id': str(item.category_id) if item.category_id and item.category.restaurant_id == self.restaurant.pk else None,
            'category_name': item.category.name if item.category_id and item.category.restaurant_id == self.restaurant.pk else '',
            'modifier_options': [{'id': str(option.pk), 'name': option.name, 'group_name': group.name}
                                 for group in item.modifier_groups.all() if group.is_active
                                 for option in group.options.all() if option.is_active]} for item in queryset])


class RecipesView(InventoryView):
    def get(self, request, pk=None):
        queryset = Recipe.objects.filter(restaurant=self.restaurant).select_related('catalog_item').prefetch_related('lines__item', 'lines__modifier_option')
        if pk:
            return self.response(RecipeSerializer(get_object_or_404(queryset, pk=pk)).data)
        if request.query_params.get('catalogItem') or request.query_params.get('catalog_item'):
            catalog_id = request.query_params.get('catalogItem') or request.query_params.get('catalog_item')
            catalog = services.scoped(CatalogItem, self.restaurant, catalog_id, 'catalogItem')
            queryset = queryset.filter(catalog_item=catalog)
        else:
            queryset = queryset.filter(is_active=True)
        return self.response(RecipeSerializer(queryset, many=True).data)

    def create_recipe(self, request):
        self.manage()
        serializer = RecipeInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        recipe = services.create_recipe(self.restaurant, serializer.validated_data, request.user)
        return self.response(RecipeSerializer(recipe).data, 201)

    def update_recipe(self, request, pk):
        self.manage()
        if dict(request.data) != {'is_active': False}:
            raise ValidationError(_('Retsept o‘zgarishi uchun yangi versiya yarating. Faqat isActive:false mumkin.'))
        with transaction.atomic():
            recipe = get_object_or_404(Recipe.objects.select_for_update().filter(restaurant=self.restaurant), pk=pk)
            recipe.is_active = False
            recipe.save(update_fields=['is_active', 'updated_at'])
        return self.response(RecipeSerializer(recipe).data)


class RecipesListView(RecipesView):
    post = RecipesView.create_recipe


class RecipesDetailView(RecipesView):
    patch = RecipesView.update_recipe


class DocumentsView(InventoryView):
    def queryset(self):
        return StockDocument.objects.filter(restaurant=self.restaurant).select_related('warehouse', 'supplier').prefetch_related('lines')

    def get(self, request, pk=None):
        queryset = self.queryset()
        if pk:
            return self.response(DocumentSerializer(get_object_or_404(queryset, pk=pk)).data)
        for field in ('kind', 'status'):
            if request.query_params.get(field):
                queryset = queryset.filter(**{field: request.query_params[field]})
        warehouse = self.warehouse()
        if warehouse:
            queryset = queryset.filter(warehouse=warehouse)
        search = request.query_params.get('search', '')
        if search:
            from django.db.models import Q
            queryset = queryset.filter(Q(number__icontains=search) | Q(reference__icontains=search) | Q(reason__icontains=search))
        limit, offset = self.page()
        return self.response(DocumentSerializer(queryset[offset:offset + limit], many=True).data)

    def create_document(self, request):
        self.manage()
        self.cost_input(request.data)
        serializer = DocumentInputSerializer(data=request.data, context=self.serializer_context())
        serializer.is_valid(raise_exception=True)
        document = services.create_document(self.restaurant, serializer.validated_data, request.user)
        return self.response(DocumentSerializer(document).data, 201)

    def update_document(self, request, pk):
        self.manage()
        document = get_object_or_404(self.queryset(), pk=pk)
        data = request.data.copy()
        if not self.can_view_cost and data.get('attachment_url') in (None, '', document.attachment_url):
            # A hidden attachment is represented as null/blank by the editor;
            # saving unrelated draft fields must not erase the original invoice.
            data.pop('attachment_url', None)
        self.cost_input(data)
        serializer = DocumentInputSerializer(data=data, partial=True, context=self.serializer_context())
        serializer.is_valid(raise_exception=True)
        document = services.update_document(document, serializer.validated_data)
        return self.response(DocumentSerializer(document).data)


class DocumentsListView(DocumentsView):
    post = DocumentsView.create_document


class DocumentsDetailView(DocumentsView):
    patch = DocumentsView.update_document


class PostDocumentView(InventoryView):
    http_method_names = ['post', 'options']
    queryset = DocumentsView.queryset
    def post(self, request, pk):
        require_any_permission_code(request.user, 'admin.inventory.post')
        document = get_object_or_404(self.queryset(), pk=pk)
        allow_negative = request.data.get('allow_negative', False)
        if not isinstance(allow_negative, bool):
            raise ValidationError({'allowNegative': _('Mantiqiy qiymat kerak.')})
        document = services.post_document(document, request.user, allow_negative=allow_negative)
        return self.response(DocumentSerializer(document).data)


class ReverseDocumentView(InventoryView):
    http_method_names = ['post', 'options']
    queryset = DocumentsView.queryset
    def post(self, request, pk):
        require_any_permission_code(request.user, 'admin.inventory.post')
        document = get_object_or_404(self.queryset(), pk=pk)
        reason = request.data.get('reason', '')
        if not isinstance(reason, str) or len(reason) > 500:
            raise ValidationError({'reason': _('Sabab 500 belgidan oshmasin.')})
        document = services.reverse_document(document, reason, request.user)
        return self.response(DocumentSerializer(document).data)


class ReportView(InventoryView):
    report = 'balances'

    def result(self):
        warehouse = self.warehouse()
        start, end = self.dates()
        if self.report == 'balances':
            return reports.balances(self.restaurant, warehouse)
        if self.report == 'movements':
            item = services.scoped(InventoryItem, self.restaurant, self.request.query_params['item'], 'item') if self.request.query_params.get('item') else None
            limit, offset = self.page()
            return reports.movements(self.restaurant, warehouse, start, end, item,
                                     self.request.query_params.get('kind'), limit, offset)
        if self.report == 'variance':
            return reports.variance(self.restaurant, warehouse, start, end)
        if self.report == 'overview':
            return reports.overview(self.restaurant, warehouse, start, end)
        return reports.insights(self.restaurant, warehouse)

    def get(self, request):
        result = self.result()
        if self.report == 'insights':
            # Root's optional provider service can advertise its configured state.
            try:
                from .ai import ai_available
                result['ai_available'] = bool(ai_available())
            except ImportError:
                pass
        return self.response(result)


def csv_response(rows, filename, can_view_cost=True, metadata=None):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)

    def safe(value):
        if value is None:
            return ''
        text = str(value)
        numeric = isinstance(value, (int, float, Decimal)) or bool(re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)', text))
        return "'" + text if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) and not numeric else text

    if metadata:
        for key, value in metadata.items():
            if can_view_cost or key not in COST_FIELDS | PRIVATE_DOCUMENT_FIELDS:
                writer.writerow([key, safe(value)])
        writer.writerow([])
    if rows:
        fields = [key for key in rows[0] if can_view_cost or key not in COST_FIELDS | PRIVATE_DOCUMENT_FIELDS]
        writer.writerow(fields)
        for row in rows:
            writer.writerow([safe(row.get(key)) for key in fields])
    response = HttpResponse('\ufeff' + stream.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['Cache-Control'] = 'private, no-store'
    return response


class ExportView(ReportView):
    def get(self, request):
        self.report = request.query_params.get('report', 'balances')
        if self.report not in {'balances', 'movements', 'variance'}:
            raise ValidationError({'report': _('balances, movements yoki variance tanlang.')})
        if self.report == 'movements':
            start, end = self.dates()
            rows = reports.movements(self.restaurant, self.warehouse(), start, end, limit=None)
        else:
            rows = self.result()
        return csv_response(rows, f'inventory-{self.report}.csv', self.can_view_cost,
                             {'restaurant': self.restaurant.name, 'generated_at': timezone.now().isoformat(),
                              'note': 'Operatsion ombor hisobi; elektron raqamli imzo emas.'})


class DocumentExportView(InventoryView):
    http_method_names = ['get', 'head', 'options']
    queryset = DocumentsView.queryset
    def get(self, request, pk):
        document = get_object_or_404(self.queryset(), pk=pk)
        data = dict(DocumentSerializer(document).data)
        lines = data.pop('lines')
        data['restaurant_name'] = document.restaurant.name
        data['restaurant_legal_name'] = document.restaurant.legal_name
        data['restaurant_tax_number'] = document.restaurant.tax_number
        data['signature_note'] = 'Tizimdagi tasdiq ERI emas. Zarur imzolar korxona tartibiga muvofiq rasmiylashtiriladi.'
        return csv_response(lines, f'{document.number}.csv', self.can_view_cost, data)


class AttachmentsView(InventoryView):
    def post(self, request):
        self.manage()
        upload = request.FILES.get('file')
        if not upload or upload.size > 10 * 1024 * 1024:
            raise ValidationError({'file': _('10 MB gacha PDF, JPG yoki PNG yuklang.')})
        header = upload.read(16)
        upload.seek(0)
        if header.startswith(b'%PDF-'):
            content_type, extensions = 'application/pdf', {'.pdf'}
        elif header.startswith(b'\x89PNG\r\n\x1a\n'):
            content_type, extensions = 'image/png', {'.png'}
        elif header.startswith(b'\xff\xd8\xff'):
            content_type, extensions = 'image/jpeg', {'.jpg', '.jpeg'}
        else:
            raise ValidationError({'file': _('Fayl turi PDF, JPG yoki PNG bo‘lishi kerak.')})
        if Path(upload.name).suffix.lower() not in extensions:
            raise ValidationError({'file': _('Fayl kengaytmasi tarkibiga mos emas.')})
        attachment = InventoryAttachment.objects.create(restaurant=self.restaurant, file=upload,
                       name=Path(upload.name).name[:255], content_type=content_type, created_by=request.user)
        return self.response({'id': str(attachment.pk), 'name': attachment.name,
             'url': request.build_absolute_uri(f'/api/v1/admin/inventory/attachments/{attachment.pk}/download/')}, 201)


class AttachmentDownloadView(InventoryView):
    def get(self, request, pk):
        require_any_permission_code(request.user, 'admin.inventory.view_cost')
        attachment = get_object_or_404(InventoryAttachment, restaurant=self.restaurant, pk=pk)
        response = FileResponse(attachment.file.open('rb'), content_type=attachment.content_type,
                                as_attachment=True, filename=attachment.name)
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response
