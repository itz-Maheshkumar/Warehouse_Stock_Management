from django.urls import path
from . import views

urlpatterns = [
    path('parts/', views.PartListCreateView.as_view(), name='part-list'),
    path('parts/<int:pk>/', views.PartDetailView.as_view(), name='part-detail'),
    path('inventory/', views.InventoryListView.as_view(), name='inventory-list'),
    path('warehouses/', views.WarehouseListView.as_view(), name='warehouse-list'),
    path('orders/', views.OrderListCreateView.as_view(), name='order-list'),
    path('dealers/', views.DealerListCreateView.as_view(), name='dealer-list'),
]
