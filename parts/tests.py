from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.contrib.auth import get_user_model
from parts.models import (
    Warehouse, Part, Inventory, InventoryTransaction, Dealer, Order, OrderItem,
    DemandHistory, ForecastResult, StockTransfer, Recommendation, Notification
)
from parts.services.inventory_service import get_or_create_inventory, record_transaction
from parts.services.order_service import create_dealer_order, process_dealer_order, ship_dealer_order, cancel_dealer_order
from parts.services.forecast_service import generate_forecast, calculate_forecast_accuracy
from parts.services.risk_service import calculate_stockout_risk
from parts.services.recommendation_service import generate_recommendation_for_part_warehouse, generate_all_recommendations
from parts.services.transfer_service import create_transfer, approve_transfer, dispatch_transfer, receive_transfer
from parts.services.notification_service import create_or_update_notification, evaluate_and_resolve_notifications, get_unread_notifications

User = get_user_model()


class InventoryEngineTests(TestCase):
    def setUp(self):
        self.wh_chennai = Warehouse.objects.create(name="Chennai PDC", location="Chennai")
        self.wh_pune = Warehouse.objects.create(name="Pune Depot", location="Pune")
        self.part_seal = Part.objects.create(
            sku="CAT-HYD-002",
            name="Hydraulic Pump Seal Kit",
            category="Hydraulic",
            reorder_level=50,
            criticality="HIGH",
            unit_cost=2500.00,
            supplier_lead_time_days=20,
            safety_stock=30
        )

    def test_inventory_derived_properties(self):
        inv = Inventory.objects.create(
            warehouse=self.wh_chennai,
            part=self.part_seal,
            on_hand=28,
            reserved=10,
            damaged=0,
            incoming=0
        )
        self.assertEqual(inv.available_stock, 18)
        self.assertEqual(inv.available, 18)
        self.assertEqual(inv.inventory_position, 18)
        self.assertEqual(inv.total_value, 28 * 2500.00)
        self.assertEqual(inv.calculated_status, 'Critical')

    def test_ledger_transaction_recording_and_idempotency(self):
        inv = get_or_create_inventory(self.wh_chennai, self.part_seal)
        inv.on_hand = 50
        inv.save()

        # 1. Reservation
        inv, txn1 = record_transaction(
            inventory=inv,
            transaction_type='RESERVATION',
            quantity=10,
            reference_type='Order',
            reference_id='ORD-101',
            reference_line_id='LINE-1'
        )
        self.assertEqual(inv.reserved, 10)
        self.assertEqual(inv.available_stock, 40)

        # 2. Idempotent retry should return existing transaction without double reserving
        inv_retry, txn_retry = record_transaction(
            inventory=inv,
            transaction_type='RESERVATION',
            quantity=10,
            reference_type='Order',
            reference_id='ORD-101',
            reference_line_id='LINE-1'
        )
        self.assertEqual(txn_retry.id, txn1.id)
        self.assertEqual(inv_retry.reserved, 10)
        self.assertEqual(inv_retry.available_stock, 40)

    def test_prevent_insufficient_stock_reservation(self):
        inv = get_or_create_inventory(self.wh_chennai, self.part_seal)
        inv.on_hand = 10
        inv.reserved = 5
        inv.save()  # available = 5

        with self.assertRaises(ValidationError):
            record_transaction(
                inventory=inv,
                transaction_type='RESERVATION',
                quantity=10,
                reference_type='Order',
                reference_id='ORD-999'
            )


class DealerOrderFulfillmentTests(TestCase):
    def setUp(self):
        self.wh = Warehouse.objects.create(name="Chennai PDC")
        self.dealer = Dealer.objects.create(name="Demo Dealer TN")
        self.part = Part.objects.create(
            sku="CAT-HYD-002",
            name="Hydraulic Seal Kit",
            reorder_level=50,
            safety_stock=30
        )
        self.inv = get_or_create_inventory(self.wh, self.part)
        self.inv.on_hand = 28
        self.inv.save()

    def test_order_creation_and_reservation(self):
        order = create_dealer_order(
            dealer=self.dealer,
            warehouse=self.wh,
            items_data=[{'part': self.part, 'quantity': 10}]
        )
        self.inv.refresh_from_db()

        self.assertEqual(self.inv.on_hand, 28)
        self.assertEqual(self.inv.reserved, 10)
        self.assertEqual(self.inv.available_stock, 18)
        self.assertEqual(order.status, 'FULFILLED')

    def test_shipment_reduces_on_hand_and_reserved(self):
        order = create_dealer_order(
            dealer=self.dealer,
            warehouse=self.wh,
            items_data=[{'part': self.part, 'quantity': 10}]
        )
        ship_dealer_order(order)
        self.inv.refresh_from_db()

        self.assertEqual(self.inv.on_hand, 18)
        self.assertEqual(self.inv.reserved, 0)
        self.assertEqual(self.inv.available_stock, 18)


class ForecastingAndRiskEngineTests(TestCase):
    def setUp(self):
        self.wh = Warehouse.objects.create(name="Chennai PDC")
        self.part = Part.objects.create(
            sku="CAT-HYD-002",
            name="Hydraulic Seal Kit",
            supplier_lead_time_days=20,
            reorder_level=85,
            safety_stock=30,
            criticality="HIGH"
        )
        from datetime import date, timedelta
        today = date.today()
        for i in range(30, 0, -1):
            DemandHistory.objects.create(
                part=self.part, warehouse=self.wh, date=today - timedelta(days=i), quantity_demanded=3
            )
        self.inv = get_or_create_inventory(self.wh, self.part)
        self.inv.on_hand = 28
        self.inv.reserved = 10
        self.inv.save()  # available = 18

    def test_deterministic_stockout_risk_scoring(self):
        fc = generate_forecast(self.part, self.wh, horizon=30)
        self.assertTrue(fc.predicted_demand > 0)

        risk_info = calculate_stockout_risk(self.part, self.wh)
        self.assertEqual(risk_info['available_stock'], 18)
        self.assertEqual(risk_info['risk_level'], 'Critical')
        self.assertTrue(risk_info['risk_score'] >= 81)
        self.assertIn('lead_time_demand', risk_info)
        self.assertIn('sub_scores', risk_info)


class RecommendationAndTransferWorkflowTests(TestCase):
    def setUp(self):
        self.che = Warehouse.objects.create(name="Chennai PDC")
        self.pune = Warehouse.objects.create(name="Pune Depot")
        self.part = Part.objects.create(
            sku="CAT-HYD-002",
            name="Hydraulic Seal Kit",
            supplier_lead_time_days=20,
            safety_stock=30,
            criticality="HIGH"
        )
        # Chennai: On Hand 28, Reserved 10 -> Available 18
        self.inv_che = get_or_create_inventory(self.che, self.part)
        self.inv_che.on_hand = 28
        self.inv_che.reserved = 10
        self.inv_che.save()

        # Pune: On Hand 120, Reserved 0 -> Available 120 (Safe surplus)
        self.inv_pune = get_or_create_inventory(self.pune, self.part)
        self.inv_pune.on_hand = 120
        self.inv_pune.save()

    def test_smart_recommendation_evaluates_safe_surplus_and_generates_transfer(self):
        rec = generate_recommendation_for_part_warehouse(self.part, self.che)
        self.assertEqual(rec.recommendation_type, 'TRANSFER')
        self.assertEqual(rec.source_warehouse, self.pune)
        self.assertEqual(rec.target_warehouse, self.che)
        self.assertTrue(rec.quantity >= 20)

    def test_transfer_lifecycle_approved_dispatched_received(self):
        rec = generate_recommendation_for_part_warehouse(self.part, self.che)
        transfer = create_transfer(
            from_warehouse=self.pune,
            to_warehouse=self.che,
            part=self.part,
            quantity=50,
            reason=rec.reason
        )
        rec.transfer = transfer
        rec.save()

        # 1. Approve
        approve_transfer(transfer)
        self.inv_pune.refresh_from_db()
        self.assertEqual(self.inv_pune.on_hand, 120)  # No stock change on approval

        # 2. Dispatch
        dispatch_transfer(transfer)
        self.inv_pune.refresh_from_db()
        self.inv_che.refresh_from_db()

        self.assertEqual(self.inv_pune.on_hand, 70)
        self.assertEqual(self.inv_che.in_transit, 50)
        self.assertEqual(self.inv_che.on_hand, 28)

        # 3. Receive
        receive_transfer(transfer)
        self.inv_pune.refresh_from_db()
        self.inv_che.refresh_from_db()

        self.assertEqual(self.inv_pune.on_hand, 70)
        self.assertEqual(self.inv_che.on_hand, 78)
        self.assertEqual(self.inv_che.in_transit, 0)
        self.assertEqual(self.inv_che.reserved, 10)
        self.assertEqual(self.inv_che.available_stock, 68)

        # 4. Recommendation & risk updated
        rec.refresh_from_db()
        self.assertEqual(rec.status, 'COMPLETED')


class RBACPermissionsAndNotificationTests(TestCase):
    def setUp(self):
        from parts.services.rbac_service import is_manager, is_operator, setup_roles_and_permissions, ROLE_MANAGER, ROLE_OPERATOR
        from django.contrib.auth.models import Group
        setup_roles_and_permissions()

        self.superuser = User.objects.create_superuser(username='admin', password='password')
        self.manager_user = User.objects.create_user(username='manager', password='password')
        self.operator_user = User.objects.create_user(username='operator', password='password')
        self.viewer_user = User.objects.create_user(username='viewer', password='password')

        manager_group = Group.objects.get(name=ROLE_MANAGER)
        operator_group = Group.objects.get(name=ROLE_OPERATOR)

        self.manager_user.groups.add(manager_group)
        self.operator_user.groups.add(operator_group)

        self.che = Warehouse.objects.create(name="Chennai PDC")
        self.part = Part.objects.create(sku="CAT-HYD-002", name="Seal Kit")

    def test_rbac_permission_helpers(self):
        from parts.services.rbac_service import is_manager, is_operator
        self.assertTrue(is_manager(self.superuser))
        self.assertTrue(is_manager(self.manager_user))
        self.assertFalse(is_manager(self.operator_user))
        self.assertFalse(is_manager(self.viewer_user))

        self.assertTrue(is_operator(self.manager_user))
        self.assertTrue(is_operator(self.operator_user))
        self.assertFalse(is_operator(self.viewer_user))

    def test_notification_deduplication_and_resolution(self):
        # 1. Create initial notification
        n1 = create_or_update_notification(
            title="Stockout Alert",
            message="Initial stock low",
            notification_type="CRITICAL_STOCKOUT",
            part=self.part,
            warehouse=self.che
        )
        # 2. Duplicate call should update message and return existing active notification
        n2 = create_or_update_notification(
            title="Stockout Alert",
            message="Updated stock low message",
            notification_type="CRITICAL_STOCKOUT",
            part=self.part,
            warehouse=self.che
        )
        self.assertEqual(n1.id, n2.id)
        self.assertEqual(n2.message, "Updated stock low message")
        self.assertEqual(get_unread_notifications().count(), 1)


class EndToEndCoreFlowIntegrationTests(TestCase):
    def setUp(self):
        self.che = Warehouse.objects.create(name="Chennai PDC", location="Chennai")
        self.pune = Warehouse.objects.create(name="Pune Depot", location="Pune")
        self.dealer = Dealer.objects.create(name="Demo Dealer TN", region="South")

        self.seal_kit = Part.objects.create(
            sku="CAT-HYD-002",
            name="Hydraulic Pump Seal Kit",
            category="Hydraulic",
            reorder_level=50,
            criticality="HIGH",
            unit_cost=2500.00,
            supplier_lead_time_days=20,
            safety_stock=30
        )

        # Seed initial inventory state:
        # Chennai: On Hand 28, Reserved 0, Available 28
        self.inv_che = get_or_create_inventory(self.che, self.seal_kit)
        self.inv_che.on_hand = 28
        self.inv_che.reserved = 0
        self.inv_che.save()

        # Pune: On Hand 120, Reserved 0, Available 120
        self.inv_pune = get_or_create_inventory(self.pune, self.seal_kit)
        self.inv_pune.on_hand = 120
        self.inv_pune.reserved = 0
        self.inv_pune.save()

        # Seed 30 days demand history to produce forecast ~85 units/30d
        from datetime import date, timedelta
        today = date.today()
        for i in range(30, 0, -1):
            DemandHistory.objects.create(
                part=self.seal_kit, warehouse=self.che, date=today - timedelta(days=i), quantity_demanded=3
            )

    def test_complete_end_to_end_core_flow(self):
        # 1. Dealer Order places order for 10 units
        order = create_dealer_order(
            dealer=self.dealer,
            warehouse=self.che,
            items_data=[{'part': self.seal_kit, 'quantity': 10}]
        )
        self.inv_che.refresh_from_db()
        # 2. Reservation: On Hand = 28, Reserved = 10, Available = 18
        self.assertEqual(self.inv_che.on_hand, 28)
        self.assertEqual(self.inv_che.reserved, 10)
        self.assertEqual(self.inv_che.available_stock, 18)

        # 3. Risk Detection: Evaluates stockout risk for Chennai (Available 18 vs Lead-time demand ~56.7 units)
        risk_before = calculate_stockout_risk(self.seal_kit, self.che)
        self.assertTrue(risk_before['risk_score'] >= 81)
        self.assertEqual(risk_before['risk_level'], 'Critical')

        # Create active notification
        notif = create_or_update_notification(
            title=f"CRITICAL STOCKOUT RISK: {self.seal_kit.name}",
            message=risk_before['explanation'],
            notification_type='CRITICAL_STOCKOUT',
            part=self.seal_kit,
            warehouse=self.che
        )
        self.assertEqual(get_unread_notifications().count(), 1)

        # 4. Recommendation Engine: Generates TRANSFER recommendation from Pune to Chennai
        rec = generate_recommendation_for_part_warehouse(self.seal_kit, self.che)
        self.assertEqual(rec.recommendation_type, 'TRANSFER')
        self.assertEqual(rec.source_warehouse, self.pune)
        self.assertEqual(rec.target_warehouse, self.che)

        # 5. Transfer Approval: Create and approve stock transfer
        transfer = create_transfer(
            from_warehouse=self.pune,
            to_warehouse=self.che,
            part=self.seal_kit,
            quantity=rec.quantity,
            reason=rec.reason
        )
        rec.transfer = transfer
        rec.save()

        approve_transfer(transfer)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, 'APPROVED')

        # 6. Dispatch Transfer: Pune On Hand decreases by transfer qty, Chennai In Transit increases
        dispatch_transfer(transfer)
        self.inv_pune.refresh_from_db()
        self.inv_che.refresh_from_db()

        self.assertEqual(self.inv_pune.on_hand, 120 - rec.quantity)
        self.assertEqual(self.inv_che.in_transit, rec.quantity)

        # 7. Receive Transfer: Chennai In Transit decreases, Chennai On Hand increases
        receive_transfer(transfer)
        self.inv_che.refresh_from_db()
        self.inv_pune.refresh_from_db()

        self.assertEqual(self.inv_che.on_hand, 28 + rec.quantity)
        self.assertEqual(self.inv_che.reserved, 10)
        self.assertEqual(self.inv_che.available_stock, 18 + rec.quantity)
        self.assertEqual(self.inv_che.in_transit, 0)

        # 8. Risk Recalculation & Notification Resolution
        risk_after = calculate_stockout_risk(self.seal_kit, self.che)
        self.assertTrue(risk_after['risk_score'] < risk_before['risk_score'])
        self.assertIn(risk_after['risk_level'], ['Low', 'Medium'])

        # Notification auto-resolved
        notif.refresh_from_db()
        self.assertTrue(notif.is_resolved)
        self.assertEqual(get_unread_notifications().count(), 0)

        # Recommendation completed
        rec.refresh_from_db()
        self.assertEqual(rec.status, 'COMPLETED')


