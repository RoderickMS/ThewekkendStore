"""
Lógica de negocio del carrito: obtención (usuario o invitado, M07),
validación de stock en servidor (M05) y fusión al iniciar sesión.

Nunca se modifica `ProductVariant.stock_quantity` desde aquí: el stock solo
cambia vía `apps.inventory.services.register_movement`.
"""
from django.db import transaction

from apps.inventory.services import get_available_stock

from .models import Cart, CartItem


def get_or_create_cart(request, create=False):
    """Carrito del usuario autenticado o del invitado (por `session_key`).

    Con `create=False` devuelve None si todavía no existe.
    """
    if request.user.is_authenticated:
        if create:
            return Cart.objects.get_or_create(user=request.user)[0]
        return Cart.objects.filter(user=request.user).first()

    if not request.session.session_key:
        if not create:
            return None
        request.session.create()
    session_key = request.session.session_key
    if create:
        cart = Cart.objects.filter(session_key=session_key, user__isnull=True).first()
        return cart or Cart.objects.create(session_key=session_key)
    return Cart.objects.filter(session_key=session_key, user__isnull=True).first()


def validate_and_sync_cart(cart, user=None):
    """Devuelve una lista de avisos si algún ítem dejó de ser válido
    (producto/variante inactivos o stock disponible menor a la cantidad)."""
    warnings = []
    for item in cart.items.select_related("variant__product"):
        variant = item.variant
        name = str(variant)
        if not variant.is_active or not variant.product.is_active:
            warnings.append(f"{name} ya no está disponible; elimínalo para continuar.")
            continue
        available = get_available_stock(variant, exclude_user=user)
        if available < item.quantity:
            warnings.append(
                f"{name}: solo hay {available} disponible(s) y tienes {item.quantity} en el carrito."
            )
    return warnings


@transaction.atomic
def merge_guest_cart_into_user(session_key, user):
    """Fusiona el carrito de invitado en el del usuario (M07), sin superar
    el stock disponible, y elimina el carrito de sesión."""
    if not session_key:
        return
    guest_cart = (
        Cart.objects.filter(session_key=session_key, user__isnull=True)
        .prefetch_related("items__variant__product")
        .first()
    )
    if guest_cart is None:
        return

    user_cart, _ = Cart.objects.get_or_create(user=user)
    for item in guest_cart.items.all():
        variant = item.variant
        if not variant.is_active or not variant.product.is_active:
            continue
        available = get_available_stock(variant, exclude_user=user)
        if available <= 0:
            continue
        existing = CartItem.objects.filter(cart=user_cart, variant=variant).first()
        existing_qty = existing.quantity if existing else 0
        new_qty = min(existing_qty + item.quantity, available)
        if existing:
            existing.quantity = new_qty
            existing.save(update_fields=["quantity"])
        else:
            CartItem.objects.create(cart=user_cart, variant=variant, quantity=new_qty)
    guest_cart.delete()
