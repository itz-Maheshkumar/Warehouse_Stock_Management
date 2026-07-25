from rest_framework import serializers
from .models import Part, Inventory, Warehouse, Dealer, Order


class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = ['id', 'name', 'location']


class PartSerializer(serializers.ModelSerializer):
    class Meta:
        model = Part
        fields = ['id', 'sku', 'name', 'category', 'reorder_level', 'criticality']


class InventorySerializer(serializers.ModelSerializer):
    part = PartSerializer(read_only=True)
    warehouse = WarehouseSerializer(read_only=True)

    class Meta:
        model = Inventory
        fields = ['id', 'part', 'warehouse', 'available', 'reserved', 'incoming']


class DealerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dealer
        fields = ['id', 'name', 'region']


class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ['id', 'dealer', 'part', 'quantity', 'created_at', 'fulfilled']
