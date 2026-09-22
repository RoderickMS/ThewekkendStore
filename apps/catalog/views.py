from django.shortcuts import get_object_or_404, render

from apps.accounts.permissions import admin_required

from .models import Category, Product


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
    """Vista de producto con selector de variante (color/imagen propia,
    precio y stock por variante). El "añadir al carrito" real, con
    validación de cantidad en servidor, llega en la Etapa 2 (M06/M11);
    por ahora el botón se muestra deshabilitado."""
    product = get_object_or_404(
        Product.objects.select_related("category").prefetch_related("images", "variants"),
        slug=slug,
        is_active=True,
    )
    variants = list(product.variants.filter(is_active=True))
    # Variante preseleccionada al cargar la página: la primera con stock,
    # o si ninguna tiene, la primera de todas (para que se vea "agotado").
    default_variant = next((v for v in variants if v.is_in_stock), variants[0] if variants else None)
    return render(
        request,
        "catalog/product_detail.html",
        {"product": product, "variants": variants, "default_variant": default_variant},
    )


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
