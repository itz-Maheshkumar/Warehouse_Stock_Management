import random
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model
from parts.models import (
    Warehouse, Part, Inventory, Dealer, Order, OrderItem,
    DemandHistory, ForecastResult, Recommendation, StockTransfer,
    Notification, AuditLog, InventoryTransaction
)
from parts.services.inventory_service import get_or_create_inventory, record_transaction
from parts.services.order_service import create_dealer_order
from parts.services.forecast_service import generate_forecast
from parts.services.risk_service import calculate_stockout_risk
from parts.services.recommendation_service import generate_all_recommendations
from parts.services.transfer_service import create_transfer
from parts.services.notification_service import create_or_update_notification
from parts.services.audit_service import log_action

User = get_user_model()


class Command(BaseCommand):
    help = "Seeds CatParts India realistic demo data with calibrated inventory, demand history, risk, and transfers."

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Wipes existing domain data before seeding demo state.'
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options['reset']:
            self.stdout.write(self.style.WARNING("Resetting existing domain data..."))
            Notification.objects.all().delete()
            Recommendation.objects.all().delete()
            StockTransfer.objects.all().delete()
            InventoryTransaction.objects.all().delete()
            DemandHistory.objects.all().delete()
            ForecastResult.objects.all().delete()
            OrderItem.objects.all().delete()
            Order.objects.all().delete()
            Inventory.objects.all().delete()
            Dealer.objects.all().delete()
            Part.objects.all().delete()
            Warehouse.objects.all().delete()
            AuditLog.objects.all().delete()

        self.stdout.write(self.style.SUCCESS("Seeding India Warehouses..."))
        chennai, _ = Warehouse.objects.get_or_create(
            name="Chennai Regional Parts Distribution Center",
            defaults={'location': 'Chennai, Tamil Nadu', 'code': 'WH-CHE'}
        )
        pune, _ = Warehouse.objects.get_or_create(
            name="Pune Spare Parts Depot",
            defaults={'location': 'Pune, Maharashtra', 'code': 'WH-PUN'}
        )
        delhi, _ = Warehouse.objects.get_or_create(
            name="Delhi NCR Distribution Hub",
            defaults={'location': 'Gurugram, Delhi NCR', 'code': 'WH-DEL'}
        )
        bengaluru, _ = Warehouse.objects.get_or_create(
            name="Bengaluru Tech-Parts Warehouse",
            defaults={'location': 'Bengaluru, Karnataka', 'code': 'WH-BLR'}
        )

        self.stdout.write(self.style.SUCCESS("Seeding Parts..."))
        seal_kit, _ = Part.objects.get_or_create(
            sku="CAT-HYD-002",
            defaults={
                'name': "Hydraulic Pump Seal Kit",
                'category': "Hydraulic",
                'reorder_level': 50,
                'criticality': "HIGH",
                'unit_cost': 2500.00,
                'supplier_lead_time_days': 20,
                'supplier_name': "ABC Components",
                'safety_stock': 30,
                'maximum_stock': 200
            }
        )
        oil_filter, _ = Part.objects.get_or_create(
            sku="CAT-ENG-001",
            defaults={
                'name': "Engine Oil Filter",
                'category': "Engine",
                'reorder_level': 100,
                'criticality': "MEDIUM",
                'unit_cost': 1200.00,
                'supplier_lead_time_days': 14,
                'supplier_name': "FilterTech Pvt Ltd",
                'safety_stock': 40,
                'maximum_stock': 300
            }
        )
        fuel_filter, _ = Part.objects.get_or_create(
            sku="CAT-FLT-003",
            defaults={
                'name': "Fuel Filter",
                'category': "Engine",
                'reorder_level': 150,
                'criticality': "MEDIUM",
                'unit_cost': 1800.00,
                'supplier_lead_time_days': 15,
                'supplier_name': "FilterTech Pvt Ltd",
                'safety_stock': 50,
                'maximum_stock': 400
            }
        )
        track_roller, _ = Part.objects.get_or_create(
            sku="CAT-TRK-004",
            defaults={
                'name': "Track Roller Assembly",
                'category': "Undercarriage",
                'reorder_level': 20,
                'criticality': "CRITICAL",
                'unit_cost': 15000.00,
                'supplier_lead_time_days': 25,
                'supplier_name': "IndoForging India",
                'safety_stock': 10,
                'maximum_stock': 50
            }
        )

        self.stdout.write(self.style.SUCCESS("Seeding Dealers..."))
        dealer_tn, _ = Dealer.objects.get_or_create(name="Demo Dealer Tamil Nadu", defaults={'region': 'South'})
        dealer_mh, _ = Dealer.objects.get_or_create(name="Demo Dealer Maharashtra", defaults={'region': 'West'})
        dealer_del, _ = Dealer.objects.get_or_create(name="Demo Dealer North India", defaults={'region': 'North'})
        dealer_ka, _ = Dealer.objects.get_or_create(name="Demo Dealer Karnataka", defaults={'region': 'South'})

        self.stdout.write(self.style.SUCCESS("Seeding Calibrated Inventories..."))
        # Chennai Hydraulic Seal Kit: On Hand 28, Reserved 10, Available 18
        inv_seal_che, _ = Inventory.objects.update_or_create(
            part=seal_kit, warehouse=chennai,
            defaults={'on_hand': 28, 'reserved': 10, 'damaged': 0, 'incoming': 0, 'in_transit': 0, 'safety_stock': 30, 'reorder_level': 50, 'maximum_stock': 200}
        )
        # Pune Hydraulic Seal Kit: On Hand 120, Reserved 0, Available 120
        inv_seal_pun, _ = Inventory.objects.update_or_create(
            part=seal_kit, warehouse=pune,
            defaults={'on_hand': 120, 'reserved': 0, 'damaged': 0, 'incoming': 0, 'in_transit': 0, 'safety_stock': 30, 'reorder_level': 50, 'maximum_stock': 200}
        )
        # Delhi NCR & Blr Seal Kit
        Inventory.objects.update_or_create(
            part=seal_kit, warehouse=delhi,
            defaults={'on_hand': 45, 'reserved': 5, 'damaged': 0, 'incoming': 20, 'in_transit': 0, 'safety_stock': 30, 'reorder_level': 50, 'maximum_stock': 200}
        )
        Inventory.objects.update_or_create(
            part=seal_kit, warehouse=bengaluru,
            defaults={'on_hand': 60, 'reserved': 0, 'damaged': 0, 'incoming': 0, 'in_transit': 0, 'safety_stock': 30, 'reorder_level': 50, 'maximum_stock': 200}
        )

        # Other parts inventory setup
        Inventory.objects.update_or_create(part=oil_filter, warehouse=chennai, defaults={'on_hand': 125, 'reserved': 5, 'incoming': 20, 'safety_stock': 40, 'reorder_level': 100})
        Inventory.objects.update_or_create(part=fuel_filter, warehouse=chennai, defaults={'on_hand': 260, 'reserved': 10, 'incoming': 50, 'safety_stock': 50, 'reorder_level': 150})
        Inventory.objects.update_or_create(part=track_roller, warehouse=pune, defaults={'on_hand': 5, 'reserved': 1, 'incoming': 0, 'safety_stock': 10, 'reorder_level': 20})

        self.stdout.write(self.style.SUCCESS("Seeding 60 Days Demand History..."))
        today = date.today()
        random.seed(42)  # reproducible seed
        for days_back in range(60, 0, -1):
            dt = today - timedelta(days=days_back)
            # Chennai seal kit daily demand averages ~2.8 units -> 85 units per 30 days
            q_che = max(1, int(random.gauss(2.85, 0.8)))
            DemandHistory.objects.update_or_create(
                part=seal_kit, warehouse=chennai, date=dt,
                defaults={'quantity_demanded': q_che}
            )
            # Pune seal kit daily demand
            q_pun = max(1, int(random.gauss(1.5, 0.5)))
            DemandHistory.objects.update_or_create(
                part=seal_kit, warehouse=pune, date=dt,
                defaults={'quantity_demanded': q_pun}
            )

        self.stdout.write(self.style.SUCCESS("Seeding Initial Dealer Orders & Transactions..."))
        # Seed initial reservation ledger entry for Chennai seal kit 10 units
        record_transaction(
            inventory=inv_seal_che,
            transaction_type='RESERVATION',
            quantity=10,
            reference_type='Order',
            reference_id='ORD-INIT-01',
            notes='Initial Dealer Order Reservation demo'
        )

        order1 = Order.objects.create(
            dealer=dealer_tn,
            warehouse=chennai,
            priority='CRITICAL',
            status='PARTIALLY_FULFILLED',
            part=seal_kit,
            quantity=10,
            fulfilled=False
        )
        OrderItem.objects.create(
            order=order1,
            part=seal_kit,
            quantity_ordered=10,
            quantity_allocated=10,
            quantity_fulfilled=0,
            quantity_backordered=0
        )

        self.stdout.write(self.style.SUCCESS("Running Forecast, Risk Engine & Recommendations..."))
        generate_forecast(seal_kit, chennai, horizon=30)
        generate_forecast(seal_kit, pune, horizon=30)
        risk_info = calculate_stockout_risk(seal_kit, chennai)

        # Generate recommendation & link transfer
        generate_all_recommendations()
        rec = Recommendation.objects.filter(part=seal_kit, warehouse=chennai).first()

        if rec and rec.recommendation_type == 'TRANSFER' and rec.source_warehouse:
            transfer = create_transfer(
                from_warehouse=rec.source_warehouse,
                to_warehouse=rec.target_warehouse,
                part=rec.part,
                quantity=rec.quantity,
                reason=rec.reason
            )
            rec.transfer = transfer
            rec.save()

        create_or_update_notification(
            title=f"CRITICAL STOCKOUT RISK: {seal_kit.name} at {chennai.name}",
            message=f"Available stock ({risk_info['available_stock']}) is critically low against 20-day lead-time demand ({risk_info['lead_time_demand']} units). Risk score: {risk_info['risk_score']}%.",
            notification_type='CRITICAL_STOCKOUT',
            part=seal_kit,
            warehouse=chennai
        )

        log_action("SEED_DEMO_DATA", details="Demo data seeded successfully with exact Chennai-Pune transfer scenario.")

        self.stdout.write(self.style.SUCCESS(
            f"Successfully seeded demo environment!\n"
            f"  - Chennai Seal Kit: On Hand={inv_seal_che.on_hand}, Reserved={inv_seal_che.reserved}, Available={inv_seal_che.available_stock}\n"
            f"  - Pune Seal Kit: On Hand={inv_seal_pun.on_hand}, Reserved={inv_seal_pun.reserved}, Available={inv_seal_pun.available_stock}\n"
            f"  - Calculated Risk: {risk_info['risk_score']}% ({risk_info['risk_level']})\n"
            f"  - Recommendation: {rec.recommendation_type if rec else 'None'} ({rec.quantity if rec else 0} units)"
        ))
