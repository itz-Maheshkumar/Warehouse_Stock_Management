from django.db import models
from django.db.models import F, Q, CheckConstraint, UniqueConstraint
from django.contrib.auth import get_user_model

User = get_user_model()


class Warehouse(models.Model):
    name = models.CharField(max_length=200)
    location = models.CharField(max_length=200, blank=True)
    code = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return self.name


class Part(models.Model):
    CRITICALITY_CHOICES = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('CRITICAL', 'Critical'),
    ]

    sku = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=100, blank=True)
    reorder_level = models.PositiveIntegerField(default=0)
    criticality = models.CharField(max_length=50, choices=CRITICALITY_CHOICES, default='MEDIUM')
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=2500.00)
    supplier_lead_time_days = models.IntegerField(default=20)
    supplier_name = models.CharField(max_length=200, default='ABC Components')
    safety_stock = models.IntegerField(default=30)
    maximum_stock = models.IntegerField(default=200)

    def __str__(self):
        return f"{self.sku} - {self.name}"


class Inventory(models.Model):
    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name='inventories')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='inventories')
    on_hand = models.IntegerField(default=0)
    reserved = models.IntegerField(default=0)
    damaged = models.IntegerField(default=0)
    available = models.IntegerField(default=0)
    incoming = models.IntegerField(default=0)
    in_transit = models.IntegerField(default=0)
    safety_stock = models.IntegerField(default=0)
    reorder_level = models.IntegerField(default=0)
    maximum_stock = models.IntegerField(default=0)

    class Meta:
        unique_together = ('part', 'warehouse')
        constraints = [
            CheckConstraint(
                condition=Q(on_hand__gte=F('reserved') + F('damaged')),
                name='check_on_hand_gte_reserved_damaged'
            ),
            CheckConstraint(
                condition=Q(on_hand__gte=0, reserved__gte=0, damaged__gte=0, incoming__gte=0, in_transit__gte=0),
                name='check_non_negative_inventory_counts'
            )
        ]

    def save(self, *args, **kwargs):
        # Always maintain available = max(0, on_hand - reserved - damaged)
        self.available = max(0, self.on_hand - self.reserved - self.damaged)
        if not self.safety_stock and self.part_id:
            self.safety_stock = self.part.safety_stock
        if not self.reorder_level and self.part_id:
            self.reorder_level = self.part.reorder_level
        if not self.maximum_stock and self.part_id:
            self.maximum_stock = self.part.maximum_stock
        super().save(*args, **kwargs)

    @property
    def available_stock(self):
        return max(0, self.on_hand - self.reserved - self.damaged)

    @property
    def inventory_position(self):
        return self.available_stock + self.in_transit

    @property
    def total_value(self):
        return float(self.on_hand) * float(self.part.unit_cost if self.part else 0)

    @property
    def calculated_status(self):
        avail = self.available_stock
        eff_safety = self.safety_stock or (self.part.safety_stock if self.part else 0)
        eff_reorder = self.reorder_level or (self.part.reorder_level if self.part else 0)
        eff_max = self.maximum_stock or (self.part.maximum_stock if self.part else 0)

        if avail <= max(1, int(eff_safety * 0.65)):
            return 'Critical'
        elif avail <= eff_reorder:
            return 'Low'
        elif eff_max > 0 and self.on_hand >= eff_max:
            return 'Overstocked'
        return 'Healthy'

    def __str__(self):
        return f"{self.part.sku} @ {self.warehouse.name}"


class InventoryTransaction(models.Model):
    TRANSACTION_TYPES = [
        ('RECEIPT', 'Receipt'),
        ('RESERVATION', 'Reservation'),
        ('RELEASE', 'Release'),
        ('SHIPMENT', 'Shipment'),
        ('TRANSFER_OUT', 'Transfer Out'),
        ('TRANSFER_IN', 'Transfer In'),
        ('ADJUSTMENT', 'Adjustment'),
        ('DAMAGE', 'Damage'),
        ('RETURN', 'Return'),
    ]

    inventory = models.ForeignKey(Inventory, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=30, choices=TRANSACTION_TYPES)
    quantity = models.IntegerField()
    reference_type = models.CharField(max_length=100)
    reference_id = models.CharField(max_length=100)
    reference_line_id = models.CharField(max_length=100, blank=True, default='')
    performed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=['reference_type', 'reference_id', 'transaction_type', 'reference_line_id'],
                name='unique_transaction_event'
            )
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.transaction_type} {self.quantity} ({self.inventory.part.sku} @ {self.inventory.warehouse.name})"


class Dealer(models.Model):
    name = models.CharField(max_length=200)
    region = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.name


class Order(models.Model):
    PRIORITY_CHOICES = [
        ('NORMAL', 'Normal'),
        ('URGENT', 'Urgent'),
        ('CRITICAL', 'Critical'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PARTIALLY_FULFILLED', 'Partially Fulfilled'),
        ('FULFILLED', 'Fulfilled'),
        ('BACKORDERED', 'Backordered'),
        ('CANCELLED', 'Cancelled'),
    ]

    dealer = models.ForeignKey(Dealer, on_delete=models.CASCADE, related_name='orders')
    warehouse = models.ForeignKey(Warehouse, null=True, blank=True, on_delete=models.SET_NULL, related_name='orders')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='NORMAL')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='PENDING')
    expected_fulfillment_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Legacy backward-compatibility fields (used when order has a single line item)
    part = models.ForeignKey(Part, null=True, blank=True, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    fulfilled = models.BooleanField(default=False)

    def __str__(self):
        return f"Order #{self.id} - {self.dealer.name}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    part = models.ForeignKey(Part, on_delete=models.CASCADE)
    quantity_ordered = models.PositiveIntegerField()
    quantity_allocated = models.PositiveIntegerField(default=0)
    quantity_fulfilled = models.PositiveIntegerField(default=0)
    quantity_backordered = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"OrderItem #{self.id} (Order #{self.order_id} - {self.part.sku} x{self.quantity_ordered})"


class DemandHistory(models.Model):
    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name='demand_histories')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='demand_histories')
    date = models.DateField()
    quantity_demanded = models.PositiveIntegerField()

    class Meta:
        unique_together = ('part', 'warehouse', 'date')
        ordering = ['date']

    def __str__(self):
        return f"Demand {self.part.sku} @ {self.warehouse.name} on {self.date}: {self.quantity_demanded}"


class ForecastResult(models.Model):
    HORIZON_CHOICES = [
        (7, '7 Days'),
        (30, '30 Days'),
        (90, '90 Days'),
    ]

    CONFIDENCE_CHOICES = [
        ('HIGH', 'High'),
        ('MEDIUM', 'Medium'),
        ('LOW', 'Low'),
    ]

    part = models.ForeignKey(Part, on_delete=models.CASCADE)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE)
    forecast_date = models.DateField()
    forecast_horizon = models.IntegerField(choices=HORIZON_CHOICES, default=30)
    predicted_demand = models.FloatField()
    forecasting_method = models.CharField(max_length=50, default='WEIGHTED_MOVING_AVERAGE')
    confidence = models.CharField(max_length=20, choices=CONFIDENCE_CHOICES, default='HIGH')
    confidence_score = models.FloatField(default=0.85)
    generated_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Forecast {self.part.sku} @ {self.warehouse.name} (+{self.forecast_horizon}d): {self.predicted_demand}"


class StockTransfer(models.Model):
    STATUS_CHOICES = [
        ('RECOMMENDED', 'Recommended'),
        ('PENDING_APPROVAL', 'Pending Approval'),
        ('APPROVED', 'Approved'),
        ('DISPATCHED', 'Dispatched'),
        ('RECEIVED', 'Received'),
        ('REJECTED', 'Rejected'),
        ('CANCELLED', 'Cancelled'),
    ]

    reference = models.CharField(max_length=64, unique=True)
    from_warehouse = models.ForeignKey(Warehouse, related_name='transfers_sent', on_delete=models.CASCADE)
    to_warehouse = models.ForeignKey(Warehouse, related_name='transfers_received', on_delete=models.CASCADE)
    part = models.ForeignKey(Part, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='PENDING_APPROVAL')
    estimated_transit_days = models.IntegerField(default=5)
    actual_transit_days = models.IntegerField(null=True, blank=True)
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Transfer {self.reference} ({self.quantity} x {self.part.sku}: {self.from_warehouse.name} -> {self.to_warehouse.name})"


class Recommendation(models.Model):
    TYPE_CHOICES = [
        ('HOLD', 'Hold'),
        ('TRANSFER', 'Transfer'),
        ('REORDER', 'Reorder'),
        ('EXPEDITE', 'Expedite'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('EXPIRED', 'Expired'),
        ('COMPLETED', 'Completed'),
    ]

    part = models.ForeignKey(Part, on_delete=models.CASCADE)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE)
    recommendation_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    source_warehouse = models.ForeignKey(Warehouse, null=True, blank=True, related_name='recommendations_as_source', on_delete=models.SET_NULL)
    target_warehouse = models.ForeignKey(Warehouse, null=True, blank=True, related_name='recommendations_as_target', on_delete=models.SET_NULL)
    quantity = models.PositiveIntegerField(null=True, blank=True)
    risk_score = models.IntegerField(default=0)
    confidence = models.CharField(max_length=20, default='HIGH')
    priority = models.CharField(max_length=20, default='MEDIUM')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    reason = models.TextField(blank=True)
    transfer = models.OneToOneField(StockTransfer, null=True, blank=True, on_delete=models.SET_NULL, related_name='origin_recommendation')
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(User, null=True, blank=True, related_name='approved_recommendations', on_delete=models.SET_NULL)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(User, null=True, blank=True, related_name='rejected_recommendations', on_delete=models.SET_NULL)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Rec {self.recommendation_type} - {self.part.sku} @ {self.warehouse.name} ({self.status})"


class Notification(models.Model):
    TYPE_CHOICES = [
        ('CRITICAL_STOCKOUT', 'Critical Stockout'),
        ('LOW_INVENTORY', 'Low Inventory'),
        ('ORDER_DELAY', 'Order Delay'),
        ('TRANSFER_REQUIRED', 'Transfer Required'),
        ('SUPPLIER_DELAY', 'Supplier Delay'),
    ]

    title = models.CharField(max_length=255)
    message = models.TextField()
    notification_type = models.CharField(max_length=50, choices=TYPE_CHOICES)
    link = models.CharField(max_length=255, blank=True)
    active_condition_key = models.CharField(max_length=255, blank=True, db_index=True)
    is_read = models.BooleanField(default=False)
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Notification [{self.notification_type}] {self.title}"


class AuditLog(models.Model):
    action = models.CharField(max_length=255)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Audit: {self.action} by {self.user} at {self.created_at}"

