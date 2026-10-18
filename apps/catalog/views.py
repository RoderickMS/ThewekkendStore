from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from apps.accounts.permissions import admin_required

from .models import Category, Product

SEARCH_MIN_LENGTH = 2
SEARCH_MAX_LENGTH = 100
SEARCH_PAGE_SIZE = 12
SUGGESTION_LIMIT = 5


def home(request):
    """Vitrina principal, con el mismo lenguaje visual de Rhode: hero,
    rail de productos, manifiesto, spotlights, rutina y footer."""
    featured_products = (
        Product.objects.filter(is_active=True)
        .select_related("category")
        .prefetch_related("images", "variants")
        .order_by("-created_at")[:8]
    )
    root_categories = Category.objects.filter(parent__isnull=True, is_active=True)
    return render(
        request,
        "catalog/home.html",
        {"featured_products": featured_products, "root_categories": root_categories},
    )


def category_detail(request, slug):
    """Listado de productos de una categoría (y sus subcategorías),
    parte del catálogo jerárquico M01."""
    category = get_object_or_404(Category, slug=slug, is_active=True)
    category_ids = [category.pk] + list(category.children.filter(is_active=True).values_list("pk", flat=True))
    products = (
        Product.objects.filter(category_id__in=category_ids, is_active=True)
        .select_related("category")
        .prefetch_related("images", "variants")
        .order_by("name")
    )
    return render(
        request,
        "catalog/category_detail.html",
        {"category": category, "products": products},
    )


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
    # Variante preseleccionada al cargar la página: la primera con stock,
    # o si ninguna tiene, la primera de todas (para que se vea "agotado").
    default_variant = next((v for v in variants if v.is_in_stock), variants[0] if variants else None)
    return render(
        request,
        "catalog/product_detail.html",
        {"product": product, "variants": variants, "default_variant": default_variant},
    )


def _search_products(query):
    """Productos activos que coinciden con TODAS las palabras de `query`
    (cada palabra puede aparecer en nombre, descripciones, categoría o en
    el valor/SKU de una variante activa)."""
    products = Product.objects.filter(is_active=True, category__is_active=True)
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
    """Resultados de búsqueda (M10): GET con parámetro `q`, paginado."""
    query = _clean_query(request)
    page_obj = None
    too_short = bool(query) and len(query) < SEARCH_MIN_LENGTH
    if len(query) >= SEARCH_MIN_LENGTH:
        products = (
            _search_products(query)
            .select_related("category")
            .prefetch_related("images", "variants")
        )
        page_obj = Paginator(products, SEARCH_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "catalog/search_results.html",
        {
            "query": query,
            "page_obj": page_obj,
            "too_short": too_short,
            "min_length": SEARCH_MIN_LENGTH,
        },
    )


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
    """Panel administrativo (T05): demuestra que el rechazo de rol ocurre
    en el servidor. Un usuario sin role=administrador que entre a /panel/
    directamente por la URL recibe 403, sin importar lo que muestre el
    navegador. Este panel se irá ampliando en etapas posteriores con
    pedidos (M19) y el dashboard (M20)."""
    stats = {
        "total_categories": Category.objects.count(),
        "total_products": Product.objects.count(),
        "active_products": Product.objects.filter(is_active=True).count(),
    }
    return render(request, "catalog/panel_home.html", {"stats": stats})