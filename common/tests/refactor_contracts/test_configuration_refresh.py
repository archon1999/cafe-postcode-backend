from copy import deepcopy

from rest_framework import status

from apps.local_agents.models import LocalAgent
from apps.printing.models import PrintTemplate
from apps.printing.services.templates import create_template_version, publish_template_version
from apps.sales.tests.support.pos_api import PosTestCase


class BackendConfigurationRefreshScenarioTests(PosTestCase):
    def setUp(self):
        super().setUp()
        _agent, self.agent_token = LocalAgent.issue_for_restaurant(
            restaurant=self.restaurant,
            name="Configuration characterization agent",
        )

    def bootstrap(self):
        response = self.client.get(
            "/api/v1/local-agent/sync/bootstrap/",
            HTTP_AUTHORIZATION=f"Bearer {self.agent_token}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data

    @staticmethod
    def plain_template(bootstrap):
        return next(
            template
            for template in bootstrap["printTemplates"]
            if template["kind"] == PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN
        )

    def test_restaurant_changes_are_immediate_but_draft_template_waits_for_publish(self):
        initial = self.bootstrap()
        initial_template = self.plain_template(initial)
        template = PrintTemplate.objects.select_related("published_version").get(
            restaurant=self.restaurant,
            kind=PrintTemplate.Kind.PAYMENT_RECEIPT_PLAIN,
        )
        initial_version_id = str(template.published_version_id)
        self.assertEqual(initial_template["version"]["id"], initial_version_id)
        self.assertEqual(initial_template["version"]["revision"], 1)

        draft_layout = deepcopy(template.published_version.layout)
        marker = "CONFIG-REFRESH-CHARACTERIZATION"
        draft_layout["blocks"][0]["text"] = marker
        draft = create_template_version(
            template=template,
            layout=draft_layout,
            created_by=self.user,
        )
        self.restaurant.name = "Qamish Refresh"
        self.restaurant.phone = "+998 90 777 77 77"
        self.restaurant.social = "@qamish-refresh"
        self.restaurant.address = "Refresh ko'chasi 15"
        self.restaurant.service_fee_enabled = True
        self.restaurant.service_fee_percent = 15
        self.restaurant.vat_enabled = True
        self.restaurant.vat_percent = 12
        self.restaurant.marking_check_enabled = True
        self.restaurant.payment_total_mode = self.restaurant.PaymentTotalMode.CASHIER_EDITABLE
        self.restaurant.save(
            update_fields=[
                "name",
                "phone",
                "social",
                "address",
                "service_fee_enabled",
                "service_fee_percent",
                "vat_enabled",
                "vat_percent",
                "marking_check_enabled",
                "payment_total_mode",
                "updated_at",
            ]
        )

        before_publish = self.bootstrap()
        self.assertEqual(
            before_publish["restaurant"],
            {
                "restaurant_id": str(self.restaurant.id),
                "restaurant_name": "Qamish Refresh",
                "phone": "+998 90 777 77 77",
                "social": "@qamish-refresh",
                "address": "Refresh ko'chasi 15",
                "pos_auth_background_image_url": None,
                "service_fee_enabled": True,
                "service_fee_percent": "15.00",
                "vat_enabled": True,
                "vat_percent": "12.00",
                "marking_check_enabled": True,
                "pos_monitor_variant": "default",
                "payment_total_mode": "cashier_editable",
            },
        )
        before_publish_template = self.plain_template(before_publish)
        self.assertEqual(before_publish_template["version"]["id"], initial_version_id)
        self.assertEqual(before_publish_template["version"]["revision"], 1)
        self.assertNotIn(marker, str(before_publish_template["version"]["layout"]))

        publish_template_version(template=template, version=draft)

        after_publish = self.bootstrap()
        after_publish_template = self.plain_template(after_publish)
        self.assertEqual(after_publish_template["version"]["id"], str(draft.id))
        self.assertEqual(after_publish_template["version"]["revision"], 2)
        self.assertEqual(after_publish_template["version"]["schemaVersion"], 1)
        self.assertEqual(after_publish_template["version"]["layout"], draft_layout)
        self.assertIn(marker, str(after_publish_template["version"]["layout"]))
