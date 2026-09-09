import logging
from parts.models import Part, Warehouse, Inventory
from parts.services.inventory_service import get_or_create_inventory
from parts.services.forecast_service import generate_forecast

logger = logging.getLogger(__name__)


def calculate_stockout_risk(part: Part, warehouse: Warehouse) -> dict:
    """
    Deterministic Stockout Risk Engine.
    Calculates four normalized sub-scores (0-100):
    1. Inventory Coverage Risk (40%)
    2. Safety Stock Breach Risk (25%)
    3. Lead-Time Exposure Risk (20%)
    4. Part Criticality Risk (15%)
    """
    inv = get_or_create_inventory(warehouse, part)
    fc = generate_forecast(part, warehouse, horizon=30)

    lead_time_days = part.supplier_lead_time_days or 20
    forecast_30d = fc.predicted_demand or 85.0
    lead_time_demand = round(forecast_30d * (lead_time_days / 30.0), 1)

    available = inv.available_stock
    safety_stock = inv.safety_stock or part.safety_stock or 30
    incoming = inv.incoming

    projected_position = available + incoming - lead_time_demand

    # 1. Inventory Coverage Risk (0 - 100)
    if available <= 0:
        coverage_subscore = 100.0
    elif available < lead_time_demand:
        # High vulnerability when available stock cannot cover lead-time demand
        coverage_subscore = min(100.0, ((lead_time_demand - available) / max(1.0, lead_time_demand)) * 100.0 + 35.0)
    else:
        coverage_subscore = max(0.0, 50.0 - ((available - lead_time_demand) / max(1.0, lead_time_demand)) * 50.0)

    # 2. Safety Stock Breach Risk (0 - 100)
    if available <= 0:
        safety_subscore = 100.0
    elif available < safety_stock:
        safety_subscore = min(100.0, ((safety_stock - available) / max(1.0, safety_stock)) * 100.0 + 40.0)
    else:
        safety_subscore = 0.0

    # 3. Lead-Time Exposure Risk (0 - 100)
    base_lt_risk = (lead_time_days / 30.0) * 100.0
    if available < lead_time_demand:
        lead_time_subscore = min(100.0, base_lt_risk + 30.0)
    else:
        lead_time_subscore = max(0.0, base_lt_risk - 20.0)

    # 4. Part Criticality Risk (0 - 100)
    crit_map = {
        'CRITICAL': 100.0,
        'HIGH': 85.0,
        'MEDIUM': 50.0,
        'LOW': 20.0,
    }
    criticality_subscore = crit_map.get(str(part.criticality).upper(), 50.0)

    # Final Weighted Risk Score calculation
    weighted_score = (
        (coverage_subscore * 0.40) +
        (safety_subscore * 0.25) +
        (lead_time_subscore * 0.20) +
        (criticality_subscore * 0.15)
    )

    risk_score = int(min(99, max(1, round(weighted_score))))

    # Risk level mapping
    if risk_score >= 81:
        risk_level = 'Critical'
    elif risk_score >= 61:
        risk_level = 'High'
    elif risk_score >= 31:
        risk_level = 'Medium'
    else:
        risk_level = 'Low'

    # Explanations and contributing factors
    factors = []
    if available < lead_time_demand:
        factors.append(f"Available stock ({available}) is lower than 20-day lead-time demand ({lead_time_demand} units).")
    if available < safety_stock:
        factors.append(f"Stock breaches safety threshold of {safety_stock} units.")
    if lead_time_days >= 20:
        factors.append(f"Long supplier lead time ({lead_time_days} days).")
    if part.criticality in ['HIGH', 'CRITICAL']:
        factors.append(f"Part criticality is set to {part.criticality}.")

    explanation = " ".join(factors) if factors else "Stock levels are healthy relative to forecasted demand."

    recommended_action = "HOLD"
    if risk_score >= 61:
        recommended_action = "TRANSFER" if available < lead_time_demand else "REORDER"

    return {
        'part_id': part.id,
        'warehouse_id': warehouse.id,
        'part_sku': part.sku,
        'part_name': part.name,
        'warehouse_name': warehouse.name,
        'available_stock': available,
        'reserved_stock': inv.reserved,
        'on_hand_stock': inv.on_hand,
        'incoming_stock': incoming,
        'safety_stock': safety_stock,
        'supplier_lead_time_days': lead_time_days,
        'forecast_30d': forecast_30d,
        'lead_time_demand': lead_time_demand,
        'projected_inventory_position': projected_position,
        'risk_score': risk_score,
        'risk_level': risk_level,
        'sub_scores': {
            'inventory_coverage_risk': round(coverage_subscore, 1),
            'safety_stock_breach_risk': round(safety_subscore, 1),
            'lead_time_exposure_risk': round(lead_time_subscore, 1),
            'criticality_risk': round(criticality_subscore, 1),
        },
        'contributing_factors': factors,
        'explanation': explanation,
        'recommended_action': recommended_action,
    }
