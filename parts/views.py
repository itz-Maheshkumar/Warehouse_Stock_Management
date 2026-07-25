import logging
from rest_framework import generics
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Sum
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import user_passes_test
from .models import Part, Inventory, Warehouse, Dealer, Order
from .serializers import PartSerializer, InventorySerializer, WarehouseSerializer, DealerSerializer, OrderSerializer
import random
from datetime import datetime, timedelta

superuser_required = user_passes_test(lambda u: u.is_superuser, login_url='parts_frontend:login')


# ---- API views (existing) ----
class PartListCreateView(generics.ListCreateAPIView):
    queryset = Part.objects.all().order_by('sku')
    serializer_class = PartSerializer


class PartDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Part.objects.all()
    serializer_class = PartSerializer


class InventoryListView(generics.ListAPIView):
    queryset = Inventory.objects.select_related('part', 'warehouse').all()
    serializer_class = InventorySerializer


class WarehouseListView(generics.ListCreateAPIView):
    queryset = Warehouse.objects.all()
    serializer_class = WarehouseSerializer


class OrderListCreateView(generics.ListCreateAPIView):
    queryset = Order.objects.all().order_by('-created_at')
    serializer_class = OrderSerializer


class DealerListCreateView(generics.ListCreateAPIView):
    queryset = Dealer.objects.all()
    serializer_class = DealerSerializer


# ---- Frontend views (server-rendered pages) ----
logger = logging.getLogger(__name__)

def _kpi_values():
    total_parts = Part.objects.count()
    inventory_value_inr = 42000000  # ₹4.2 Cr placeholder
    critical_parts = Part.objects.filter(criticality__iexact='critical').count()
    high_risk_parts = 28  # placeholder
    open_orders = Order.objects.filter(fulfilled=False).count()
    pending_recs = 19
    return {
        'total_parts': total_parts or 250,
        'inventory_value': inventory_value_inr,
        'critical_parts': critical_parts or 12,
        'high_risk_parts': high_risk_parts,
        'open_orders': open_orders,
        'pending_recommendations': pending_recs,
    }


@superuser_required
def dashboard(request):
    kpis = _kpi_values()

    # Inventory health breakdown mock
    health = {'healthy': 182, 'low': 40, 'critical': 28}

    # Stockout alerts: derive from inventories and parts where possible, otherwise mock
    alerts = []
    inventories = Inventory.objects.select_related('part', 'warehouse').all()[:10]
    if inventories:
        for inv in inventories:
            forecast = random.randint(20, 120)
            risk = min(99, int((forecast - inv.available) / max(1, forecast) * 100))
            level = 'Low'
            if risk >= 85:
                level = 'Critical'
            elif risk >= 60:
                level = 'High'
            elif risk >= 40:
                level = 'Medium'
            alerts.append({
                'part_name': inv.part.name,
                'warehouse': inv.warehouse.name,
                'available': inv.available,
                'forecast': forecast,
                'risk_percent': risk,
                'risk_level': level,
                'part_id': inv.part.id,
            })
    else:
        # fallback mock data
        alerts = [
            {'part_name': 'Hydraulic Pump Seal Kit', 'warehouse': 'Chennai', 'available': 18, 'forecast': 85, 'risk_percent': 91, 'risk_level': 'Critical', 'part_id': 2},
            {'part_name': 'Track Roller Assembly', 'warehouse': 'Pune', 'available': 5, 'forecast': 15, 'risk_percent': 88, 'risk_level': 'Critical', 'part_id': 4},
            {'part_name': 'Engine Gasket Kit', 'warehouse': 'Delhi NCR', 'available': 12, 'forecast': 40, 'risk_percent': 72, 'risk_level': 'High', 'part_id': 5},
            {'part_name': 'Fuel Filter', 'warehouse': 'Bengaluru', 'available': 80, 'forecast': 100, 'risk_percent': 55, 'risk_level': 'Medium', 'part_id': 3},
        ]

    # Recommendations mock
    recommendations = [
        {'type': 'REORDER', 'part': 'Hydraulic Pump Seal Kit', 'qty': 100, 'warehouse': 'Chennai'},
        {'type': 'TRANSFER', 'part': 'Track Roller Assembly', 'qty': 20, 'warehouse': 'Pune → Chennai'},
        {'type': 'EXPEDITE', 'part': 'Engine Gasket Kit', 'qty': None, 'warehouse': 'Supplier: ABC Components'},
        {'type': 'HOLD', 'part': 'Engine Oil Filter', 'qty': None, 'warehouse': 'Inventory healthy'},
    ]

    # Regional inventory bar chart data (mocked)
    regions = ['Chennai', 'Pune', 'Delhi NCR', 'Bengaluru']
    values = [random.randint(2000000, 15000000) for _ in regions]

    # Recent dealer orders (mock or from DB)
    recent_orders = Order.objects.select_related('dealer', 'part').order_by('-created_at')[:8]

    logger.info('Rendering dashboard', extra={'path': request.path, 'user': request.user.username if request.user.is_authenticated else 'anonymous'})
    context = {
        'kpis': kpis,
        'health': health,
        'alerts': alerts,
        'recommendations': recommendations,
        'regions': regions,
        'region_values': values,
        'recent_orders': recent_orders,
    }
    return render(request, 'dashboard/index.html', context)


@superuser_required
def inventory_list(request):
    qs = Inventory.objects.select_related('part', 'warehouse')
    # Basic filters from GET
    q = request.GET.get('q')
    warehouse = request.GET.get('warehouse')
    if q:
        qs = qs.filter(part__name__icontains=q) | qs.filter(part__sku__icontains=q)
    if warehouse:
        qs = qs.filter(warehouse__name__icontains=warehouse)

    page = request.GET.get('page', 1)
    inventories = qs.order_by('-available')[:50]
    logger.info('Rendering inventory list', extra={'path': request.path, 'query': request.GET.dict()})
    context = {'inventories': inventories}
    return render(request, 'inventory/list.html', context)


@superuser_required
def part_detail(request, pk):
    part = get_object_or_404(Part, pk=pk)
    inventories = Inventory.objects.filter(part=part).select_related('warehouse')

    # demand history mock (6 months)
    now = datetime.now()
    months = []
    demand = []
    for i in range(6, 0, -1):
        dt = (now - timedelta(days=30 * i))
        months.append(dt.strftime('%b %Y'))
        demand.append(random.randint(10, 120))
    forecast = [int(v * 1.2) for v in demand]

    # mock risk for this part
    total_available = inventories.aggregate(total=Sum('available'))['total'] or 0
    forecast_next = sum(forecast[:1])
    risk_score = min(99, int((forecast_next - total_available) / max(1, forecast_next) * 100)) if forecast_next else 0
    risk_level = 'Low'
    if risk_score >= 85:
        risk_level = 'Critical'
    elif risk_score >= 60:
        risk_level = 'High'
    elif risk_score >= 40:
        risk_level = 'Medium'

    recommendation = None
    # special-case demo part
    if 'Hydraulic' in part.name or 'Seal' in part.name or part.sku == 'CAT-HYD-002':
        recommendation = {
            'action': 'TRANSFER',
            'from': 'Pune',
            'to': 'Chennai',
            'qty': 50,
            'reason': 'Chennai is at critical stockout risk; Pune has sufficient inventory.'
        }

    logger.info('Rendering part detail', extra={'path': request.path, 'part_id': pk, 'risk_score': risk_score})
    context = {
        'part': part,
        'inventories': inventories,
        'months': months,
        'demand': demand,
        'forecast': forecast,
        'risk_score': risk_score,
        'risk_level': risk_level,
        'recommendation': recommendation,
    }
    return render(request, 'parts/detail.html', context)


@superuser_required
def risk_list(request):
    inventories = Inventory.objects.select_related('part', 'warehouse').all()[:100]
    rows = []
    for inv in inventories:
        forecast = random.randint(20, 120)
        risk = min(99, int((forecast - inv.available) / max(1, forecast) * 100))
        rows.append({
            'part': inv.part,
            'warehouse': inv.warehouse,
            'available': inv.available,
            'forecast': forecast,
            'lead_time': random.randint(7, 30),
            'criticality': inv.part.criticality or 'Medium',
            'risk_score': risk,
            'risk_level': 'Critical' if risk >= 85 else ('High' if risk >= 60 else ('Medium' if risk >= 40 else 'Low')),
        })
    logger.info('Rendering risk list', extra={'path': request.path, 'rows': len(rows)})
    return render(request, 'risks/index.html', {'rows': rows})


@superuser_required
def recommendations_list(request):
    # Mock a few recommendations and also derive one from data
    recommendations = [
        {'id': 1, 'type': 'TRANSFER', 'part': 'Hydraulic Pump Seal Kit', 'from': 'Pune', 'to': 'Chennai', 'qty': 50, 'reason': 'Pune has surplus', 'risk_score': 91, 'confidence': 'High'},
        {'id': 2, 'type': 'REORDER', 'part': 'Fuel Filter', 'from': None, 'to': 'Chennai', 'qty': 200, 'reason': '30-day forecast high', 'risk_score': 65, 'confidence': 'Medium'},
    ]
    logger.info('Rendering recommendations list', extra={'path': request.path, 'recommendations': len(recommendations)})
    return render(request, 'recommendations/index.html', {'recommendations': recommendations})


@superuser_required
def orders_list(request):
    orders = Order.objects.select_related('dealer', 'part').order_by('-created_at')[:50]
    logger.info('Rendering orders list', extra={'path': request.path, 'orders': len(orders)})
    return render(request, 'orders/list.html', {'orders': orders})


@superuser_required
def forecast_view(request):
    parts = Part.objects.all()[:50]
    # mock chart data (one example)
    labels = ['-30d', '-20d', '-10d', 'Today', '+10d', '+20d', '+30d']
    historical = [random.randint(10, 80) for _ in labels[:4]]
    forecast = [random.randint(20, 100) for _ in labels[4:]]
    logger.info('Rendering forecast view', extra={'path': request.path, 'parts': len(parts)})
    return render(request, 'forecasting/index.html', {'parts': parts, 'labels': labels, 'historical': historical, 'forecast': forecast})


@superuser_required
def warehouses_list(request):
    warehouses = Warehouse.objects.all()
    # mock inventory values
    data = []
    for w in warehouses:
        data.append({'warehouse': w, 'value': random.randint(1000000, 15000000), 'parts': Part.objects.count() // max(1, warehouses.count())})
    logger.info('Rendering warehouses list', extra={'path': request.path, 'warehouses': len(data)})
    return render(request, 'warehouses/list.html', {'warehouses': data})


@superuser_required
def reports_view(request):
    # simple charts mocked
    logger.info('Rendering reports view', extra={'path': request.path})
    return render(request, 'reports/index.html', {})


def login_view(request):
    next_page = request.GET.get('next', '') or request.POST.get('next', '')
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        User = get_user_model()
        try:
            user_exists = User.objects.get(username=username)
        except User.DoesNotExist:
            messages.error(request, "User doesn't exist.")
            user_exists = None

        if user_exists:
            user = authenticate(request, username=username, password=password)
            if user is not None and user.is_superuser:
                login(request, user)
                return redirect(next_page or 'parts_frontend:dashboard')
            elif user is not None:
                messages.error(request, 'Only superusers may sign in.')
            else:
                messages.error(request, 'Username or password incorrect.')

    logger.info('Rendering login page', extra={'path': request.path})
    return render(request, 'registration/login.html', {'next': next_page})


def logout_view(request):
    logout(request)
    return redirect('parts_frontend:login')
