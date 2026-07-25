from django.contrib import admin
from .models import Warehouse, Part, Inventory, Dealer, Order


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ('name', 'location')


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display = ('sku', 'name', 'category', 'reorder_level', 'criticality')
    search_fields = ('sku', 'name')


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ('part', 'warehouse', 'available', 'reserved', 'incoming')
    list_filter = ('warehouse',)


@admin.register(Dealer)
class DealerAdmin(admin.ModelAdmin):
    list_display = ('name', 'region')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('dealer', 'part', 'quantity', 'created_at', 'fulfilled')
    list_filter = ('fulfilled',)
