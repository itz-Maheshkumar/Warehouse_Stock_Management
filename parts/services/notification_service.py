import logging
from django.utils import timezone
from parts.models import Notification, Part, Warehouse
from parts.services.risk_service import calculate_stockout_risk

logger = logging.getLogger(__name__)


def create_or_update_notification(
    title: str,
    message: str,
    notification_type: str,
    part: Part,
    warehouse: Warehouse,
    link: str = ""
) -> Notification:
    """
    Creates a notification with deduplication based on active_condition_key.
    Prevents duplicate unread notifications from flooding topbar.
    """
    condition_key = f"cond_{part.id}_{warehouse.id}_{notification_type}"

    existing = Notification.objects.filter(
        active_condition_key=condition_key,
        is_resolved=False
    ).first()

    if existing:
        existing.message = message
        existing.save()
        return existing

    notif = Notification.objects.create(
        title=title,
        message=message,
        notification_type=notification_type,
        link=link or f"/parts/{part.id}/",
        active_condition_key=condition_key,
        is_read=False,
        is_resolved=False
    )
    logger.info(f"Notification created: [{notification_type}] {title}")
    return notif


def evaluate_and_resolve_notifications(part: Part, warehouse: Warehouse):
    """
    Recalculates risk for part and warehouse. If risk drops below threshold,
    resolves any associated active notifications.
    """
    risk_info = calculate_stockout_risk(part, warehouse)
    risk_score = risk_info['risk_score']

    if risk_score < 60:
        # Resolve active critical stockout/transfer alerts
        active_notifs = Notification.objects.filter(
            active_condition_key__startswith=f"cond_{part.id}_{warehouse.id}_",
            is_resolved=False
        )
        for n in active_notifs:
            n.is_resolved = True
            n.resolved_at = timezone.now()
            n.save()
            logger.info(f"Notification resolved: ID {n.id} - {n.title}")


def get_unread_notifications():
    """Returns all active, unread notifications for topbar display."""
    return Notification.objects.filter(is_read=False, is_resolved=False).order_by('-created_at')


def mark_notification_as_read(notification_id: int) -> Notification:
    """Marks a notification as read."""
    notif = Notification.objects.get(pk=notification_id)
    notif.is_read = True
    notif.save()
    return notif
