from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.http import urlencode

from apps.accounts.permissions import admin_required
from apps.inventory.services import get_available_stock, low_stock_variants
from apps.orders.models import Order

from .filters import (
    base_products,
    build_category_filter,
    descendant_category_ids,
    querystring_without_page,
    visible_category_ids,
)
from .models import Category, Product

SEARCH_MIN_LENGTH = 2
SEARCH_MAX_LENGTH = 100
SEARCH_PAGE_SIZE = 12
SHOP_PAGE_SIZE = 12
SUGGESTION_LIMIT = 5


def _listing_context(request, products, *, root=None, page_size=SHOP_PAGE_SIZE):
    """Aplica el filtro por categoría (`?cat=`) a `products`, pagina y devuelve
    el contexto común de tienda, categoría y búsqueda.

    El filtro siempre se resuelve en el servidor; los slugs desconocidos se
    ignoran y los resultados son la unión de las categorías elegidas y todas
    sus subcategorías."""
    category_filter = build_category_filter(request, products, root=root)
    page_obj = Paginator(
        category_filter.products.select_related("category")
        .prefetch_related("images", "variants")
        .order_by("name"),
        page_size,
    ).get_page(request.GET.get("page"))
    return {
        "page_obj": page_obj,
        "category_filter": category_filter,
        "extra_query": querystring_without_page(request),
    }


def home(request):
    """Vitrina principal, con el mismo lenguaje visual de Rhode: hero,
    rail de productos, manifiesto, spotlights, rutina y footer."""
    featured_products = (
        base_products()
        .select_related("category")
        .prefetch_related("images", "variants")
        .order_by("-created_at")[:10]
    )
    categories = Category.objects.filter(pk__in=visible_category_ids()).order_by("order", "name")
    return render(
        request,
        "catalog/home.html",
        {"featured_products": featured_products, "categories": categories},
    )


def shop(request):
    """Tienda completa con filtro por categorías (varias a la vez)."""
    return render(
        request,
        "catalog/shop.html",
        _listing_context(request, base_products()),
    )


def category_detail(request, slug):
    """Productos de una categoría y de todas sus subcategorías (a cualquier
    profundidad), con filtro por subcategoría (M01)."""
    category = get_object_or_404(Category, slug=slug, pk__in=visible_category_ids())
    products = base_products().filter(category_id__in=descendant_category_ids(category))
    context = _listing_context(request, products, root=category)
    context.update(category=category, clear_url=category.get_absolute_url())
    return render(request, "catalog/category_detail.html", context)


def product_detail(request, slug):
    """Vista de producto con selector de variante (imagen propia, precio y
    stock por variante) y formulario de "añadir al carrito" (M11).

    El formulario envía POST a `carts:add` con `variant_id` y `quantity`.
    La validación real de stock ocurre en el servidor (carrito); el `max`
    del input es solo una ayuda de interfaz."""
    product = get_object_or_404(
        Product.objects.select_related("category").prefetch_related("images", "variants"),
        slug=slug,
        is_active=True,
    )
    # Se filtra en Python (no con .filter()) para reutilizar el prefetch
    # y no lanzar una consulta extra.
    variants = [v for v in product.variants.all() if v.is_active]
    for variant in variants:
        variant.available_quantity = get_available_stock(variant)
    # Variante preseleccionada al cargar la página: la primera con stock,
    # o si ninguna tiene, la primera de todas (para que se vea "agotado").
    default_variant = next(
        (v for v in variants if v.available_quantity > 0), variants[0] if variants else None
    )
    return render(
        request,
        "catalog/product_detail.html",
        {"product": product, "variants": variants, "default_variant": default_variant},
    )


def _search_products(query):
    """Productos activos que coinciden con TODAS las palabras de `query`
    (cada palabra puede aparecer en nombre, descripciones, categoría o en
    el valor/SKU de una variante activa)."""
    products = base_products()
    for term in query.split():
        products = products.filter(
            Q(name__icontains=term)
            | Q(short_description__icontains=term)
            | Q(description__icontains=term)
            | Q(category__name__icontains=term)
            | Q(variants__attribute_value__icontains=term, variants__is_active=True)
            | Q(variants__sku__icontains=term, variants__is_active=True)
        )
    return products.distinct().order_by("name")


def _clean_query(request):
    return request.GET.get("q", "").strip()[:SEARCH_MAX_LENGTH]


def search(request):
    """Resultados de búsqueda (M10): GET con parámetro `q`, paginado y con el
    mismo filtro por categoría que la tienda."""
    query = _clean_query(request)
    too_short = bool(query) and len(query) < SEARCH_MIN_LENGTH
    context = {
        "query": query,
        "page_obj": None,
        "category_filter": None,
        "too_short": too_short,
        "min_length": SEARCH_MIN_LENGTH,
    }
    if len(query) >= SEARCH_MIN_LENGTH:
        context.update(
            _listing_context(request, _search_products(query), page_size=SEARCH_PAGE_SIZE),
            clear_url=f"{reverse('catalog:search')}?{urlencode({'q': query})}",
        )
    return render(request, "catalog/search_results.html", context)


def search_suggestions(request):
    """Sugerencias rápidas para el panel de búsqueda (JSON, máx. 5)."""
    query = _clean_query(request)
    results = []
    if len(query) >= SEARCH_MIN_LENGTH:
        products = (
            _search_products(query)
            .select_related("category")
            .prefetch_related("images")[:SUGGESTION_LIMIT]
        )
        for product in products:
            image = product.primary_image
            results.append(
                {
                    "name": product.name,
                    "category": product.category.name,
                    "price": f"{product.base_price:.2f}",
                    "url": product.get_absolute_url(),
                    "image": image.image.url if image else "",
                }
            )
    return JsonResponse({"results": results})


@admin_required
def panel_home(request):
    """Panel administrativo (T05). Un usuario sin rol de administrador que
    entre a /panel/ directamente por la URL recibe 403 desde el servidor.

    Reúne los accesos de la Etapa 3: pedidos (M19) y alertas de bajo
    inventario (M21). El dashboard completo es de la Etapa 4 (M20)."""
    stats = {
        "total_categories": Category.objects.count(),
        "total_products": Product.objects.count(),
        "active_products": Product.objects.filter(is_active=True).count(),
    }
    by_status = dict(Order.objects.values_list("status").annotate(n=Count("pk")))
    order_stats = {
        "pending_payment": by_status.get(Order.Status.PENDING_PAYMENT, 0),
        "to_prepare": by_status.get(Order.Status.PAID, 0),
        "in_progress": by_status.get(Order.Status.PREPARING, 0) + by_status.get(Order.Status.SHIPPED, 0),
        "total": sum(by_status.values()),
        "low_stock": low_stock_variants().count(),
    }
    return render(request, "catalog/panel_home.html", {"stats": stats, "order_stats": order_stats})
