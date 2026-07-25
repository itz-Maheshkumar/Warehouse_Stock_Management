from django.urls import path
from . import views

app_name = 'parts_frontend'

urlpatterns = [
    path('', views.login_view, name='login'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('inventory/', views.inventory_list, name='inventory'),
    path('parts/<int:pk>/', views.part_detail, name='part_detail'),
    path('risks/', views.risk_list, name='risks'),
    path('recommendations/', views.recommendations_list, name='recommendations'),
    path('orders/', views.orders_list, name='orders'),
    path('forecast/', views.forecast_view, name='forecast'),
    path('warehouses/', views.warehouses_list, name='warehouses'),
    path('reports/', views.reports_view, name='reports'),
    path('accounts/login/', views.login_view, name='login'),
    path('accounts/logout/', views.logout_view, name='logout'),
]
