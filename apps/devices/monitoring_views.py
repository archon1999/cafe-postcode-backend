from datetime import datetime, time, timedelta

from django.db.models import Count, Max, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.models import CashShift
from apps.devices.models import Device, DevicePairing, SecurityEvent
from apps.local_agents.models import LocalAgent
from apps.platform.api.admin.permissions import PlatformAccountPermission
from apps.restaurants.models import Restaurant
from apps.sales.models import Order
from apps.telegram_reports.models import TelegramBranchSubscription
from common.api.admin_permissions import ADMIN_PERMISSION_CLASSES


ACTIVE_SECURITY_RISK_WINDOW = timedelta(hours=24)
BRANCH_ACTIVITY_STALE_WINDOW = timedelta(hours=24)
AGENT_OFFLINE_ACTIVITY_GRACE = timedelta(minutes=2)
AGENT_OFFLINE_RISK_LOOKBACK = timedelta(minutes=30)
AGENT_OFFLINE_RISK_SETTLE_WINDOW = timedelta(minutes=2)


def _agent_offline_assessment(
    *,
    agent,
    agent_is_online,
    device_status,
    open_cash_shifts,
    last_order_at,
    recent_risk_event_count,
):
    if agent_is_online:
        return {"expected": False, "reason": "online", "recentRiskEventCount": 0}
    if agent is None or agent.last_seen_at is None:
        return {
            "expected": False,
            "reason": "last_seen_missing",
            "recentRiskEventCount": recent_risk_event_count,
        }
    if not agent.is_active or device_status != Device.Status.ACTIVE:
        return {
            "expected": False,
            "reason": "agent_inactive",
            "recentRiskEventCount": recent_risk_event_count,
        }
    if recent_risk_event_count:
        return {
            "expected": False,
            "reason": "risk_before_offline",
            "recentRiskEventCount": recent_risk_event_count,
        }
    if open_cash_shifts:
        return {
            "expected": False,
            "reason": "open_cash_shift",
            "recentRiskEventCount": 0,
        }
    if (
        last_order_at
        and last_order_at > agent.last_seen_at + AGENT_OFFLINE_ACTIVITY_GRACE
    ):
        return {
            "expected": False,
            "reason": "orders_after_offline",
            "recentRiskEventCount": 0,
        }
    return {
        "expected": True,
        "reason": "natural_inactivity",
        "recentRiskEventCount": 0,
    }


def _branch_health_priority(branch, *, now):
    agent = branch["agent"]
    devices = branch["devices"]
    security = branch["security"]
    critical = security["unacknowledgedCritical"] > 0 or (
        agent is not None and agent["deviceStatus"] != Device.Status.ACTIVE
    )
    if critical:
        return 2

    last_seen_at = devices["lastSeenAt"]
    attention = (
        security["unacknowledgedHigh"] > 0
        or agent is None
        or (not agent["online"] and not agent["expectedOffline"])
        or devices["activePOS"] == 0
        or last_seen_at is None
        or (
            not (agent and agent["expectedOffline"])
            and now - datetime.fromisoformat(last_seen_at)
            > BRANCH_ACTIVITY_STALE_WINDOW
        )
    )
    return 1 if attention else 0


class MonitoringOverviewView(APIView):
    """Return a read-only, database-backed operational fleet snapshot."""

    permission_classes = [*ADMIN_PERMISSION_CLASSES, PlatformAccountPermission]

    def get(self, request):
        now = timezone.now()
        active_security_risk_cutoff = now - ACTIVE_SECURITY_RISK_WINDOW
        business_partner_id = str(
            request.query_params.get("business_partner_id")
            or request.query_params.get("businessPartnerId")
            or ""
        ).strip()
        device_online_cutoff = now - timedelta(minutes=5)
        current_timezone = timezone.get_current_timezone()
        today = timezone.localdate(now, current_timezone)
        activity_start_date = today - timedelta(days=6)
        activity_end_date = today + timedelta(days=1)
        activity_start = timezone.make_aware(
            datetime.combine(activity_start_date, time.min),
            current_timezone,
        )
        activity_end = timezone.make_aware(
            datetime.combine(activity_end_date, time.min),
            current_timezone,
        )
        branch_queryset = Restaurant.objects.filter(is_active=True)
        if business_partner_id:
            branch_queryset = branch_queryset.filter(
                business_partner_id=business_partner_id
            )
        branches = list(
            branch_queryset.select_related(
                "local_agent", "local_agent__device"
            ).order_by("name", "id")
        )
        restaurant_ids = [restaurant.id for restaurant in branches]
        scoped_security_events = SecurityEvent.objects.all()
        scoped_pending_pairings = DevicePairing.objects.all()
        if business_partner_id:
            scoped_security_events = scoped_security_events.filter(
                restaurant_id__in=restaurant_ids
            )
            scoped_pending_pairings = scoped_pending_pairings.filter(
                device__restaurant_id__in=restaurant_ids
            )
        device_aggregates = {
            row["restaurant_id"]: row
            for row in Device.objects.filter(restaurant_id__in=restaurant_ids)
            .values("restaurant_id")
            .annotate(
                active=Count("id", filter=Q(status=Device.Status.ACTIVE)),
                online=Count(
                    "id",
                    filter=Q(
                        status=Device.Status.ACTIVE,
                        last_seen_at__gte=device_online_cutoff,
                    ),
                ),
                revoked=Count("id", filter=Q(status=Device.Status.REVOKED)),
                active_local_agent=Count(
                    "id",
                    filter=Q(status=Device.Status.ACTIVE, type=Device.Type.LOCAL_AGENT),
                ),
                active_pos=Count(
                    "id",
                    filter=Q(
                        status=Device.Status.ACTIVE, type=Device.Type.POS_TERMINAL
                    ),
                ),
                active_tv=Count(
                    "id",
                    filter=Q(status=Device.Status.ACTIVE, type=Device.Type.TV_MONITOR),
                ),
                active_control=Count(
                    "id",
                    filter=Q(
                        status=Device.Status.ACTIVE, type=Device.Type.CONTROL_DEVICE
                    ),
                ),
                last_seen_at=Max(
                    "last_seen_at",
                    filter=Q(status=Device.Status.ACTIVE),
                ),
            )
        }
        open_cash_shift_counts = {
            row["cash_desk__restaurant_id"]: row["total"]
            for row in CashShift.objects.filter(
                cash_desk__restaurant_id__in=restaurant_ids,
                status=CashShift.Status.OPEN,
            )
            .values("cash_desk__restaurant_id")
            .annotate(total=Count("id"))
        }
        last_order_activity = {
            row["restaurant_id"]: row["last_order_at"]
            for row in Order.objects.filter(restaurant_id__in=restaurant_ids)
            .values("restaurant_id")
            .annotate(last_order_at=Max("created_at"))
        }
        telegram_subscription_counts = {
            row["restaurant_id"]: row["total"]
            for row in TelegramBranchSubscription.objects.filter(
                restaurant_id__in=restaurant_ids,
            )
            .values("restaurant_id")
            .annotate(total=Count("id"))
        }
        security_aggregates = {
            row["restaurant_id"]: row
            for row in SecurityEvent.objects.filter(
                restaurant_id__in=restaurant_ids,
                created_at__gte=active_security_risk_cutoff,
            )
            .values("restaurant_id")
            .annotate(
                unacknowledged_high=Count(
                    "id",
                    filter=Q(
                        severity=SecurityEvent.Severity.HIGH,
                        acknowledged_at__isnull=True,
                    ),
                ),
                unacknowledged_critical=Count(
                    "id",
                    filter=Q(
                        severity=SecurityEvent.Severity.CRITICAL,
                        acknowledged_at__isnull=True,
                    ),
                ),
                last_event_at=Max("created_at"),
            )
        }
        security_activity = {
            activity_date: {
                "date": activity_date.isoformat(),
                "high": 0,
                "critical": 0,
            }
            for activity_date in (
                activity_start_date + timedelta(days=offset) for offset in range(7)
            )
        }
        security_activity_rows = (
            scoped_security_events.filter(
                created_at__gte=activity_start,
                created_at__lt=activity_end,
                severity__in=(
                    SecurityEvent.Severity.HIGH,
                    SecurityEvent.Severity.CRITICAL,
                ),
            )
            .annotate(activity_date=TruncDate("created_at", tzinfo=current_timezone))
            .values("activity_date")
            .annotate(
                high=Count("id", filter=Q(severity=SecurityEvent.Severity.HIGH)),
                critical=Count(
                    "id", filter=Q(severity=SecurityEvent.Severity.CRITICAL)
                ),
            )
            .order_by("activity_date")
        )
        for row in security_activity_rows:
            bucket = security_activity.get(row["activity_date"])
            if bucket is not None:
                bucket["high"] = row["high"]
                bucket["critical"] = row["critical"]

        global_security = scoped_security_events.filter(
            acknowledged_at__isnull=True,
            created_at__gte=active_security_risk_cutoff,
        ).aggregate(
            unacknowledged_high=Count(
                "id",
                filter=Q(severity=SecurityEvent.Severity.HIGH),
            ),
            unacknowledged_critical=Count(
                "id",
                filter=Q(severity=SecurityEvent.Severity.CRITICAL),
            ),
        )

        agent_online = 0
        agent_offline = 0
        agent_expected_offline = 0
        agent_attention_required = 0
        agent_missing = 0
        agent_versions = {}
        branch_payloads = []

        agents_by_device_id = {
            restaurant.local_agent.device_id: restaurant.local_agent
            for restaurant in branches
            if hasattr(restaurant, "local_agent")
            and restaurant.local_agent.device_id
            and restaurant.local_agent.last_seen_at
        }
        agent_risk_event_counts = {device_id: 0 for device_id in agents_by_device_id}
        if agents_by_device_id:
            exact_agent_risk_windows = Q()
            for device_id, agent in agents_by_device_id.items():
                exact_agent_risk_windows |= Q(
                    device_id=device_id,
                    created_at__gte=agent.last_seen_at - AGENT_OFFLINE_RISK_LOOKBACK,
                    created_at__lte=agent.last_seen_at
                    + AGENT_OFFLINE_RISK_SETTLE_WINDOW,
                )
            agent_risk_events = (
                SecurityEvent.objects.filter(
                    exact_agent_risk_windows,
                    severity__in=(
                        SecurityEvent.Severity.HIGH,
                        SecurityEvent.Severity.CRITICAL,
                    ),
                    result="DENIED",
                )
                .values("device_id")
                .annotate(total=Count("id"))
            )
            agent_risk_event_counts.update(
                {row["device_id"]: row["total"] for row in agent_risk_events}
            )

        for restaurant in branches:
            device_counts = device_aggregates.get(restaurant.id, {})
            security_counts = security_aggregates.get(restaurant.id, {})
            try:
                agent = restaurant.local_agent
            except LocalAgent.DoesNotExist:
                agent = None

            agent_payload = None
            agent_is_online = bool(agent and agent.is_active and agent.is_online())
            agent_device_status = (
                agent.device.status if agent and agent.device is not None else None
            )
            offline_assessment = _agent_offline_assessment(
                agent=agent,
                agent_is_online=agent_is_online,
                device_status=agent_device_status,
                open_cash_shifts=open_cash_shift_counts.get(restaurant.id, 0),
                last_order_at=last_order_activity.get(restaurant.id),
                recent_risk_event_count=(
                    agent_risk_event_counts.get(agent.device_id, 0)
                    if agent and agent.device_id
                    else 0
                ),
            )
            if agent is None or not agent.is_active:
                agent_missing += 1
            else:
                if agent_is_online:
                    agent_online += 1
                else:
                    agent_offline += 1
                    if offline_assessment["expected"]:
                        agent_expected_offline += 1
                    else:
                        agent_attention_required += 1

            if agent is not None:
                version = (agent.version or "").strip() or "unknown"
                version_counts = agent_versions.setdefault(
                    version,
                    {"version": version, "total": 0, "online": 0, "offline": 0},
                )
                version_counts["total"] += 1
                version_counts["online" if agent_is_online else "offline"] += 1
                device = agent.device
                agent_payload = {
                    "id": str(agent.id),
                    "name": agent.name,
                    "version": agent.version,
                    "lastSeenAt": agent.last_seen_at.isoformat()
                    if agent.last_seen_at
                    else None,
                    "online": agent_is_online,
                    "isActive": agent.is_active,
                    "protocolVersion": agent.protocol_version,
                    "deviceStatus": device.status if device is not None else None,
                    "expectedOffline": offline_assessment["expected"],
                    "offlineReason": offline_assessment["reason"],
                    "recentRiskEventCount": offline_assessment["recentRiskEventCount"],
                    "deviceLeaseExpiresAt": (
                        device.lease_expires_at.isoformat()
                        if device is not None
                        else None
                    ),
                    "capabilities": agent.capabilities,
                }

            branch_payloads.append(
                {
                    "restaurantId": str(restaurant.id),
                    "restaurantName": restaurant.name,
                    "agent": agent_payload,
                    "devices": {
                        "active": device_counts.get("active", 0),
                        "online": device_counts.get("online", 0),
                        "revoked": device_counts.get("revoked", 0),
                        "activeLocalAgent": device_counts.get("active_local_agent", 0),
                        "activePOS": device_counts.get("active_pos", 0),
                        "activeTV": device_counts.get("active_tv", 0),
                        "activeControl": device_counts.get("active_control", 0),
                        "telegramSubscriptions": telegram_subscription_counts.get(
                            restaurant.id,
                            0,
                        ),
                        "lastSeenAt": (
                            device_counts["last_seen_at"].isoformat()
                            if device_counts.get("last_seen_at")
                            else None
                        ),
                    },
                    "security": {
                        "unacknowledgedHigh": security_counts.get(
                            "unacknowledged_high", 0
                        ),
                        "unacknowledgedCritical": security_counts.get(
                            "unacknowledged_critical", 0
                        ),
                        "lastEventAt": (
                            security_counts["last_event_at"].isoformat()
                            if security_counts.get("last_event_at")
                            else None
                        ),
                    },
                }
            )

        branch_payloads.sort(
            key=lambda branch: (
                _branch_health_priority(branch, now=now),
                branch["restaurantName"].casefold(),
                branch["restaurantId"],
            )
        )

        active_devices = sum(item["active"] for item in device_aggregates.values())
        revoked_devices = sum(item["revoked"] for item in device_aggregates.values())
        active_pos_terminals = sum(
            item["active_pos"] for item in device_aggregates.values()
        )
        device_types = {
            "localAgent": sum(
                item["active_local_agent"] for item in device_aggregates.values()
            ),
            "pos": active_pos_terminals,
            "tv": sum(item["active_tv"] for item in device_aggregates.values()),
            "control": sum(
                item["active_control"] for item in device_aggregates.values()
            ),
        }

        return Response(
            {
                "generatedAt": now.isoformat(),
                "summary": {
                    "totalBranches": len(branches),
                    "agentOnline": agent_online,
                    "agentOffline": agent_offline,
                    "agentExpectedOffline": agent_expected_offline,
                    "agentAttentionRequired": agent_attention_required,
                    "agentMissing": agent_missing,
                    "activeDevices": active_devices,
                    "revokedDevices": revoked_devices,
                    "activePOSTerminals": active_pos_terminals,
                    "pendingPairings": scoped_pending_pairings.filter(
                        status=DevicePairing.Status.PENDING,
                        expires_at__gt=now,
                    ).count(),
                    "riskWindowHours": int(
                        ACTIVE_SECURITY_RISK_WINDOW.total_seconds() // 3600
                    ),
                    "unacknowledgedHigh": global_security["unacknowledged_high"],
                    "unacknowledgedCritical": global_security[
                        "unacknowledged_critical"
                    ],
                },
                "insights": {
                    "securityActivity": list(security_activity.values()),
                    "agentVersions": [
                        agent_versions[version] for version in sorted(agent_versions)
                    ],
                    "deviceTypes": device_types,
                },
                "branches": branch_payloads,
            }
        )
