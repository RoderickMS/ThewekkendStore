from .models import Category


def storefront_nav(request):
    """Categorías raíz activas, disponibles en todos los templates para
    construir la navegación del header (M01)."""
    categories = (
        Category.objects.filter(parent__isnull=True, is_active=True)
        .prefetch_related("children")
        .order_by("order", "name")
    )
    return {"nav_categories": categories}
