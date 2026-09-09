import logging
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from parts.models import Warehouse, Part, Inventory, Order, StockTransfer, Recommendation, AuditLog

logger = logging.getLogger(__name__)

ROLE_ADMIN = 'Admin'
ROLE_MANAGER = 'Warehouse Manager'
ROLE_OPERATOR = 'Warehouse Operator'
ROLE_VIEWER = 'Viewer'


def setup_roles_and_permissions():
    """Initializes standard Django Auth Groups and Permissions for CatParts India."""
    admin_group, _ = Group.objects.get_or_create(name=ROLE_ADMIN)
    manager_group, _ = Group.objects.get_or_create(name=ROLE_MANAGER)
    operator_group, _ = Group.objects.get_or_create(name=ROLE_OPERATOR)
    viewer_group, _ = Group.objects.get_or_create(name=ROLE_VIEWER)

    # Assign permissions if needed
    logger.info("Django RBAC Groups initialized: Admin, Warehouse Manager, Warehouse Operator, Viewer.")


def is_manager(user) -> bool:
    """Checks if user has Warehouse Manager or Admin privileges."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(name__in=[ROLE_ADMIN, ROLE_MANAGER]).exists()


def is_operator(user) -> bool:
    """Checks if user has Warehouse Operator, Manager, or Admin privileges."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(name__in=[ROLE_ADMIN, ROLE_MANAGER, ROLE_OPERATOR]).exists()
