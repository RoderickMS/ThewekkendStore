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
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.catalog.models import ProductVariant

from .models import StockMovement


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
