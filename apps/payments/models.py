"""
Modelo de datos de pagos, diseñado en la Etapa 1 (T01-T03). El flujo real
de pago simulado tipo Sandbox/PayPal (M16) y su consistencia con el
inventario (M17) se implementan en la Etapa 3.
"""
from django.db import models


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pendiente", "Pendiente"
        SUCCESS = "exitoso", "Exitoso"
        FAILED = "fallido", "Fallido"
        CANCELLED = "cancelado", "Cancelado"

    order = models.OneToOneField(
        "orders.Order", related_name="payment", on_delete=models.CASCADE, verbose_name="pedido"
    )
    provider = models.CharField(max_length=50, default="sandbox", verbose_name="proveedor")
    reference = models.CharField(max_length=100, unique=True, verbose_name="referencia")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="monto")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, verbose_name="estado"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name="fecha de pago")

    class Meta:
        verbose_name = "pago"
        verbose_name_plural = "pagos"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Pago {self.reference} ({self.get_status_display()})"
