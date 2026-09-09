import logging
from django.db import transaction
from django.core.exceptions import ValidationError
from parts.models import Order, OrderItem, Inventory, Part, Warehouse
from parts.services.inventory_service import get_or_create_inventory, record_transaction
from parts.services.audit_service import log_action

logger = logging.getLogger(__name__)


@transaction.atomic
def create_dealer_order(dealer, warehouse, items_data: list[dict], priority: str = 'NORMAL', user=None) -> Order:
    """
    Create a Dealer Order with OrderItem line items and immediately process inventory reservation.
    items_data: list of dicts [{'part': Part, 'quantity': int}]
    """
    order = Order.objects.create(
        dealer=dealer,
        warehouse=warehouse,
        priority=priority,
        status='PENDING'
    )

    for item_data in items_data:
        part = item_data['part']
        qty = item_data['quantity']
        OrderItem.objects.create(
            order=order,
            part=part,
            quantity_ordered=qty
        )
        # Set legacy fields for single item order compatibility
        if not order.part_id:
            order.part = part
            order.quantity = qty
            order.save()

    process_dealer_order(order, user=user)
    return order


@transaction.atomic
def process_dealer_order(order: Order, user=None) -> Order:
    """
    Evaluates available stock for all line items in dealer order,
    reserves available quantity, sets backorders, and updates order status.
    """
    if not order.warehouse:
        raise ValidationError("Order must have a designated warehouse for fulfillment.")

    all_fulfilled = True
    any_allocated = False

    items = order.items.all()
    if not items.exists() and order.part_id:
        # Fallback for legacy single-item orders
        items = [OrderItem.objects.create(order=order, part=order.part, quantity_ordered=order.quantity)]

    for item in items:
        inv = get_or_create_inventory(order.warehouse, item.part)
        needed = item.quantity_ordered - item.quantity_fulfilled - item.quantity_allocated
        
        if needed > 0:
            alloc_qty = min(needed, inv.available_stock)
            if alloc_qty > 0:
                record_transaction(
                    inventory=inv,
                    transaction_type='RESERVATION',
                    quantity=alloc_qty,
                    reference_type='Order',
                    reference_id=str(order.id),
                    reference_line_id=str(item.id),
                    performed_by=user,
                    notes=f"Reservation for Dealer Order #{order.id}"
                )
                item.quantity_allocated += alloc_qty
                any_allocated = True

        shortage = item.quantity_ordered - item.quantity_fulfilled - item.quantity_allocated
        item.quantity_backordered = max(0, shortage)
        item.save()

        if item.quantity_fulfilled + item.quantity_allocated < item.quantity_ordered:
            all_fulfilled = False

    if all_fulfilled:
        order.status = 'FULFILLED'
        order.fulfilled = True
    elif any_allocated:
        order.status = 'PARTIALLY_FULFILLED'
        order.fulfilled = False
    else:
        order.status = 'BACKORDERED'
        order.fulfilled = False

    order.save()
    log_action(f"PROCESS_ORDER_{order.status}", user=user, details=f"Order #{order.id} status set to {order.status}")
    return order


@transaction.atomic
def ship_dealer_order(order: Order, user=None) -> Order:
    """Fulfills and ships allocated order items, turning reservation into physical shipment."""
    for item in order.items.all():
        if item.quantity_allocated > 0:
            inv = get_or_create_inventory(order.warehouse, item.part)
            record_transaction(
                inventory=inv,
                transaction_type='SHIPMENT',
                quantity=item.quantity_allocated,
                reference_type='Order',
                reference_id=str(order.id),
                reference_line_id=str(item.id),
                performed_by=user,
                notes=f"Shipment for Dealer Order #{order.id}"
            )
            item.quantity_fulfilled += item.quantity_allocated
            item.quantity_allocated = 0
            item.quantity_backordered = max(0, item.quantity_ordered - item.quantity_fulfilled)
            item.save()

    order.status = 'FULFILLED'
    order.fulfilled = True
    order.save()
    log_action("SHIP_ORDER", user=user, details=f"Order #{order.id} shipped successfully.")
    return order


@transaction.atomic
def cancel_dealer_order(order: Order, user=None) -> Order:
    """Cancels order and releases any allocated reservations."""
    for item in order.items.all():
        if item.quantity_allocated > 0:
            inv = get_or_create_inventory(order.warehouse, item.part)
            record_transaction(
                inventory=inv,
                transaction_type='RELEASE',
                quantity=item.quantity_allocated,
                reference_type='Order',
                reference_id=str(order.id),
                reference_line_id=str(item.id),
                performed_by=user,
                notes=f"Release reservation for cancelled Order #{order.id}"
            )
            item.quantity_allocated = 0
            item.save()

    order.status = 'CANCELLED'
    order.fulfilled = False
    order.save()
    log_action("CANCEL_ORDER", user=user, details=f"Order #{order.id} cancelled.")
    return order
