from django.db import models


class Warehouse(models.Model):
    name = models.CharField(max_length=200)
    location = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.name


class Part(models.Model):
    sku = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=100, blank=True)
    reorder_level = models.PositiveIntegerField(default=0)
    criticality = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return f"{self.sku} - {self.name}"


class Inventory(models.Model):
    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name='inventories')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='inventories')
    available = models.IntegerField(default=0)
    reserved = models.IntegerField(default=0)
    incoming = models.IntegerField(default=0)

    class Meta:
        unique_together = ('part', 'warehouse')

    def __str__(self):
        return f"{self.part.sku} @ {self.warehouse.name}"


class Dealer(models.Model):
    name = models.CharField(max_length=200)
    region = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.name


class Order(models.Model):
    dealer = models.ForeignKey(Dealer, on_delete=models.CASCADE)
    part = models.ForeignKey(Part, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    fulfilled = models.BooleanField(default=False)

    def __str__(self):
        return f"Order {self.id} - {self.dealer.name} - {self.part.sku} x{self.quantity}"
