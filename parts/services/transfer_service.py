import logging
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from parts.models import StockTransfer, Recommendation, Inventory
from parts.services.inventory_service import get_or_create_inventory, record_transaction
from parts.services.audit_service import log_action

logger = logging.getLogger(__name__)


@transaction.atomic
def create_transfer(from_warehouse, to_warehouse, part, quantity: int, reason: str = "", user=None) -> StockTransfer:
    """Create a manual or system-driven StockTransfer request."""
    if quantity <= 0:
        raise ValidationError("Transfer quantity must be greater than zero.")
    if from_warehouse.id == to_warehouse.id:
        raise ValidationError("Source and destination warehouses cannot be the same.")

    ref_num = StockTransfer.objects.count() + 1001
    transfer = StockTransfer.objects.create(
        reference=f"TR-{ref_num}",
        from_warehouse=from_warehouse,
        to_warehouse=to_warehouse,
        part=part,
        quantity=quantity,
        status='PENDING_APPROVAL',
        reason=reason,
        created_by=user if (user and getattr(user, 'is_authenticated', True)) else None
    )
    log_action("CREATE_TRANSFER", user=user, details=f"Transfer request {transfer.reference} created.")
    return transfer


@transaction.atomic
def approve_transfer(transfer: StockTransfer, user=None) -> StockTransfer:
    """Approve a stock transfer request. Does not alter physical stock yet."""
    if transfer.status not in ['PENDING_APPROVAL', 'RECOMMENDED']:
        raise ValidationError(f"Cannot approve transfer in status '{transfer.status}'. Must be PENDING_APPROVAL or RECOMMENDED.")

    transfer.status = 'APPROVED'
    transfer.save()

    if hasattr(transfer, 'origin_recommendation') and transfer.origin_recommendation:
        rec = transfer.origin_recommendation
        rec.status = 'APPROVED'
        rec.approved_at = timezone.now()
        rec.approved_by = user if (user and getattr(user, 'is_authenticated', True)) else None
        rec.save()

    log_action("APPROVE_TRANSFER", user=user, details=f"Transfer {transfer.reference} approved.")
    return transfer


@transaction.atomic
def reject_transfer(transfer: StockTransfer, user=None, reason: str = "") -> StockTransfer:
    """Reject a stock transfer request."""
    if transfer.status in ['DISPATCHED', 'RECEIVED']:
        raise ValidationError(f"Cannot reject transfer already {transfer.status}.")

    transfer.status = 'REJECTED'
    if reason:
        transfer.reason = f"{transfer.reason} [Rejected: {reason}]"
    transfer.save()

    if hasattr(transfer, 'origin_recommendation') and transfer.origin_recommendation:
        rec = transfer.origin_recommendation
        rec.status = 'REJECTED'
        rec.rejected_at = timezone.now()
        rec.rejected_by = user if (user and getattr(user, 'is_authenticated', True)) else None
        rec.save()

    log_action("REJECT_TRANSFER", user=user, details=f"Transfer {transfer.reference} rejected.")
    return transfer


@transaction.atomic
def dispatch_transfer(transfer: StockTransfer, user=None) -> StockTransfer:
    """
    Dispatch stock transfer.
    Deducts on_hand at source warehouse and increases in_transit at destination warehouse.
    """
    if transfer.status != 'APPROVED':
        raise ValidationError(f"Transfer must be APPROVED before dispatch. Current status: '{transfer.status}'.")

    src_inv = get_or_create_inventory(transfer.from_warehouse, transfer.part)
    dst_inv = get_or_create_inventory(transfer.to_warehouse, transfer.part)

    # 1. Deduct physical stock at source warehouse via ledger
    record_transaction(
        inventory=src_inv,
        transaction_type='TRANSFER_OUT',
        quantity=transfer.quantity,
        reference_type='StockTransfer',
        reference_id=str(transfer.id),
        reference_line_id='DISPATCH',
        performed_by=user,
        notes=f"Dispatched Transfer {transfer.reference} to {transfer.to_warehouse.name}"
    )

    # 2. Increase in_transit at destination warehouse
    dst_inv.in_transit += transfer.quantity
    dst_inv.save()

    transfer.status = 'DISPATCHED'
    transfer.save()

    log_action("DISPATCH_TRANSFER", user=user, details=f"Transfer {transfer.reference} dispatched from {transfer.from_warehouse.name}.")
    return transfer


@transaction.atomic
def receive_transfer(transfer: StockTransfer, user=None) -> StockTransfer:
    """
    Receive stock transfer.
    Deducts in_transit and increases on_hand at destination warehouse via TRANSFER_IN ledger entry.
    Marks recommendation COMPLETED and auto-resolves notifications.
    """
    if transfer.status != 'DISPATCHED':
        raise ValidationError(f"Transfer must be DISPATCHED before receiving. Current status: '{transfer.status}'.")

    dst_inv = get_or_create_inventory(transfer.to_warehouse, transfer.part)

    # Record TRANSFER_IN ledger transaction at destination
    record_transaction(
        inventory=dst_inv,
        transaction_type='TRANSFER_IN',
        quantity=transfer.quantity,
        reference_type='StockTransfer',
        reference_id=str(transfer.id),
        reference_line_id='RECEIPT',
        performed_by=user,
        notes=f"Received Transfer {transfer.reference} from {transfer.from_warehouse.name}"
    )

    transfer.status = 'RECEIVED'
    transfer.actual_transit_days = transfer.estimated_transit_days
    transfer.save()

    if hasattr(transfer, 'origin_recommendation') and transfer.origin_recommendation:
        rec = transfer.origin_recommendation
        rec.status = 'COMPLETED'
        rec.completed_at = timezone.now()
        rec.save()

    # Recalculate risk & auto-resolve notifications
    from parts.services.notification_service import evaluate_and_resolve_notifications
    evaluate_and_resolve_notifications(transfer.part, transfer.to_warehouse)

    log_action("RECEIVE_TRANSFER", user=user, details=f"Transfer {transfer.reference} received at {transfer.to_warehouse.name}.")
    return transfer
