from .services import get_or_create_cart


def cart_summary(request):
    cart = get_or_create_cart(request)
    return {"cart_count": cart.total_items if cart else 0}