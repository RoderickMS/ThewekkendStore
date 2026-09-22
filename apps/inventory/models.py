"""
M04 — Inventario y movimientos.

Cada cambio de stock (entrada, ajuste, venta, cancelación o devolución)
queda registrado como un StockMovement con cantidad, fecha, motivo y
responsable. El stock "actual" cacheado en ProductVariant.stock_quantity
solo debe modificarse a través de apps.inventory.services.register_movement,
nunca editando el campo directamente, para que ambos queden siempre
sincronizados.
"""
from django.conf import settings
from django.db import models


class StockMovement(models.Model):
    class MovementType(models.TextChoices):
        ENTRADA = "entrada", "Entrada"
        AJUSTE = "ajuste", "Ajuste"
        VENTA = "venta", "Venta"
        CANCELACION = "cancelacion", "Cancelación"
        DEVOLUCION = "devolucion", "Devolución"

    variant = models.ForeignKey(
        "catalog.ProductVariant",
        related_name="movements",
        on_delete=models.CASCADE,
        verbose_name="variante",
    )
    movement_type = models.CharField(
        max_length=20, choices=MovementType.choices, verbose_name="tipo de movimiento"
    )
    quantity = models.IntegerField(
        verbose_name="cantidad",
        help_text="Positivo para entradas/devoluciones, negativo para ventas/salidas.",
    )
    reason = models.CharField(max_length=255, verbose_name="motivo")
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="stock_movements",
        verbose_name="responsable",
    )
    stock_after = models.PositiveIntegerField(
        verbose_name="stock resultante",
        help_text="Stock de la variante inmediatamente después de este movimiento.",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="fecha")

    class Meta:
        verbose_name = "movimiento de inventario"
        verbose_name_plural = "movimientos de inventario"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_movement_type_display()} ({self.quantity:+d}) — {self.variant}"
