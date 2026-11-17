"""
Servicios de inventario: movimientos, reservas temporales y alertas.

Cualquier cambio de stock (admin, pago confirmado, cancelación) debe pasar
por `register_movement` para que:

1. El stock nunca quede negativo (M05, control de stock en servidor).
2. Cada cambio quede trazado en StockMovement con cantidad, fecha, motivo y
   responsable (M04).
3. La actualización sea atómica y con bloqueo de fila (select_for_update).

Reservas temporales (M13/T04)
-----------------------------
Una reserva no toca `stock_quantity`: solo resta del stock *disponible*
(`stock - reservas vigentes de otros clientes`). Todo lo que decide si hay
stock (reservar, crear el pedido, confirmar el pago) corre dentro de una
transacción que primero **bloquea las filas de ProductVariant en orden de pk**
(`lock_variants`) y recién entonces lee las reservas. Así, dos clientes que
compiten por la última unidad se serializan: el segundo ve la reserva del
primero ya confirmada y recibe `InsufficientStockError`. El orden por pk evita
deadlocks entre transacciones que bloquean varias variantes.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from apps.catalog.models import ProductVariant

from .models import StockMovement, StockReservation


class InsufficientStockError(ValidationError):
    """No hay stock suficiente (o la variante dejó de estar disponible)."""


# --- Bloqueo y validación ---------------------------------------------------


def lock_variants(variant_ids):
    """Bloquea (FOR UPDATE) las variantes indicadas, siempre en orden de pk, y
    las devuelve como `{pk: variant}` con su producto cargado.

    Solo se bloquean las filas de la variante (`of=("self",)`), no las del
    producto. Debe llamarse dentro de una transacción.
    """
    ids = sorted({pk for pk in variant_ids if pk is not None})
    if not ids:
        return {}
    variants = (
        ProductVariant.objects.select_for_update(of=("self",))
        .select_related("product")
        .filter(pk__in=ids)
        .order_by("pk")
    )
    return {v.pk: v for v in variants}


def _reserved_by_others(variant_id, exclude_user=None) -> int:
    reservations = StockReservation.objects.filter(
        variant_id=variant_id, is_active=True, expires_at__gt=timezone.now()
    )
    if exclude_user is not None and getattr(exclude_user, "is_authenticated", False):
        reservations = reservations.exclude(user=exclude_user)
    return reservations.aggregate(total=Sum("quantity"))["total"] or 0


def get_available_stock(variant, exclude_user=None) -> int:
    """Stock realmente disponible: stock físico menos reservas vigentes.

    `exclude_user` omite las reservas de ese usuario, para que quien está en
    checkout (o tiene un pedido por pagar) no compita contra su propia
    reserva. Solo lee: las reservas vencidas se ignoran por fecha y se
    desactivan en `cleanup_expired_reservations`. Nunca devuelve negativos.
    """
    return max(variant.stock_quantity - _reserved_by_others(variant.pk, exclude_user), 0)


def check_purchasable(variant, quantity, exclude_user=None):
    """Lanza `InsufficientStockError` si `variant` no se puede comprar en esa
    cantidad. Para resultados fiables, `variant` debe estar bloqueada
    (`lock_variants`) en la transacción actual."""
    if not variant.is_active or not variant.product.is_active:
        raise InsufficientStockError(f"{variant} ya no está disponible.")
    available = get_available_stock(variant, exclude_user=exclude_user)
    if available < quantity:
        raise InsufficientStockError(
            f"Stock insuficiente para {variant}: disponible {available}, solicitado {quantity}."
        )


# --- Movimientos (M04) ------------------------------------------------------


@transaction.atomic
def register_movement(*, variant_id, movement_type, quantity, reason, responsible):
    """Aplica un movimiento de inventario de forma atómica.

    `quantity` es positivo para entradas/devoluciones y negativo para
    ventas/salidas. Si el movimiento hace que el stock cruce hacia abajo el
    umbral de bajo inventario del producto (M21), se avisa por correo a los
    administradores una vez confirmada la transacción.
    """
    if quantity == 0:
        raise ValidationError("La cantidad del movimiento no puede ser cero.")

    variant = lock_variants([variant_id]).get(variant_id)
    if variant is None:
        raise ValidationError("La variante no existe.")
    previous = variant.stock_quantity
    new_quantity = previous + quantity

    if new_quantity < 0:
        raise InsufficientStockError(
            f"Stock insuficiente para {variant}: disponible {previous}, "
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

    threshold = variant.product.low_stock_threshold
    if previous > threshold >= new_quantity and variant.is_active and variant.product.is_active:
        label, sku = str(variant), variant.sku
        transaction.on_commit(lambda: notify_low_stock(label, sku, new_quantity, threshold))

    return movement


# --- Alertas de bajo inventario (M21) -----------------------------------------


def low_stock_variants():
    """Variantes activas con stock igual o menor al umbral de su producto."""
    return (
        ProductVariant.objects.filter(
            is_active=True,
            product__is_active=True,
            stock_quantity__lte=F("product__low_stock_threshold"),
        )
        .select_related("product")
        .order_by("stock_quantity", "product__name", "attribute_value")
    )


def notify_low_stock(label, sku, stock, threshold):
    """Correo a los administradores. Nunca debe romper una venta: si el
    correo falla, solo se omite (la alerta sigue visible en /panel/stock/)."""
    User = get_user_model()
    recipients = list(
        User.objects.filter(is_active=True)
        .filter(Q(role=User.Role.ADMIN) | Q(is_superuser=True))
        .exclude(email="")
        .values_list("email", flat=True)
        .distinct()
    )
    if not recipients:
        return
    state = "AGOTADO" if stock == 0 else "bajo inventario"
    send_mail(
        subject=f"[The Weekend Store] {state}: {label}",
        message=(
            f"{label} (SKU {sku}) quedó con {stock} unidad(es); "
            f"el umbral de alerta es {threshold}.\n\n"
            "Revisa y repone el inventario en el panel: /panel/stock/"
        ),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=recipients,
        fail_silently=True,
    )


# --- Reservas temporales de checkout (M13/T04) ----------------------------------

RESERVATION_TTL_MINUTES = 15


def cleanup_expired_reservations():
    """Desactiva las reservas cuya vigencia ya terminó."""
    return StockReservation.objects.filter(
        is_active=True, expires_at__lte=timezone.now()
    ).update(is_active=False)


@transaction.atomic
def reserve_cart(user, cart, ttl_minutes=RESERVATION_TTL_MINUTES):
    """Reserva todo el contenido del carrito para el checkout del usuario.

    - Bloquea las variantes y valida el stock disponible (otros clientes
      incluidos) antes de reservar: o se reserva todo o nada.
    - Es idempotente: si el usuario ya tiene una reserva vigente idéntica al
      carrito, se devuelve tal cual **sin extender su vigencia** (recargar la
      página no sirve para retener stock indefinidamente).
    - Si el carrito cambió, la reserva anterior se reemplaza por una nueva.

    Lanza `InsufficientStockError` si alguna variante está inactiva o sin
    stock suficiente. No modifica `stock_quantity`.
    """
    cleanup_expired_reservations()
    items = list(cart.items.order_by("variant_id"))
    wanted = {item.variant_id: item.quantity for item in items}
    locked = lock_variants(wanted)

    current = list(
        StockReservation.objects.select_for_update()
        .filter(user=user, order__isnull=True, is_active=True, expires_at__gt=timezone.now())
        .order_by("variant_id")
    )

    for item in items:
        variant = locked.get(item.variant_id)
        if variant is None:
            raise InsufficientStockError("Un producto de tu carrito ya no existe.")
        if not variant.is_active or not variant.product.is_active:
            raise InsufficientStockError(f"{variant} ya no está disponible.")

    if current and {r.variant_id: r.quantity for r in current} == wanted and len(current) == len(wanted):
        return current  # misma reserva: no se renueva

    StockReservation.objects.filter(user=user, order__isnull=True, is_active=True).update(is_active=False)
    for item in items:
        check_purchasable(locked[item.variant_id], item.quantity, exclude_user=user)

    expires_at = timezone.now() + timedelta(minutes=ttl_minutes)
    return StockReservation.objects.bulk_create(
        [
            StockReservation(
                variant=locked[item.variant_id], user=user, quantity=item.quantity, expires_at=expires_at
            )
            for item in items
        ]
    )


def release_user_reservations(user):
    """Libera las reservas de *checkout* del usuario (las ligadas a un pedido
    pendiente no se tocan: duran lo que dure su ventana de pago)."""
    return StockReservation.objects.filter(user=user, order__isnull=True, is_active=True).update(
        is_active=False
    )
