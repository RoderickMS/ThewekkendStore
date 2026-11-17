"""Vistas de pedidos: historial y detalle del cliente (M18) y detalle
administrativo con cambio de estado (M19/M15)."""
from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import admin_required, customer_required
from apps.inventory.services import InsufficientStockError

from .models import Order
from .services import (
    InvalidTransition,
    OrderError,
    admin_transitions,
    cancel_by_customer,
    change_status,
    expire_pending_orders,
)

CUSTOMER_PAGE_SIZE = 8
PANEL_PAGE_SIZE = 15


def _status_filter(request):
    status = request.GET.get("estado", "")
    return status if status in dict(Order.Status.choices) else ""


def _extra_query(request, *keys):
    """Querystring con los filtros activos, para conservarlos al paginar."""
    return urlencode({k: request.GET[k] for k in keys if request.GET.get(k)})


# --- Cliente (M18) ----------------------------------------------------------


@customer_required
def order_list(request):
    expire_pending_orders()
    status = _status_filter(request)
    orders = Order.objects.filter(user=request.user).prefetch_related("items")
    if status:
        orders = orders.filter(status=status)
    page_obj = Paginator(orders, CUSTOMER_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "orders/order_list.html",
        {
            "page_obj": page_obj,
            "status": status,
            "statuses": Order.Status.choices,
            "extra_query": _extra_query(request, "estado"),
        },
    )


@customer_required
def order_detail(request, number):
    expire_pending_orders()
    order = get_object_or_404(
        Order.objects.prefetch_related("items", "status_history"), number=number, user=request.user
    )
    return render(
        request,
        "orders/order_detail.html",
        {
            "order": order,
            "payment": getattr(order, "payment", None),
            "history": list(order.status_history.all())[::-1],
        },
    )


@customer_required
@require_POST
def order_cancel(request, number):
    order = get_object_or_404(Order, number=number, user=request.user)
    try:
        cancel_by_customer(order, request.user)
        messages.success(request, f"Pedido {order.number} cancelado. El stock reservado fue liberado.")
    except OrderError as exc:
        messages.error(request, str(exc))
    return redirect("orders:detail", number=order.number)


# --- Administración (M19) -----------------------------------------------------


@admin_required
def panel_order_list(request):
    expire_pending_orders()
    status = _status_filter(request)
    query = request.GET.get("q", "").strip()[:100]
    orders = (
        Order.objects.select_related("user")
        .annotate(item_count=Count("items"))
        .order_by("-created_at", "-pk")  # con annotate, Meta.ordering no se aplica
    )
    if status:
        orders = orders.filter(status=status)
    if query:
        orders = orders.filter(
            Q(number__icontains=query)
            | Q(user__username__icontains=query)
            | Q(user__email__icontains=query)
            | Q(shipping_name__icontains=query)
        )
    counts = dict(Order.objects.values_list("status").annotate(n=Count("pk")))
    page_obj = Paginator(orders, PANEL_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "orders/panel_order_list.html",
        {
            "page_obj": page_obj,
            "status": status,
            "query": query,
            "status_tabs": [(v, label, counts.get(v, 0)) for v, label in Order.Status.choices],
            "total_count": sum(counts.values()),
            "extra_query": _extra_query(request, "estado", "q"),
        },
    )


@admin_required
def panel_order_detail(request, number):
    expire_pending_orders()
    order = get_object_or_404(
        Order.objects.select_related("user").prefetch_related("items", "status_history__changed_by"),
        number=number,
    )
    return render(
        request,
        "orders/panel_order_detail.html",
        {
            "order": order,
            "payment": getattr(order, "payment", None),
            "history": list(order.status_history.all())[::-1],
            "transitions": admin_transitions(order),
        },
    )


@admin_required
@require_POST
def panel_order_status(request, number):
    order = get_object_or_404(Order, number=number)
    new_status = request.POST.get("estado", "")
    note = request.POST.get("nota", "").strip()[:200]
    if new_status not in dict(admin_transitions(order)):
        messages.error(request, "Ese cambio de estado no está permitido para este pedido.")
        return redirect("orders_panel:detail", number=order.number)
    try:
        change_status(order, new_status, user=request.user, note=note)
        messages.success(
            request, f"Pedido {order.number} actualizado a «{dict(Order.Status.choices)[new_status]}»."
        )
    except (InvalidTransition, InsufficientStockError) as exc:
        messages.error(request, "; ".join(getattr(exc, "messages", None) or [str(exc)]))
    return redirect("orders_panel:detail", number=order.number)
