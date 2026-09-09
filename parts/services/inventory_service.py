import logging
from django.db import transaction, IntegrityError
from django.core.exceptions import ValidationError
from parts.models import Inventory, InventoryTransaction, Warehouse, Part
from parts.services.audit_service import log_action

logger = logging.getLogger(__name__)


def get_or_create_inventory(warehouse: Warehouse, part: Part) -> Inventory:
    """Fetch existing Inventory record or create a new initialized one."""
    inv, _ = Inventory.objects.get_or_create(
        warehouse=warehouse,
        part=part,
        defaults={
            'on_hand': 0,
            'reserved': 0,
            'damaged': 0,
            'incoming': 0,
            'in_transit': 0,
            'safety_stock': part.safety_stock,
            'reorder_level': part.reorder_level,
            'maximum_stock': part.maximum_stock,
        }
    )
    return inv


@transaction.atomic
def record_transaction(
    inventory: Inventory,
    transaction_type: str,
    quantity: int,
    reference_type: str,
    reference_id: str,
    reference_line_id: str = "",
    performed_by=None,
    notes: str = ""
) -> tuple[Inventory, InventoryTransaction]:
    """
    Append-only inventory ledger transaction recorder.
    Uses select_for_update() row locking and enforces composite idempotency:
    (reference_type, reference_id, transaction_type, reference_line_id).
    """
    if quantity <= 0 and transaction_type not in ['ADJUSTMENT']:
        raise ValidationError(f"Quantity for {transaction_type} must be positive.")

    # Check for duplicate idempotency key first
    existing = InventoryTransaction.objects.filter(
        reference_type=reference_type,
        reference_id=str(reference_id),
        transaction_type=transaction_type,
        reference_line_id=str(reference_line_id)
    ).first()

    if existing:
        logger.info(f"Duplicate transaction skipped via idempotency key: {reference_type}-{reference_id}-{transaction_type}")
        inv = Inventory.objects.get(pk=existing.inventory_id)
        return inv, existing

    # Lock row for atomic mutation
    locked_inv = Inventory.objects.select_for_update().get(pk=inventory.pk)

    # Perform inventory updates based on transaction type semantics
    if transaction_type == 'RECEIPT':
        locked_inv.on_hand += quantity
        if locked_inv.incoming >= quantity:
            locked_inv.incoming -= quantity
        else:
            locked_inv.incoming = 0

    elif transaction_type == 'RESERVATION':
        if locked_inv.available_stock < quantity:
            raise ValidationError(
                f"Insufficient available stock for reservation. Required: {quantity}, Available: {locked_inv.available_stock}"
            )
        locked_inv.reserved += quantity

    elif transaction_type == 'RELEASE':
        locked_inv.reserved = max(0, locked_inv.reserved - quantity)

    elif transaction_type == 'SHIPMENT':
        if locked_inv.on_hand < quantity:
            raise ValidationError(f"Insufficient physical on-hand stock for shipment ({locked_inv.on_hand} < {quantity})")
        locked_inv.on_hand -= quantity
        locked_inv.reserved = max(0, locked_inv.reserved - quantity)

    elif transaction_type == 'TRANSFER_OUT':
        if locked_inv.on_hand < quantity:
            raise ValidationError(f"Insufficient on-hand stock for transfer out ({locked_inv.on_hand} < {quantity})")
        locked_inv.on_hand -= quantity

    elif transaction_type == 'TRANSFER_IN':
        locked_inv.in_transit = max(0, locked_inv.in_transit - quantity)
        locked_inv.on_hand += quantity

    elif transaction_type == 'ADJUSTMENT':
        if locked_inv.on_hand + quantity < locked_inv.reserved + locked_inv.damaged:
            raise ValidationError("Adjustment would breach non-negative available stock rule.")
        locked_inv.on_hand += quantity

    elif transaction_type == 'DAMAGE':
        if locked_inv.available_stock < quantity:
            raise ValidationError("Cannot mark more stock damaged than is currently available.")
        locked_inv.damaged += quantity

    elif transaction_type == 'RETURN':
        locked_inv.on_hand += quantity

    else:
        raise ValidationError(f"Unsupported transaction type: {transaction_type}")

    locked_inv.save()

    txn = InventoryTransaction.objects.create(
        inventory=locked_inv,
        transaction_type=transaction_type,
        quantity=quantity,
        reference_type=reference_type,
        reference_id=str(reference_id),
        reference_line_id=str(reference_line_id),
        performed_by=performed_by if (performed_by and getattr(performed_by, 'is_authenticated', True)) else None,
        notes=notes
    )

    log_action(
        action=f"INVENTORY_TXN_{transaction_type}",
        user=performed_by,
        details=f"Part: {locked_inv.part.sku}, Warehouse: {locked_inv.warehouse.name}, Qty: {quantity}, Ref: {reference_type}:{reference_id}"
    )

    return locked_inv, txn
