import logging
from django.db import transaction
from parts.models import Part, Warehouse, Inventory, Recommendation, StockTransfer
from parts.services.inventory_service import get_or_create_inventory
from parts.services.risk_service import calculate_stockout_risk
from parts.services.forecast_service import generate_forecast

logger = logging.getLogger(__name__)


def generate_recommendation_for_part_warehouse(part: Part, warehouse: Warehouse) -> Recommendation:
    """
    Evaluates risk and determines optimal decision (TRANSFER, REORDER, EXPEDITE, HOLD).
    Validates source warehouse safe surplus before recommending TRANSFER.
    """
    risk_info = calculate_stockout_risk(part, warehouse)
    risk_score = risk_info['risk_score']
    target_available = risk_info['available_stock']
    lead_time_demand = risk_info['lead_time_demand']
    safety_stock = risk_info['safety_stock']
    inv_pos = risk_info['projected_inventory_position']

    # Priority 1: Check if Stockout Risk is High or Critical
    if risk_score >= 61:
        needed_qty = int(max(20, lead_time_demand - target_available))

        # Check other India warehouses for safe surplus
        other_warehouses = Warehouse.objects.exclude(id=warehouse.id)
        best_source = None
        best_surplus = -1

        transfer_lead_time_days = 5  # default transit duration for MVP

        for source in other_warehouses:
            src_inv = get_or_create_inventory(source, part)
            src_avail = src_inv.available_stock
            src_safety = src_inv.safety_stock or part.safety_stock or 30

            # Calculate source demand during transfer lead time (5 days)
            src_fc = generate_forecast(part, source, horizon=30)
            src_daily_demand = (src_fc.predicted_demand or 30.0) / 30.0
            src_transfer_demand = src_daily_demand * transfer_lead_time_days

            # Safe Surplus formula
            remaining_safe_surplus = src_avail - needed_qty - src_safety - src_transfer_demand

            if remaining_safe_surplus > 0 and remaining_safe_surplus > best_surplus:
                best_surplus = remaining_safe_surplus
                best_source = source

        if best_source:
            rec_type = 'TRANSFER'
            rec_quantity = needed_qty
            source_wh = best_source
            target_wh = warehouse
            reason = (
                f"Transfer {needed_qty} units from {best_source.name} to {warehouse.name}. "
                f"Estimated transit duration ({transfer_lead_time_days} days) is faster than supplier lead time ({part.supplier_lead_time_days} days). "
                f"{best_source.name} maintains a safe surplus of {int(best_surplus)} units."
            )
            priority = 'CRITICAL' if risk_score >= 81 else 'HIGH'

        elif part.supplier_lead_time_days <= 30:
            rec_type = 'REORDER'
            rec_quantity = int(max(0, lead_time_demand + safety_stock - inv_pos)) or needed_qty
            source_wh = None
            target_wh = warehouse
            reason = (
                f"Reorder {rec_quantity} units from supplier {part.supplier_name}. "
                f"Supplier lead time is {part.supplier_lead_time_days} days."
            )
            priority = 'HIGH'

        else:
            rec_type = 'EXPEDITE'
            rec_quantity = int(max(0, lead_time_demand + safety_stock - inv_pos)) or needed_qty
            source_wh = None
            target_wh = warehouse
            reason = (
                f"Expedite purchase order of {rec_quantity} units with supplier {part.supplier_name}. "
                f"Part criticality is {part.criticality} and supplier lead time ({part.supplier_lead_time_days} days) exposes high stockout risk."
            )
            priority = 'CRITICAL'

    else:
        rec_type = 'HOLD'
        rec_quantity = None
        source_wh = None
        target_wh = warehouse
        reason = f"Inventory status at {warehouse.name} is healthy ({target_available} available units). Monitor stock."
        priority = 'LOW'

    # Update or create recommendation record
    rec, created = Recommendation.objects.update_or_create(
        part=part,
        warehouse=warehouse,
        status='PENDING',
        defaults={
            'recommendation_type': rec_type,
            'source_warehouse': source_wh,
            'target_warehouse': target_wh,
            'quantity': rec_quantity,
            'risk_score': risk_score,
            'confidence': 'HIGH',
            'priority': priority,
            'reason': reason,
        }
    )

    logger.info(f"Recommendation generated: [{rec_type}] {part.sku} @ {warehouse.name} (status = {rec.status})")
    return rec


def generate_all_recommendations() -> list[Recommendation]:
    """Generates recommendations for all active inventory records in the database."""
    recs = []
    inventories = Inventory.objects.select_related('part', 'warehouse').all()
    for inv in inventories:
        rec = generate_recommendation_for_part_warehouse(inv.part, inv.warehouse)
        recs.append(rec)
    return recs
