"""
Pedidos (Etapa 3: M14, M15, M17).

El esquema se diseñó en la Etapa 1 (T01-T03); la lógica de generación,
estados y consistencia con pago/inventario vive en `apps.orders.services`.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pendiente_pago", "Pendiente de pago"
        PAID = "pagado", "Pagado/Confirmado"
        PREPARING = "en_preparacion", "En preparación"
        SHIPPED = "enviado", "Enviado"
        DELIVERED = "entregado", "Entregado"
        CANCELLED = "cancelado", "Cancelado"

    # Transiciones válidas de estado (M15): un pedido no puede saltar de
    # Cancelado a Entregado, por ejemplo. Se valida en servidor tanto para
    # los cambios del cliente como para los del panel administrativo.
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
    # La dirección viva puede borrarse después; lo que cuenta para el
    # pedido es la copia (shipping_*), que nunca cambia (criterio de M14).
    address = models.ForeignKey(
        "accounts.Address",
        related_name="orders",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="dirección de entrega",
    )
    shipping_name = models.CharField(max_length=150, blank=True, verbose_name="destinatario")
    shipping_address = models.TextField(blank=True, verbose_name="dirección de entrega (copia)")
    shipping_phone = models.CharField(max_length=20, blank=True, verbose_name="teléfono de contacto")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT, verbose_name="estado"
    )
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="vence el pago",
        help_text="Hasta cuándo se mantiene reservado el stock mientras se espera el pago.",
    )
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

    @property
    def is_payment_window_open(self) -> bool:
        """Pendiente de pago y con la reserva de stock todavía vigente."""
        return self.status == self.Status.PENDING_PAYMENT and (
            self.expires_at is None or self.expires_at > timezone.now()
        )

    @property
    def status_css(self) -> str:
        return f"status-{self.status}"


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

    @property
    def to_label(self) -> str:
        return dict(Order.Status.choices).get(self.to_status, self.to_status)

    @property
    def display_message(self) -> str:
        messages = {
            Order.Status.PENDING_PAYMENT: "Pedido creado, en espera del pago.",
            Order.Status.PAID: "Pago confirmado.",
            Order.Status.PREPARING: "Tu pedido está siendo preparado.",
            Order.Status.SHIPPED: "Tu pedido ha sido enviado.",
            Order.Status.DELIVERED: "Tu pedido ha sido entregado.",
            Order.Status.CANCELLED: "Tu pedido ha sido cancelado.",
        }
        message = messages.get(self.to_status, "El estado de tu pedido fue actualizado.")
        note = (self.note or "").strip()
        automatic_notes = (
            "Pedido creado; stock reservado mientras se completa el pago.",
            "Cambio desde el panel.",
            "Reemplazado por un nuevo checkout.",
            "Cancelado por el cliente.",
            "La reserva de stock expiró sin pago.",
        )
        if (
            not note
            or note in automatic_notes
            or note.startswith("Pago confirmado (")
            or note.startswith("Cancelado: sin stock al confirmar el pago.")
        ):
            return message
        return note
