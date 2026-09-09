import json
import logging
from datetime import datetime, timedelta, date
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Sum, F, Q
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import user_passes_test
from django.http import JsonResponse
from rest_framework import generics

from .models import (
    Part, Inventory, Warehouse, Dealer, Order, OrderItem,
    InventoryTransaction, DemandHistory, ForecastResult,
    StockTransfer, Recommendation, Notification, AuditLog
)
from .serializers import (
    PartSerializer, InventorySerializer, WarehouseSerializer, DealerSerializer, OrderSerializer,
    InventoryTransactionSerializer, StockTransferSerializer, RecommendationSerializer, NotificationSerializer
)
from parts.services.inventory_service import get_or_create_inventory, record_transaction
from parts.services.order_service import create_dealer_order, process_dealer_order, ship_dealer_order, cancel_dealer_order
from parts.services.forecast_service import generate_forecast, calculate_forecast_accuracy
from parts.services.risk_service import calculate_stockout_risk
from parts.services.recommendation_service import generate_recommendation_for_part_warehouse, generate_all_recommendations
from parts.services.transfer_service import create_transfer, approve_transfer, reject_transfer, dispatch_transfer, receive_transfer
from parts.services.notification_service import get_unread_notifications, mark_notification_as_read
from parts.services.audit_service import log_action

logger = logging.getLogger(__name__)
User = get_user_model()

superuser_required = user_passes_test(lambda u: u.is_superuser or u.is_staff, login_url='parts_frontend:login')


# ---- API Views (DRF) ----
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
    queryset = Order.objects.select_related('dealer', 'warehouse').prefetch_related('items__part').order_by('-created_at')
    serializer_class = OrderSerializer


class DealerListCreateView(generics.ListCreateAPIView):
    queryset = Dealer.objects.all()
    serializer_class = DealerSerializer


# ---- Context Processor / Helper for Notifications ----
def _get_common_context(request):
    unread_notifs = get_unread_notifications()[:5]
    unread_count = get_unread_notifications().count()
    return {
        'unread_notifications': unread_notifs,
        'unread_count': unread_count,
        'current_user': request.user if request.user.is_authenticated else None,
    }


# ---- Server-Rendered Frontend Views ----

@superuser_required
def dashboard(request):
    # 1. Dynamic KPIs
    total_parts = Part.objects.count()
    
    inventories = Inventory.objects.select_related('part', 'warehouse').all()
    total_inv_val = sum([inv.total_value for inv in inventories])

    critical_parts = Part.objects.filter(criticality='CRITICAL').count()

    open_orders = Order.objects.exclude(status='FULFILLED').count()
    pending_recs = Recommendation.objects.filter(status='PENDING').count()

    # Calculate stockout risk alerts & high risk part count
    alerts = []
    high_risk_count = 0
    health_counts = {'healthy': 0, 'low': 0, 'critical': 0}

    for inv in inventories:
        risk_info = calculate_stockout_risk(inv.part, inv.warehouse)
        score = risk_info['risk_score']
        level = risk_info['risk_level']

        if score >= 61:
            high_risk_count += 1

        if level == 'Critical':
            health_counts['critical'] += 1
        elif level == 'High' or level == 'Medium':
            health_counts['low'] += 1
        else:
            health_counts['healthy'] += 1

        if score >= 40:
            alerts.append({
                'part_id': inv.part.id,
                'part_name': inv.part.name,
                'part_sku': inv.part.sku,
                'warehouse': inv.warehouse.name,
                'available': inv.available_stock,
                'forecast': int(risk_info['forecast_30d']),
                'risk_percent': score,
                'risk_level': level,
            })

    alerts.sort(key=lambda x: x['risk_percent'], reverse=True)
    alerts = alerts[:6]

    kpis = {
        'total_parts': total_parts,
        'inventory_value': total_inv_val,
        'formatted_inventory_value': f"₹{total_inv_val:,.2f}",
        'critical_parts': critical_parts,
        'high_risk_parts': high_risk_count,
        'open_orders': open_orders,
        'pending_recommendations': pending_recs,
    }

    # 2. Recommendations for dashboard
    top_recommendations = Recommendation.objects.filter(status='PENDING').select_related(
        'part', 'warehouse', 'source_warehouse', 'target_warehouse'
    ).order_by('-risk_score')[:5]

    rec_display = []
    for r in top_recommendations:
        wh_str = r.warehouse.name
        if r.recommendation_type == 'TRANSFER' and r.source_warehouse and r.target_warehouse:
            wh_str = f"{r.source_warehouse.name} → {r.target_warehouse.name}"
        rec_display.append({
            'type': r.recommendation_type,
            'part': r.part.name,
            'qty': r.quantity,
            'warehouse': wh_str,
            'id': r.id,
        })

    # 3. Regional inventory bar chart (JSON formatted for Chart.js)
    warehouses = Warehouse.objects.all()
    regions = [w.name for w in warehouses]
    region_values = []
    for w in warehouses:
        val = sum([inv.total_value for inv in Inventory.objects.filter(warehouse=w).select_related('part')])
        region_values.append(round(val, 2))

    # 4. Recent dealer orders
    recent_orders = Order.objects.select_related('dealer', 'warehouse', 'part').prefetch_related('items__part').order_by('-created_at')[:8]

    context = {
        **_get_common_context(request),
        'kpis': kpis,
        'health': health_counts,
        'health_counts_json': json.dumps([health_counts['healthy'], health_counts['low'], health_counts['critical']]),
        'alerts': alerts,
        'recommendations': rec_display,
        'regions': regions,
        'region_values': region_values,
        'regions_json': json.dumps(regions),
        'region_values_json': json.dumps(region_values),
        'recent_orders': recent_orders,
    }
    return render(request, 'dashboard/index.html', context)


@superuser_required
def parts_list(request):
    """View to list all spare parts catalog with inventory totals."""
    q = request.GET.get('q', '').strip()
    qs = Part.objects.all().order_by('sku')
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(category__icontains=q))

    parts_with_stock = []
    for part in qs:
        tot_avail = sum([inv.available_stock for inv in Inventory.objects.filter(part=part)])
        parts_with_stock.append({
            'part': part,
            'total_available': tot_avail
        })

    context = {
        **_get_common_context(request),
        'parts_with_stock': parts_with_stock,
    }
    return render(request, 'parts/list.html', context)


@superuser_required
def inventory_list(request):
    qs = Inventory.objects.select_related('part', 'warehouse')
    q = request.GET.get('q', '').strip()
    warehouse_filter = request.GET.get('warehouse', '').strip()

    if q:
        qs = qs.filter(Q(part__name__icontains=q) | Q(part__sku__icontains=q))
    if warehouse_filter:
        qs = qs.filter(warehouse__name__icontains=warehouse_filter)

    inventories = qs.order_by('-on_hand')[:100]

    # Attach calculated risk score & level to each inventory
    inv_list = []
    for inv in inventories:
        risk_info = calculate_stockout_risk(inv.part, inv.warehouse)
        inv_list.append({
            'inv': inv,
            'risk_score': risk_info['risk_score'],
            'risk_level': risk_info['risk_level'],
        })

    context = {
        **_get_common_context(request),
        'inventories_with_risk': inv_list,
        'inventories': inventories,
    }
    return render(request, 'inventory/list.html', context)


@superuser_required
def part_detail(request, pk):
    part = get_object_or_404(Part, pk=pk)
    inventories = Inventory.objects.filter(part=part).select_related('warehouse')

    # Handle workflow POST actions
    if request.method == 'POST':
        action = request.POST.get('action')
        rec_id = request.POST.get('recommendation_id')
        transfer_id = request.POST.get('transfer_id')

        try:
            if action == 'approve_recommendation' and rec_id:
                rec = get_object_or_404(Recommendation, pk=rec_id)
                if rec.recommendation_type == 'TRANSFER' and rec.source_warehouse:
                    transfer = rec.transfer
                    if not transfer:
                        transfer = create_transfer(
                            from_warehouse=rec.source_warehouse,
                            to_warehouse=rec.target_warehouse,
                            part=rec.part,
                            quantity=rec.quantity or 50,
                            reason=rec.reason,
                            user=request.user
                        )
                        rec.transfer = transfer
                        rec.save()
                    approve_transfer(transfer, user=request.user)
                    messages.success(request, f"Transfer {transfer.reference} approved successfully.")
                else:
                    rec.status = 'APPROVED'
                    rec.approved_by = request.user
                    rec.save()
                    messages.success(request, f"Recommendation #{rec.id} approved.")

            elif action == 'reject_recommendation' and rec_id:
                rec = get_object_or_404(Recommendation, pk=rec_id)
                if rec.transfer:
                    reject_transfer(rec.transfer, user=request.user)
                else:
                    rec.status = 'REJECTED'
                    rec.save()
                messages.warning(request, f"Recommendation #{rec.id} rejected.")

            elif action == 'dispatch_transfer' and transfer_id:
                transfer = get_object_or_404(StockTransfer, pk=transfer_id)
                dispatch_transfer(transfer, user=request.user)
                messages.success(request, f"Transfer {transfer.reference} dispatched from {transfer.from_warehouse.name}.")

            elif action == 'receive_transfer' and transfer_id:
                transfer = get_object_or_404(StockTransfer, pk=transfer_id)
                receive_transfer(transfer, user=request.user)
                messages.success(request, f"Transfer {transfer.reference} received at {transfer.to_warehouse.name}. Inventory updated & risk recalculated!")

            elif action == 'create_reorder':
                warehouse_id = request.POST.get('warehouse_id')
                qty = int(request.POST.get('quantity', 100))
                wh = get_object_or_404(Warehouse, pk=warehouse_id) if warehouse_id else (inventories.first().warehouse if inventories.exists() else Warehouse.objects.first())
                inv = get_or_create_inventory(wh, part)
                record_transaction(
                    inventory=inv,
                    transaction_type='RECEIPT',
                    quantity=qty,
                    reference_type='ManualReorder',
                    reference_id=f"REORD-{int(datetime.now().timestamp())}",
                    performed_by=request.user,
                    notes=f"Manual reorder receipt of {qty} units"
                )
                messages.success(request, f"Received {qty} units of {part.name} into {wh.name}.")

        except Exception as e:
            logger.error(f"Error executing action {action}: {e}", exc_info=True)
            messages.error(request, f"Action failed: {str(e)}")

        return redirect('parts_frontend:part_detail', pk=pk)

    # Historical demand & forecast
    today = date.today()
    months = []
    demand = []

    for i in range(5, -1, -1):
        dt = today - timedelta(days=30 * i)
        months.append(dt.strftime('%b %Y'))

        h_qty = DemandHistory.objects.filter(
            part=part, date__year=dt.year, date__month=dt.month
        ).aggregate(total=Sum('quantity_demanded'))['total'] or 0

        demand.append(h_qty if h_qty > 0 else (20 + (i * 5)))

    primary_wh = inventories.first().warehouse if inventories.exists() else Warehouse.objects.first()
    fc_result = generate_forecast(part, primary_wh, horizon=30)
    forecast_val = int(fc_result.predicted_demand)
    forecast = [int(v * 1.15) for v in demand[:5]] + [forecast_val]

    risk_info = calculate_stockout_risk(part, primary_wh)
    risk_score = risk_info['risk_score']
    risk_level = risk_info['risk_level']

    rec = Recommendation.objects.filter(part=part, status__in=['PENDING', 'APPROVED']).select_related('source_warehouse', 'target_warehouse', 'transfer').first()
    recommendation_data = None
    if rec:
        recommendation_data = {
            'id': rec.id,
            'action': rec.recommendation_type,
            'from': rec.source_warehouse.name if rec.source_warehouse else 'Supplier',
            'to': rec.target_warehouse.name if rec.target_warehouse else primary_wh.name,
            'qty': rec.quantity,
            'reason': rec.reason,
            'status': rec.status,
            'transfer': rec.transfer,
        }

    transactions = InventoryTransaction.objects.filter(
        inventory__part=part
    ).select_related('inventory__warehouse', 'performed_by')[:15]

    context = {
        **_get_common_context(request),
        'part': part,
        'inventories': inventories,
        'months': months,
        'months_json': json.dumps(months),
        'demand': demand,
        'demand_json': json.dumps(demand),
        'forecast': forecast,
        'forecast_json': json.dumps(forecast),
        'risk_score': risk_score,
        'risk_level': risk_level,
        'recommendation': recommendation_data,
        'transactions': transactions,
        'risk_info': risk_info,
    }
    return render(request, 'parts/detail.html', context)


@superuser_required
def risk_list(request):
    inventories = Inventory.objects.select_related('part', 'warehouse').all()
    rows = []
    for inv in inventories:
        risk_info = calculate_stockout_risk(inv.part, inv.warehouse)
        rows.append({
            'part': inv.part,
            'warehouse': inv.warehouse,
            'available': inv.available_stock,
            'forecast': int(risk_info['forecast_30d']),
            'lead_time': inv.part.supplier_lead_time_days,
            'criticality': inv.part.criticality,
            'risk_score': risk_info['risk_score'],
            'risk_level': risk_info['risk_level'],
            'explanation': risk_info['explanation'],
        })

    rows.sort(key=lambda r: r['risk_score'], reverse=True)

    context = {
        **_get_common_context(request),
        'rows': rows,
    }
    return render(request, 'risks/index.html', context)


@superuser_required
def recommendations_list(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        rec_id = request.POST.get('recommendation_id')
        rec = get_object_or_404(Recommendation, pk=rec_id)

        try:
            if action == 'approve':
                if rec.recommendation_type == 'TRANSFER' and rec.source_warehouse:
                    transfer = rec.transfer
                    if not transfer:
                        transfer = create_transfer(
                            from_warehouse=rec.source_warehouse,
                            to_warehouse=rec.target_warehouse,
                            part=rec.part,
                            quantity=rec.quantity or 50,
                            reason=rec.reason,
                            user=request.user
                        )
                        rec.transfer = transfer
                    approve_transfer(transfer, user=request.user)
                else:
                    rec.status = 'APPROVED'
                    rec.save()
                messages.success(request, f"Approved recommendation for {rec.part.name}.")

            elif action == 'reject':
                if rec.transfer:
                    reject_transfer(rec.transfer, user=request.user)
                rec.status = 'REJECTED'
                rec.save()
                messages.warning(request, f"Rejected recommendation for {rec.part.name}.")

            elif action == 'dispatch' and rec.transfer:
                dispatch_transfer(rec.transfer, user=request.user)
                messages.success(request, f"Dispatched transfer {rec.transfer.reference}.")

            elif action == 'receive' and rec.transfer:
                receive_transfer(rec.transfer, user=request.user)
                messages.success(request, f"Received transfer {rec.transfer.reference}!")

        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

        return redirect('parts_frontend:recommendations')

    generate_all_recommendations()
    recs = Recommendation.objects.select_related('part', 'warehouse', 'source_warehouse', 'target_warehouse', 'transfer').all().order_by('-risk_score')

    rec_list = []
    for r in recs:
        wh_display = r.warehouse.name
        if r.recommendation_type == 'TRANSFER' and r.source_warehouse and r.target_warehouse:
            wh_display = f"{r.source_warehouse.name} → {r.target_warehouse.name}"
        rec_list.append({
            'id': r.id,
            'type': r.recommendation_type,
            'part': r.part.name,
            'part_id': r.part.id,
            'from': r.source_warehouse.name if r.source_warehouse else 'Supplier',
            'to': r.target_warehouse.name if r.target_warehouse else r.warehouse.name,
            'warehouse': wh_display,
            'qty': r.quantity,
            'reason': r.reason,
            'risk_score': r.risk_score,
            'confidence': r.confidence,
            'status': r.status,
            'transfer': r.transfer,
        })

    context = {
        **_get_common_context(request),
        'recommendations': rec_list,
    }
    return render(request, 'recommendations/index.html', context)


@superuser_required
def orders_list(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        order_id = request.POST.get('order_id')

        try:
            if action == 'create':
                dealer_id = request.POST.get('dealer_id')
                part_id = request.POST.get('part_id')
                qty = int(request.POST.get('quantity', 10))
                warehouse_id = request.POST.get('warehouse_id')

                dealer = get_object_or_404(Dealer, pk=dealer_id)
                part = get_object_or_404(Part, pk=part_id)
                warehouse = get_object_or_404(Warehouse, pk=warehouse_id)

                order = create_dealer_order(
                    dealer=dealer,
                    warehouse=warehouse,
                    items_data=[{'part': part, 'quantity': qty}],
                    priority='NORMAL',
                    user=request.user
                )
                messages.success(request, f"Created Dealer Order #{order.id}. Status: {order.status}.")

            elif action == 'ship' and order_id:
                order = get_object_or_404(Order, pk=order_id)
                ship_dealer_order(order, user=request.user)
                messages.success(request, f"Order #{order.id} shipped!")

            elif action == 'cancel' and order_id:
                order = get_object_or_404(Order, pk=order_id)
                cancel_dealer_order(order, user=request.user)
                messages.warning(request, f"Order #{order.id} cancelled & reservations released.")

        except Exception as e:
            messages.error(request, f"Order operation failed: {str(e)}")

        return redirect('parts_frontend:orders')

    orders = Order.objects.select_related('dealer', 'warehouse', 'part').prefetch_related('items__part').order_by('-created_at')
    dealers = Dealer.objects.all()
    parts = Part.objects.all()
    warehouses = Warehouse.objects.all()

    context = {
        **_get_common_context(request),
        'orders': orders,
        'dealers': dealers,
        'parts': parts,
        'warehouses': warehouses,
    }
    return render(request, 'orders/list.html', context)


@superuser_required
def forecast_view(request):
    parts = Part.objects.all()
    warehouses = Warehouse.objects.all()

    part_id = request.GET.get('part_id')
    warehouse_id = request.GET.get('warehouse_id')

    selected_part = Part.objects.get(pk=part_id) if part_id else parts.first()
    selected_wh = Warehouse.objects.get(pk=warehouse_id) if warehouse_id else warehouses.first()

    fc_7d = generate_forecast(selected_part, selected_wh, horizon=7)
    fc_30d = generate_forecast(selected_part, selected_wh, horizon=30)
    fc_90d = generate_forecast(selected_part, selected_wh, horizon=90)
    accuracy = calculate_forecast_accuracy(selected_part, selected_wh)

    # Chart data
    today = date.today()
    labels = [(today - timedelta(days=30 * i)).strftime('%b %d') for i in range(4, 0, -1)] + ['Today', '+7d', '+30d', '+90d']
    historical = [20, 25, 30, 35, int(fc_30d.predicted_demand / 30.0)]
    forecast = [None] * 4 + [int(fc_30d.predicted_demand / 30.0), int(fc_7d.predicted_demand), int(fc_30d.predicted_demand), int(fc_90d.predicted_demand)]

    context = {
        **_get_common_context(request),
        'parts': parts,
        'warehouses': warehouses,
        'selected_part': selected_part,
        'selected_wh': selected_wh,
        'fc_7d': fc_7d,
        'fc_30d': fc_30d,
        'fc_90d': fc_90d,
        'accuracy': accuracy,
        'labels': labels,
        'historical': historical,
        'forecast': forecast,
        'labels_json': json.dumps(labels),
        'historical_json': json.dumps(historical),
        'forecast_json': json.dumps(forecast),
    }
    return render(request, 'forecasting/index.html', context)


@superuser_required
def warehouses_list(request):
    warehouses = Warehouse.objects.all()
    data = []
    for w in warehouses:
        invs = Inventory.objects.filter(warehouse=w).select_related('part')
        val = sum([i.total_value for i in invs])
        parts_count = invs.count()
        data.append({
            'warehouse': w,
            'value': val,
            'parts': parts_count,
        })

    context = {
        **_get_common_context(request),
        'warehouses': data,
    }
    return render(request, 'warehouses/list.html', context)


@superuser_required
def reports_view(request):
    warehouses = Warehouse.objects.all()
    parts = Part.objects.all()

    # Calculate real report aggregations
    health_stats = {'healthy': 0, 'low': 0, 'critical': 0}
    inventories = Inventory.objects.select_related('part', 'warehouse').all()
    for inv in inventories:
        st = inv.calculated_status.lower()
        if st in health_stats:
            health_stats[st] += 1
        else:
            health_stats['healthy'] += 1

    top_risk_parts = []
    for inv in inventories:
        risk_info = calculate_stockout_risk(inv.part, inv.warehouse)
        top_risk_parts.append({
            'part': inv.part.name,
            'warehouse': inv.warehouse.name,
            'risk_score': risk_info['risk_score'],
            'risk_level': risk_info['risk_level']
        })
    top_risk_parts.sort(key=lambda x: x['risk_score'], reverse=True)
    top_risk_parts = top_risk_parts[:5]

    wh_names = [w.name for w in warehouses]
    wh_values = []
    for w in warehouses:
        val = sum([i.total_value for i in Inventory.objects.filter(warehouse=w).select_related('part')])
        wh_values.append(round(val, 2))

    context = {
        **_get_common_context(request),
        'warehouses': warehouses,
        'parts': parts,
        'health_stats': health_stats,
        'top_risk_parts': top_risk_parts,
        'health_labels_json': json.dumps(['Healthy', 'Low Stock', 'Critical']),
        'health_counts_json': json.dumps([health_stats['healthy'], health_stats['low'], health_stats['critical']]),
        'wh_names_json': json.dumps(wh_names),
        'wh_values_json': json.dumps(wh_values),
    }
    return render(request, 'reports/index.html', context)


def login_view(request):
    next_page = request.GET.get('next', '') or request.POST.get('next', '')
    if request.method == 'GET':
        # Consume and clear previous operational messages so they don't spill onto login card
        storage = messages.get_messages(request)
        storage.used = True

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        try:
            user_exists = User.objects.get(username=username)
        except User.DoesNotExist:
            messages.error(request, "User doesn't exist.")
            user_exists = None

        if user_exists:
            user = authenticate(request, username=username, password=password)
            if user is not None and (user.is_superuser or user.is_staff):
                login(request, user)
                return redirect(next_page or 'parts_frontend:dashboard')
            elif user is not None:
                messages.error(request, 'Only authorized users may sign in.')
            else:
                messages.error(request, 'Username or password incorrect.')

    return render(request, 'registration/login.html', {'next': next_page})


def logout_view(request):
    logout(request)
    return redirect('parts_frontend:login')


@superuser_required
def mark_notification_read_view(request, pk):
    mark_notification_as_read(pk)
    return JsonResponse({'status': 'ok'})
