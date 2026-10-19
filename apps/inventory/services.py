"""
Servicio central para registrar movimientos de inventario.

Cualquier cambio de stock (desde el admin, el carrito en la Etapa 2, o el
checkout en la Etapa 3) debe pasar por `register_movement` para que:

1. El stock nunca quede negativo (base de M05, Control de stock en servidor).
2. Cada cambio quede trazado en StockMovement con cantidad, fecha, motivo y
   responsable (M04).
3. La actualización sea atómica con bloqueo de fila (select_for_update),
   sentando la base para la reserva/validación concurrente de la Etapa 2
   (M13/T04), tal como se pactó con el cliente.
"""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.catalog.models import ProductVariant

from .models import StockMovement, StockReservation


class InsufficientStockError(ValidationError):
    """El movimiento dejaría el stock de la variante en negativo."""


@transaction.atomic
def register_movement(*, variant_id, movement_type, quantity, reason, responsible):
    """Aplica un movimiento de inventario de forma atómica.

    `quantity` es positivo para entradas/devoluciones y negativo para
    ventas/cancelaciones que restan stock.
    """
    if quantity == 0:
        raise ValidationError("La cantidad del movimiento no puede ser cero.")

    variant = ProductVariant.objects.select_for_update().get(pk=variant_id)
    new_quantity = variant.stock_quantity + quantity

    if new_quantity < 0:
        raise InsufficientStockError(
            f"Stock insuficiente para {variant}: disponible {variant.stock_quantity}, "
            f"se intentó aplicar {quantity}."
        )

    movement = StockMovement.objects.create(
        variant=variant,
        movement_type=movement_type,
        quantity=quantity,
        reason=reason,
        responsible=responsible,
        stock_after=new_quantity,
    )

    variant.stock_quantity = new_quantity
    variant.save(update_fields=["stock_quantity"])

    return movement


# --- Reservas temporales y disponibilidad (M05, M13/T04) --------------------

RESERVATION_TTL_MINUTES = 15


def cleanup_expired_reservations():
    """Desactiva las reservas cuya vigencia ya terminó."""
    return StockReservation.objects.filter(
        is_active=True, expires_at__lte=timezone.now()
    ).update(is_active=False)


def get_available_stock(variant, exclude_user=None) -> int:
    """Stock realmente disponible: stock físico menos reservas vigentes.

    `exclude_user` omite las reservas de ese usuario para que quien está en
    checkout no compita contra su propia reserva. Nunca devuelve negativos.
    """
    cleanup_expired_reservations()
    reservations = StockReservation.objects.filter(
        variant_id=variant.pk, is_active=True, expires_at__gt=timezone.now()
    )
    if exclude_user is not None and getattr(exclude_user, "is_authenticated", False):
        reservations = reservations.exclude(user=exclude_user)
    reserved = reservations.aggregate(total=Sum("quantity"))["total"] or 0
    return max(variant.stock_quantity - reserved, 0)


@transaction.atomic
def create_or_refresh_cart_reservations(user, cart, ttl_minutes=RESERVATION_TTL_MINUTES):
    """Reserva (con bloqueo de filas) todo el contenido del carrito.

    Lanza `InsufficientStockError` si alguna variante está inactiva o no
    tiene stock disponible suficiente. No modifica `stock_quantity`.
    """
    cleanup_expired_reservations()
    StockReservation.objects.filter(user=user, is_active=True).update(is_active=False)

    items = list(cart.items.all())
    variant_ids = [item.variant_id for item in items]
    # Orden por pk para evitar deadlocks entre transacciones concurrentes.
    locked = {
        v.pk: v
        for v in ProductVariant.objects.select_for_update()
        .select_related("product")
        .filter(pk__in=variant_ids)
        .order_by("pk")
    }

    expires_at = timezone.now() + timedelta(minutes=ttl_minutes)
    reservations = []
    for item in items:
        variant = locked[item.variant_id]
        if not variant.is_active or not variant.product.is_active:
            raise InsufficientStockError(f"{variant} ya no está disponible.")
        available = get_available_stock(variant, exclude_user=user)
        if available < item.quantity:
            raise InsufficientStockError(
                f"Stock insuficiente para {variant}: disponible {available}, "
                f"en tu carrito {item.quantity}."
            )
        reservations.append(
            StockReservation(
                variant=variant, user=user, quantity=item.quantity, expires_at=expires_at
            )
        )
    return StockReservation.objects.bulk_create(reservations)


def release_user_reservations(user):
    """Libera (desactiva) las reservas activas del usuario."""
    return StockReservation.objects.filter(user=user, is_active=True).update(is_active=False)
