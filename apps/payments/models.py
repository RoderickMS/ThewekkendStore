"""
Pagos (Etapa 3: M16, M17). El esquema viene de la Etapa 1; el flujo del
integración de PayPal Sandbox está en `apps.payments.gateways` y la consistencia con
pedido e inventario en `apps.payments.services`.
"""
from django.db import models


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pendiente", "Pendiente"
        SUCCESS = "exitoso", "Exitoso"
        FAILED = "fallido", "Fallido"
        CANCELLED = "cancelado", "Cancelado"
        REFUNDED = "reembolsado", "Reembolsado"

    order = models.OneToOneField(
        "orders.Order", related_name="payment", on_delete=models.CASCADE, verbose_name="pedido"
    )
    provider = models.CharField(max_length=50, default="paypal_sandbox", verbose_name="proveedor")
    reference = models.CharField(max_length=100, unique=True, verbose_name="referencia")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="monto")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, verbose_name="estado"
    )
    detail = models.CharField(
        max_length=255, blank=True, verbose_name="detalle", help_text="Último mensaje de la pasarela."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name="fecha de pago")

    class Meta:
        verbose_name = "pago"
        verbose_name_plural = "pagos"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Pago {self.reference} ({self.get_status_display()})"

    @property
    def provider_label(self) -> str:
        return "PayPal Sandbox" if self.provider == "paypal_sandbox" else "Proveedor anterior"
