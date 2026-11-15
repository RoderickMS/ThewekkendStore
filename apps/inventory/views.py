"""Alertas de bajo inventario (M21) en el panel administrativo."""
from django.core.paginator import Paginator
from django.shortcuts import render

from apps.accounts.permissions import admin_required

from .services import low_stock_variants


@admin_required
def low_stock_alerts(request):
    variants = low_stock_variants()
    only_out = request.GET.get("agotados") == "1"
    if only_out:
        variants = variants.filter(stock_quantity=0)
    page_obj = Paginator(variants, 20).get_page(request.GET.get("page"))
    all_variants = low_stock_variants()
    return render(
        request,
        "inventory/low_stock.html",
        {
            "page_obj": page_obj,
            "only_out": only_out,
            "extra_query": "agotados=1" if only_out else "",
            "total_low": all_variants.count(),
            "total_out": all_variants.filter(stock_quantity=0).count(),
        },
    )
