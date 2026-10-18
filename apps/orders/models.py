"""
Modelo de datos de pedidos, diseñado en la Etapa 1 (T01-T03) junto con el
resto del esquema. La generación real de pedidos, el flujo de estados y la
consistencia con pago/inventario (M14, M15, M17) se implementan en la
Etapa 3.
"""
import uuid

from django.conf import settings
from django.db import models


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pendiente_pago", "Pendiente de pago"
        PAID = "pagado", "Pagado/Confirmado"
        PREPARING = "en_preparacion", "En preparación"
        SHIPPED = "enviado", "Enviado"
        DELIVERED = "entregado", "Entregado"
        CANCELLED = "cancelado", "Cancelado"

    # Transiciones válidas de estado (M15): un pedido no puede saltar de
    # Cancelado a Entregado, por ejemplo. Se usa en la Etapa 3 para validar
    # cambios de estado tanto del cliente como del panel administrativo.
    VALID_TRANSITIONS = {
        Status.PENDING_PAYMENT: {Status.PAID, Status.CANCELLED},
        Status.PAID: {Status.PREPARING, Status.CANCELLED},
        Status.PREPARING: {Status.SHIPPED, Status.CANCELLED},
        Status.SHIPPED: {Status.DELIVERED},
        Status.DELIVERED: set(),
        Status.CANCELLED: set(),
    }

    number = models.CharField(
        max_length=32, unique=True, editable=False, verbose_name="número de pedido"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="orders", on_delete=models.PROTECT, verbose_name="cliente"
    )
    address = models.ForeignKey(
        "accounts.Address",
        related_name="orders",
        on_delete=models.PROTECT,
        verbose_name="dirección de entrega",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT, verbose_name="estado"
    )
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "pedido"
        verbose_name_plural = "pedidos"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Pedido {self.number}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = f"TWS-{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in self.VALID_TRANSITIONS.get(self.status, set())


class OrderItem(models.Model):
    """Copia (snapshot) del producto al momento de la compra, para que
    cambios futuros al producto no alteren el historial (criterio de
    aceptación de M14)."""

    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        related_name="order_items",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Referencia viva a la variante, solo para trazabilidad de inventario.",
    )
    product_name = models.CharField(max_length=200)
    variant_label = models.CharField(max_length=100, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "artículo del pedido"
        verbose_name_plural = "artículos del pedido"

    def __str__(self):
        return f"{self.quantity} x {self.product_name} ({self.variant_label})"


class OrderStatusHistory(models.Model):
    """Trazabilidad de cada cambio de estado (apoya M15/M19/S03)."""

    order = models.ForeignKey(Order, related_name="status_history", on_delete=models.CASCADE)
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "historial de estado del pedido"
        verbose_name_plural = "historial de estados del pedido"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.order.number}: {self.from_status} → {self.to_status}"
