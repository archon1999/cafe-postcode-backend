from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.local_agents.authentication import authenticate_local_agent
from apps.printing.models import PrintDocument, PrintTemplate
from apps.restaurants.models import CashDesk, PrepStation
from common.utils.settings import coerce_bool, coerce_int, get_setting


def _cash_desk_for_document(document: PrintDocument):
    cash_desk_id = (document.metadata or {}).get('cashDeskId')
    if cash_desk_id:
        return (
            CashDesk.objects.select_related('printer_integration')
            .filter(id=cash_desk_id, restaurant=document.restaurant, is_active=True)
            .first()
        )

    if document.source_model == 'billing.receipt' and document.source_id:
        from apps.billing.models import Receipt

        receipt = (
            Receipt.objects.select_related('payment__cash_desk__printer_integration')
            .filter(id=document.source_id, order__restaurant=document.restaurant)
            .first()
        )
        return receipt.payment.cash_desk if receipt and receipt.payment_id else None
    return None


def _printer_route(document: PrintDocument) -> dict:
    cash_desk = None
    prep_station = None
    if document.kind == PrintTemplate.Kind.KITCHEN_TICKET:
        prep_station_id = (document.metadata or {}).get('prepStationId')
        if prep_station_id:
            prep_station = (
                PrepStation.objects.select_related('printer_integration')
                .filter(id=prep_station_id, restaurant=document.restaurant, is_active=True)
                .first()
            )
        integration = prep_station.printer_integration if prep_station else None
    else:
        cash_desk = _cash_desk_for_document(document)
        integration = cash_desk.printer_integration if cash_desk else None
    if integration is None or not integration.is_enabled:
        return {
            'cashDeskId': str(cash_desk.id) if cash_desk else None,
            'prepStationId': str(prep_station.id) if prep_station else None,
            'printerIntegrationId': None,
            'printer': None,
        }

    settings = dict(integration.settings or {})
    host = str(settings.get('host') or '').strip()
    connection_type = str(
        get_setting(
            settings,
            'connection_type',
            'connectionType',
            default='socket' if host else 'system_printer',
        )
    ).strip()
    code_page = get_setting(settings, 'code_page', 'codePage')
    return {
        'cashDeskId': str(cash_desk.id) if cash_desk else None,
        'prepStationId': str(prep_station.id) if prep_station else None,
        'printerIntegrationId': str(integration.id),
        'printer': {
            'provider': integration.provider,
            'connectionType': connection_type,
            'printerName': str(get_setting(settings, 'printer_name', 'printerName', default='')).strip(),
            'host': host,
            'port': coerce_int(settings.get('port'), default=9100, minimum=1, maximum=65535),
            'encoding': str(settings.get('encoding') or settings.get('charset') or 'cp1251').strip(),
            'codePage': coerce_int(code_page, default=46, minimum=0, maximum=255) if code_page is not None else None,
            'escposEnabled': coerce_bool(
                get_setting(settings, 'escpos_enabled', 'escposEnabled'),
                default=True,
            ),
            'cutAfterPrint': coerce_bool(
                get_setting(settings, 'cut_after_print', 'cutAfterPrint'),
                default=True,
            ),
            'feedLinesBeforeCut': coerce_int(
                get_setting(settings, 'feed_lines_before_cut', 'feedLinesBeforeCut'),
                default=5,
                minimum=0,
                maximum=10,
            ),
        },
    }


class LocalAgentPrintDocumentView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, document_id):
        agent = authenticate_local_agent(request)
        if agent is None:
            return Response({'detail': 'Invalid local agent token.'}, status=status.HTTP_401_UNAUTHORIZED)

        document = (
            PrintDocument.objects.select_related('template_version')
            .filter(id=document_id, restaurant=agent.restaurant)
            .first()
        )
        if document is None:
            return Response({'detail': 'Print document not found.'}, status=status.HTTP_404_NOT_FOUND)

        version = document.template_version
        return Response(
            {
                'id': str(document.id),
                'kind': document.kind,
                'operationType': document.operation_type,
                'contentHash': document.content_hash,
                'dataSnapshot': document.data_snapshot,
                'templateVersion': {
                    'id': str(version.id),
                    'revision': version.revision,
                    'schemaVersion': version.schema_version,
                    'layout': version.layout,
                },
                'route': _printer_route(document),
            }
        )
