from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.local_agents.models import LocalAgent, LocalAgentCommand
from apps.restaurants.models import Restaurant
from apps.users.models import User


class BackendLocalAgentDiagnosticsCharacterizationTests(APITestCase):
    def setUp(self):
        self.restaurant = Restaurant.objects.create(name="Qamish diagnostics", auth_code="DIA001")
        self.other_restaurant = Restaurant.objects.create(name="Other diagnostics", auth_code="DIA002")
        self.agent, _ = LocalAgent.issue_for_restaurant(
            restaurant=self.restaurant,
            name="Qamish coordinator",
            version="0.7.9",
        )
        self.agent.status = LocalAgent.Status.OFFLINE
        self.agent.last_seen_at = timezone.now()
        self.agent.save(update_fields=["status", "last_seen_at", "updated_at"])
        other_agent, _ = LocalAgent.issue_for_restaurant(
            restaurant=self.other_restaurant,
            name="Other coordinator",
            version="9.9.9",
        )
        other_agent.status = LocalAgent.Status.ONLINE
        other_agent.last_seen_at = timezone.now()
        other_agent.save(update_fields=["status", "last_seen_at", "updated_at"])

        self.user = User.objects.create_superuser(
            username="diagnostics-characterization",
            password="Strong-Diagnostics-123!",
            full_name="Diagnostics Characterization",
        )
        self.client.force_authenticate(self.user)
        self.headers = {"HTTP_X_ADMIN_RESTAURANT_ID": str(self.restaurant.id)}

    def test_remote_pos_offline_snapshot_is_explicit_and_restaurant_scoped(self):
        response = self.client.get("/api/v1/system/status/", **self.headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        snapshot = response.data["status"]
        self.assertEqual(
            snapshot["agent"],
            {
                "online": False,
                "version": "0.7.9",
                "restaurantId": str(self.restaurant.id),
            },
        )
        self.assertEqual(snapshot["backend"], {"online": True, "offlineMode": False})
        self.assertEqual(snapshot["alerts"][0]["code"], "LOCAL_AGENT_OFFLINE")
        self.assertEqual(snapshot["fiscal"]["state"], "unknown")
        self.assertEqual(snapshot["marta"]["state"], "unknown")
        self.assertEqual(snapshot["printer"]["state"], "unknown")
        self.assertFalse(
            LocalAgentCommand.objects.filter(
                agent=self.agent,
                command_type="system.status",
            ).exists()
        )

    def test_remote_pos_diagnostics_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.get("/api/v1/system/status/", **self.headers)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
