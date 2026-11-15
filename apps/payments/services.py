"""
Pagos y consistencia con el inventario (M16, M17).

Garantías de `process_payment`:

- Todo ocurre en UNA transacción con el pedido y el pago bloqueados
  (Order -> Payment -> variantes, siempre en ese orden).
- Es idempotente: repetir la confirmación (doble clic, recarga, reintento del
  navegador) no descuenta el stock dos veces ni crea un segundo cobro.
- El stock solo se descuenta cuando la pasarela confirma el cobro, y en la
  misma transacción que marca el pago como exitoso y el pedido como pagado: o
  se hace todo o no se hace nada.
- Si al confirmar ya no hay stock (reserva vencida y otro cliente compró),
  no se cobra: el pedido se cancela y se avisa al cliente.
- Un pago fallido o cancelado deja el pedido pendiente (con su reserva) para
  reintentar mientras dure la ventana de pago.
"""
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.carts.models import Cart
from apps.inventory.models import StockMovement
from apps.inventory.services import (
    InsufficientStockError,
    check_purchasable,
    lock_variants,
    register_movement,
)
from apps.orders.models import Order
from apps.orders.services import change_status

from .gateways import PayPalSandboxError, get_gateway
from .models import Payment


class PaymentError(Exception):
    """Error de negocio con un mensaje apto para mostrar al cliente."""


@dataclass
class PaymentOutcome:
    ok: bool
    message: str
    order: Order
    payment: Payment
    already_paid: bool = False


@transaction.atomic
def initiate_payment(order) -> Payment:
    """Prepara (o reutiliza) el pago pendiente de un pedido: equivale a crear
    la orden en la pasarela. Si el intento anterior falló o se canceló, abre
    uno nuevo con otra referencia."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    if not order.is_payment_window_open:
        raise PaymentError("Este pedido ya no admite pago: venció o fue cancelado.")

    gateway = get_gateway()
    payment = Payment.objects.select_for_update().filter(order=order).first()
    if payment is None:
        return Payment.objects.create(
            order=order,
            provider=gateway.name,
            reference=gateway.create_order(order),
            amount=order.total,
            status=Payment.Status.PENDING,
        )
    if payment.status == Payment.Status.SUCCESS:
        raise PaymentError("Este pedido ya está pagado.")
    if payment.status == Payment.Status.PENDING and payment.provider != gateway.name:
        raise PaymentError("Este pedido tiene un intento abierto con otra pasarela.")
    if payment.status in (Payment.Status.FAILED, Payment.Status.CANCELLED):
        payment.reference = gateway.create_order(order)
        payment.provider = gateway.name
        payment.status = Payment.Status.PENDING
        payment.detail = "Nuevo intento de pago."
        payment.paid_at = None
    payment.amount = order.total  # el monto siempre sale del pedido
    payment.save()
    return payment


def _ensure_stock_for_order(order):
    """Con las variantes bloqueadas, confirma que el pedido todavía se puede
    cumplir. Si la reserva venció, el stock se valida de nuevo contra las
    reservas de otros clientes."""
    items = list(order.items.order_by("variant_id"))
    locked = lock_variants(i.variant_id for i in items if i.variant_id)
    live = {
        r.variant_id: r.quantity
        for r in order.reservations.filter(is_active=True, expires_at__gt=timezone.now())
    }
    for item in items:
        variant = locked.get(item.variant_id)
        if variant is None:
            raise InsufficientStockError(f"{item.product_name} ya no existe en el catálogo.")
        if not variant.is_active or not variant.product.is_active:
            raise InsufficientStockError(f"{variant} ya no está disponible.")
        if live.get(item.variant_id) == item.quantity:
            continue  # reserva vigente: el stock está garantizado
        check_purchasable(variant, item.quantity, exclude_user=order.user)


def _consume_cart(order):
    """Quita del carrito del cliente lo que acaba de comprar."""
    cart = Cart.objects.filter(user=order.user).first()
    if cart is None:
        return
    for item in order.items.all():
        cart_item = cart.items.filter(variant_id=item.variant_id).first()
        if cart_item is None:
            continue
        remaining = cart_item.quantity - item.quantity
        if remaining > 0:
            cart_item.quantity = remaining
            cart_item.save(update_fields=["quantity"])
        else:
            cart_item.delete()


def process_payment(reference, user, action) -> PaymentOutcome:
    """Captura una orden aprobada en PayPal Sandbox.

    Lanza `Payment.DoesNotExist` si la referencia no es del usuario y
    `PaymentError` si el intento ya no es válido.
    """
    if action != "approve":
        raise PaymentError("Acción de pago no válida.")

    found = Payment.objects.select_related("order").get(reference=reference, order__user=user)
    order_id = found.order_id
    gateway = get_gateway(found.provider)
    try:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order_id)
            payment = Payment.objects.select_for_update().get(pk=found.pk)

            if payment.status == Payment.Status.SUCCESS:
                return PaymentOutcome(True, "Este pedido ya estaba pagado.", order, payment, True)
            if payment.reference != reference or payment.status != Payment.Status.PENDING:
                raise PaymentError("Este intento de pago ya no es válido. Inicia uno nuevo.")
            if not order.is_payment_window_open:
                raise PaymentError("La reserva del pedido venció; no se puede capturar el pago.")
            if order.status != Order.Status.PENDING_PAYMENT:
                raise PaymentError(
                    f"El pedido está «{order.get_status_display()}» y ya no admite pago."
                )

            if action == "approve":
                _ensure_stock_for_order(order)  # InsufficientStockError -> sin cobro
            result = gateway.capture(reference, payment.amount, action)

            if not result.completed:
                payment.status = (
                    Payment.Status.CANCELLED if result.status == "CANCELLED" else Payment.Status.FAILED
                )
                payment.detail = result.detail[:255]
                payment.save(update_fields=["status", "detail"])
                message = (
                    "Cancelaste el pago. Tu pedido sigue reservado: puedes reintentar."
                    if payment.status == Payment.Status.CANCELLED
                    else "El pago fue rechazado. Tu pedido sigue reservado: puedes reintentar."
                )
                return PaymentOutcome(False, message, order, payment)

            # Cobro confirmado: descuento de stock + pago + pedido, todo junto.
            for item in order.items.order_by("variant_id"):
                register_movement(
                    variant_id=item.variant_id,
                    movement_type=StockMovement.MovementType.VENTA,
                    quantity=-item.quantity,
                    reason=f"Venta del pedido {order.number}",
                    responsible=order.user,
                )
            order.reservations.filter(is_active=True).update(is_active=False)
            payment.status = Payment.Status.SUCCESS
            payment.paid_at = timezone.now()
            payment.detail = f"{result.detail} Captura {result.capture_id}".strip()[:255]
            payment.save(update_fields=["status", "paid_at", "detail"])
            order = change_status(
                order,
                Order.Status.PAID,
                expected_status=Order.Status.PENDING_PAYMENT,
            )
            _consume_cart(order)
            return PaymentOutcome(True, "¡Pago recibido! Tu pedido quedó confirmado.", order, payment)
    except InsufficientStockError as exc:
        return _fail_for_stock(order_id, reference, " ".join(exc.messages))


def _fail_for_stock(order_id, reference, reason) -> PaymentOutcome:
    """Sin stock al confirmar: no hubo cobro; se cancela el pedido."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if order.status == Order.Status.PENDING_PAYMENT:
            order = change_status(
                order,
                Order.Status.CANCELLED,
                note=f"Cancelado: sin stock al confirmar el pago. {reason}"[:255],
                expected_status=Order.Status.PENDING_PAYMENT,
            )
        payment = Payment.objects.select_for_update().get(order=order)
        if payment.status != Payment.Status.SUCCESS:
            payment.detail = "No se realizó ningún cobro: stock insuficiente al confirmar."
            payment.save(update_fields=["detail"])
    return PaymentOutcome(
        False,
        f"No pudimos completar la compra y no se te cobró nada. {reason}",
        order,
        payment,
    )
