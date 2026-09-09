from rest_framework import serializers
from .models import (
    Warehouse, Part, Inventory, InventoryTransaction, Dealer, Order, OrderItem,
    DemandHistory, ForecastResult, StockTransfer, Recommendation, Notification, AuditLog
)


class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = ['id', 'name', 'location', 'code']


class PartSerializer(serializers.ModelSerializer):
    class Meta:
        model = Part
        fields = [
            'id', 'sku', 'name', 'category', 'reorder_level', 'criticality',
            'unit_cost', 'supplier_lead_time_days', 'supplier_name', 'safety_stock', 'maximum_stock'
        ]


class InventorySerializer(serializers.ModelSerializer):
    part = PartSerializer(read_only=True)
    warehouse = WarehouseSerializer(read_only=True)
    available_stock = serializers.IntegerField(read_only=True)
    inventory_position = serializers.IntegerField(read_only=True)
    calculated_status = serializers.CharField(read_only=True)
    total_value = serializers.FloatField(read_only=True)

    class Meta:
        model = Inventory
        fields = [
            'id', 'part', 'warehouse', 'on_hand', 'reserved', 'damaged', 'available',
            'incoming', 'in_transit', 'safety_stock', 'reorder_level', 'maximum_stock',
            'available_stock', 'inventory_position', 'calculated_status', 'total_value'
        ]


class InventoryTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryTransaction
        fields = [
            'id', 'inventory', 'transaction_type', 'quantity', 'reference_type',
            'reference_id', 'reference_line_id', 'notes', 'created_at', 'performed_by'
        ]


class DealerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dealer
        fields = ['id', 'name', 'region']


class OrderItemSerializer(serializers.ModelSerializer):
    part = PartSerializer(read_only=True)

    class Meta:
        model = OrderItem
        fields = [
            'id', 'part', 'quantity_ordered', 'quantity_allocated',
            'quantity_fulfilled', 'quantity_backordered'
        ]


class OrderSerializer(serializers.ModelSerializer):
    dealer = DealerSerializer(read_only=True)
    warehouse = WarehouseSerializer(read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'dealer', 'warehouse', 'priority', 'status',
            'expected_fulfillment_date', 'created_at', 'fulfilled', 'items'
        ]


class ForecastResultSerializer(serializers.ModelSerializer):
    part = PartSerializer(read_only=True)
    warehouse = WarehouseSerializer(read_only=True)

    class Meta:
        model = ForecastResult
        fields = [
            'id', 'part', 'warehouse', 'forecast_date', 'forecast_horizon',
            'predicted_demand', 'forecasting_method', 'confidence', 'confidence_score'
        ]


class StockTransferSerializer(serializers.ModelSerializer):
    from_warehouse = WarehouseSerializer(read_only=True)
    to_warehouse = WarehouseSerializer(read_only=True)
    part = PartSerializer(read_only=True)

    class Meta:
        model = StockTransfer
        fields = [
            'id', 'reference', 'from_warehouse', 'to_warehouse', 'part',
            'quantity', 'status', 'estimated_transit_days', 'actual_transit_days',
            'reason', 'created_at', 'updated_at'
        ]


class RecommendationSerializer(serializers.ModelSerializer):
    part = PartSerializer(read_only=True)
    warehouse = WarehouseSerializer(read_only=True)
    source_warehouse = WarehouseSerializer(read_only=True)
    target_warehouse = WarehouseSerializer(read_only=True)
    transfer = StockTransferSerializer(read_only=True)

    class Meta:
        model = Recommendation
        fields = [
            'id', 'part', 'warehouse', 'recommendation_type', 'source_warehouse',
            'target_warehouse', 'quantity', 'risk_score', 'confidence', 'priority',
            'status', 'reason', 'transfer', 'created_at'
        ]


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            'id', 'title', 'message', 'notification_type', 'link',
            'is_read', 'is_resolved', 'created_at'
        ]


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = ['id', 'action', 'user', 'details', 'created_at']
