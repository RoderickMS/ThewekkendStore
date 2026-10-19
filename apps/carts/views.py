from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.forms import AddressForm
from apps.catalog.models import ProductVariant
from apps.inventory.services import (
    InsufficientStockError,
    create_or_refresh_cart_reservations,
    get_available_stock,
)

from .models import CartItem
from .services import get_or_create_cart, validate_and_sync_cart


def _parse_quantity(raw, default=1):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _stock_user(request):
    return request.user if request.user.is_authenticated else None


def cart_detail(request):
    cart = get_or_create_cart(request)
    items = []
    total = 0
    if cart is not None:
        for warning in validate_and_sync_cart(cart, user=_stock_user(request)):
            messages.warning(request, warning)
        items = list(
            cart.items.select_related("variant__product").prefetch_related(
                "variant__product__images"
            )
        )
        for item in items:
            item.available = get_available_stock(item.variant, exclude_user=_stock_user(request))
        # El total siempre se calcula en servidor con el precio vigente (T06).
        total = sum((item.subtotal for item in items), start=0)
    return render(request, "carts/cart_detail.html", {"cart": cart, "items": items, "total": total})


@require_POST
def cart_add(request):
    variant = get_object_or_404(
        ProductVariant.objects.select_related("product"),
        pk=_parse_quantity(request.POST.get("variant_id"), 0),
    )
    product_url = variant.product.get_absolute_url()
    quantity = _parse_quantity(request.POST.get("quantity"))
    if quantity < 1:
        messages.error(request, "La cantidad debe ser al menos 1.")
        return redirect(product_url)
    if not variant.is_active or not variant.product.is_active:
        messages.error(request, "Este producto no está disponible.")
        return redirect(product_url)

    cart = get_or_create_cart(request, create=True)
    item = CartItem.objects.filter(cart=cart, variant=variant).first()
    current = item.quantity if item else 0
    available = get_available_stock(variant, exclude_user=_stock_user(request))
    if current + quantity > available:
        remaining = max(available - current, 0)
        messages.error(
            request,
            f"Stock insuficiente: solo puedes añadir {remaining} unidad(es) más de {variant}.",
        )
        return redirect(product_url)

    # Solo se guarda variante y cantidad: el precio nunca viene del cliente.
    if item:
        item.quantity = current + quantity
        item.save(update_fields=["quantity"])
    else:
        CartItem.objects.create(cart=cart, variant=variant, quantity=quantity)
    messages.success(request, f"Añadiste {variant} al carrito.")
    return redirect("carts:detail")


def _get_cart_item(request, item_id):
    cart = get_or_create_cart(request)
    if cart is None:
        return None
    return get_object_or_404(CartItem.objects.select_related("variant__product"), pk=item_id, cart=cart)


@require_POST
def cart_update(request, item_id):
    item = _get_cart_item(request, item_id)
    if item is None:
        return redirect("carts:detail")
    quantity = _parse_quantity(request.POST.get("quantity"), item.quantity)
    if quantity <= 0:
        item.delete()
        messages.success(request, "Artículo eliminado del carrito.")
        return redirect("carts:detail")

    available = get_available_stock(item.variant, exclude_user=_stock_user(request))
    if quantity > available:
        messages.error(
            request, f"Stock insuficiente: solo hay {available} unidad(es) de {item.variant}."
        )
        return redirect("carts:detail")
    item.quantity = quantity
    item.save(update_fields=["quantity"])
    messages.success(request, "Carrito actualizado.")
    return redirect("carts:detail")


@require_POST
def cart_remove(request, item_id):
    item = _get_cart_item(request, item_id)
    if item is not None:
        item.delete()
        messages.success(request, "Artículo eliminado del carrito.")
    return redirect("carts:detail")


@login_required
def checkout(request):
    cart = get_or_create_cart(request)
    if cart is None or not cart.items.exists():
        messages.warning(request, "Tu carrito está vacío.")
        return redirect("carts:detail")

    # Reserva temporal (M13/T04): bloquea filas y valida stock en servidor.
    try:
        reservations = create_or_refresh_cart_reservations(request.user, cart)
    except InsufficientStockError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("carts:detail")

    addresses = request.user.addresses.all()
    address_form = AddressForm()
    if request.method == "POST":
        address = None
        address_id = request.POST.get("address_id")
        if address_id == "new":
            address_form = AddressForm(request.POST)
            if address_form.is_valid():
                address = address_form.save(commit=False)
                address.user = request.user
                address.save()
        elif address_id:
            address = addresses.filter(pk=_parse_quantity(address_id, 0)).first()
        if address is None:
            if address_id != "new":
                messages.error(request, "Selecciona una dirección de entrega.")
        else:
            request.session["checkout_address_id"] = address.pk
            messages.success(
                request,
                "Reserva confirmada: tus productos están apartados. "
                "El pago se habilitará en la siguiente etapa.",
            )
            return redirect("carts:checkout")

    items = list(
        cart.items.select_related("variant__product").prefetch_related("variant__product__images")
    )
    selected_id = request.session.get("checkout_address_id")
    return render(
        request,
        "carts/checkout.html",
        {
            "cart": cart,
            "items": items,
            "total": sum((item.subtotal for item in items), start=0),
            "addresses": addresses,
            "address_form": address_form,
            "reservations": reservations,
            "selected_address_id": selected_id,
        },
    )
