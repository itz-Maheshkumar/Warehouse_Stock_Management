import logging
from parts.models import AuditLog

logger = logging.getLogger(__name__)


def log_action(action: str, user=None, details: str = "") -> AuditLog:
    """Log an operational event or user action to AuditLog."""
    entry = AuditLog.objects.create(
        action=action,
        user=user if (user and getattr(user, 'is_authenticated', True)) else None,
        details=details
    )
    logger.info(f"AuditLog created: {action} (User: {user})")
    return entry
