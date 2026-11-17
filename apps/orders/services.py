"""
Lógica de pedidos (Etapa 3).

- M14  Generación del pedido a partir del carrito, con copia (snapshot) de
       producto, precio y dirección, y reserva de stock ligada al pedido.
- M15  Estados del pedido con transiciones validadas y trazabilidad.
- M17  Consistencia con inventario: el stock solo se descuenta al confirmar
       el pago (ver `apps.payments.services`) y se devuelve si se cancela un
       pedido ya pagado; un pedido sin pago expira y libera la reserva.

Orden de bloqueo (evita deadlocks): primero filas de `Order`/`Payment` y
luego filas de `ProductVariant` (siempre por pk ascendente).
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.inventory.models import StockMovement, StockReservation
from apps.inventory.services import (
    check_purchasable,
    lock_variants,
    register_movement,
)
from apps.payments.models import Payment

from .models import Order, OrderItem, OrderStatusHistory


class OrderError(Exception):
    """Error de negocio con un mensaje apto para mostrar al usuario."""


class EmptyCartError(OrderError):
    pass


class InvalidTransition(OrderError):
    pass


def payment_window_minutes() -> int:
    return int(getattr(settings, "PAYMENT_WINDOW_MINUTES", 15))


def format_address(address) -> str:
    """Texto multilínea de una dirección, para la copia guardada en el pedido."""
    lines = [address.line1]
    if address.line2:
        lines.append(address.line2)
    city = address.city + (f", {address.state}" if address.state else "")
    if address.postal_code:
        city += f" {address.postal_code}"
    lines.append(city)
    lines.append(address.country)
    return "\n".join(lines)


# --- M14: generación del pedido ---------------------------------------------


@transaction.atomic
def create_order_from_cart(user, cart, address):
    """Crea un pedido `pendiente_pago` desde el carrito del usuario.

    Todo ocurre en una transacción: bloqueo de variantes, validación del
    stock disponible, pedido + artículos (copia de nombre/precio), reservas
    ligadas al pedido y primer registro del historial de estados. Los precios
    salen siempre de la base de datos (T06), nunca del navegador.

    Un cliente solo tiene un pedido pendiente a la vez: al iniciar otro
    checkout, los pendientes anteriores se cancelan y liberan su reserva.
    """
    if address.user_id != user.pk:
        raise OrderError("La dirección seleccionada no pertenece a tu cuenta.")
    items = list(cart.items.select_related("variant__product").order_by("variant_id"))
    if not items:
        raise EmptyCartError("Tu carrito está vacío.")

    # 1) Pedidos pendientes previos del mismo cliente (Order antes que variantes).
    previous = list(
        Order.objects.select_for_update()
        .filter(user=user, status=Order.Status.PENDING_PAYMENT)
        .values_list("pk", flat=True)
    )
    for pk in previous:
        change_status(
            Order.objects.get(pk=pk),
            Order.Status.CANCELLED,
            note="Reemplazado por un nuevo checkout.",
        )

    # 2) Bloqueo de variantes y validación concurrente de stock (M13/T04).
    locked = lock_variants(item.variant_id for item in items)
    StockReservation.objects.filter(user=user, order__isnull=True, is_active=True).update(
        is_active=False
    )
    for item in items:
        check_purchasable(locked[item.variant_id], item.quantity, exclude_user=user)

    # 3) Pedido con copia de datos.
    now = timezone.now()
    expires_at = now + timedelta(minutes=payment_window_minutes())
    subtotal = Decimal("0")
    lines = []
    for item in items:
        variant = locked[item.variant_id]
        unit_price = variant.price
        line_total = unit_price * item.quantity
        subtotal += line_total
        lines.append((variant, item.quantity, unit_price, line_total))

    order = Order.objects.create(
        user=user,
        address=address,
        shipping_name=address.full_name,
        shipping_address=format_address(address),
        shipping_phone=address.phone,
        status=Order.Status.PENDING_PAYMENT,
        subtotal=subtotal,
        total=subtotal,
        expires_at=expires_at,
    )
    OrderItem.objects.bulk_create(
        [
            OrderItem(
                order=order,
                variant=variant,
                product_name=variant.product.name,
                variant_label=variant.label,
                unit_price=unit_price,
                quantity=quantity,
                subtotal=line_total,
            )
            for variant, quantity, unit_price, line_total in lines
        ]
    )
    StockReservation.objects.bulk_create(
        [
            StockReservation(
                variant=variant, user=user, order=order, quantity=quantity, expires_at=expires_at
            )
            for variant, quantity, _price, _total in lines
        ]
    )
    OrderStatusHistory.objects.create(
        order=order,
        from_status="",
        to_status=order.status,
        changed_by=user,
    )
    return order


# --- M15: estados -------------------------------------------------------------


def admin_transitions(order):
    """Estados a los que el panel administrativo puede mover el pedido.

    Un pedido pendiente de pago NO puede marcarse como pagado a mano: el pago
    solo se confirma a través de la pasarela (M17), que es lo que descuenta
    el inventario."""
    if order.status == Order.Status.PENDING_PAYMENT:
        allowed = {Order.Status.CANCELLED}
    else:
        allowed = set(Order.VALID_TRANSITIONS.get(order.status, set()))
    labels = dict(Order.Status.choices)
    return [(value, labels[value]) for value, _ in Order.Status.choices if value in allowed]


@transaction.atomic
def change_status(order, new_status, *, user=None, note="", expected_status=None):
    """Cambia el estado validando la transición (M15) y dejando historial.

    - `expected_status`: si se indica, falla si el pedido ya no está en ese
      estado (evita pisar un pago que se confirmó en paralelo).
    - Al cancelar un pedido ya pagado se devuelve el stock con un movimiento
      `cancelacion` y el pago se marca como reembolsado (M17).
    - Al cancelar uno pendiente se libera la reserva y se cancela el pago.
    `user=None` significa acción del sistema (p. ej. expiración).
    """
    order = Order.objects.select_for_update().get(pk=order.pk)
    if expected_status is not None and order.status != expected_status:
        raise InvalidTransition(
            f"El pedido {order.number} ya no está «{dict(Order.Status.choices)[expected_status]}»."
        )
    if not order.can_transition_to(new_status):
        labels = dict(Order.Status.choices)
        raise InvalidTransition(
            f"No se puede pasar el pedido {order.number} de "
            f"«{labels.get(order.status, order.status)}» a «{labels.get(new_status, new_status)}»."
        )

    previous = order.status
    if new_status == Order.Status.CANCELLED:
        _apply_cancellation(order, previous, user)

    order.status = new_status
    order.save(update_fields=["status", "updated_at"])
    OrderStatusHistory.objects.create(
        order=order,
        from_status=previous,
        to_status=new_status,
        changed_by=user,
        note=note[:255],
    )
    return order


def _apply_cancellation(order, previous_status, user):
    responsible = user or order.user
    payment = Payment.objects.select_for_update().filter(order=order).first()

    if previous_status in (Order.Status.PAID, Order.Status.PREPARING):
        # El stock ya se había descontado: se devuelve (M17).
        for item in order.items.order_by("variant_id"):
            if item.variant_id is None:
                continue
            register_movement(
                variant_id=item.variant_id,
                movement_type=StockMovement.MovementType.CANCELACION,
                quantity=item.quantity,
                reason=f"Cancelación del pedido {order.number}",
                responsible=responsible,
            )
        if payment and payment.status == Payment.Status.SUCCESS:
            payment.status = Payment.Status.REFUNDED
            payment.detail = "Devolución registrada por cancelación del pedido (entorno local)."
            payment.save(update_fields=["status", "detail"])
    else:
        if payment and payment.status in (Payment.Status.PENDING, Payment.Status.FAILED):
            payment.status = Payment.Status.CANCELLED
            payment.detail = "Pedido cancelado antes de completar el pago."
            payment.save(update_fields=["status", "detail"])

    order.reservations.filter(is_active=True).update(is_active=False)


def cancel_by_customer(order, user):
    """El cliente solo puede cancelar mientras el pedido espera el pago."""
    if order.user_id != user.pk:
        raise OrderError("Pedido no encontrado.")
    try:
        return change_status(
            order,
            Order.Status.CANCELLED,
            user=user,
            note="Cancelado por el cliente.",
            expected_status=Order.Status.PENDING_PAYMENT,
        )
    except InvalidTransition as exc:
        raise InvalidTransition(
            "Solo puedes cancelar un pedido que aún no se ha pagado. "
            "Si necesitas ayuda con un pedido pagado, contacta a la tienda."
        ) from exc


def expire_pending_orders(now=None):
    """Cancela los pedidos pendientes cuya ventana de pago venció y libera su
    reserva. Es seguro llamarla en cualquier momento (también la ejecuta el
    comando `expire_pending_orders`). Devuelve cuántos canceló."""
    now = now or timezone.now()
    ids = list(
        Order.objects.filter(
            status=Order.Status.PENDING_PAYMENT, expires_at__isnull=False, expires_at__lte=now
        ).values_list("pk", flat=True)
    )
    cancelled = 0
    for pk in ids:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=pk)
            # Revalida con el pedido bloqueado: quizá se pagó justo ahora.
            if order.status != Order.Status.PENDING_PAYMENT or order.expires_at > now:
                continue
            change_status(
                order,
                Order.Status.CANCELLED,
                note="La reserva de stock expiró sin pago.",
                expected_status=Order.Status.PENDING_PAYMENT,
            )
            cancelled += 1
    return cancelled
