"""
Modelo de datos del carrito, diseñado en la Etapa 1 (T01-T03) para evitar
migraciones tardías, aunque la lógica de negocio (agregar/quitar, fusión de
carrito de invitado, precios en servidor) se implementa en la Etapa 2
(M06, M07, T06).
"""
from django.conf import settings
from django.db import models


class Cart(models.Model):
    """Un carrito pertenece a un usuario autenticado, o a un invitado
    identificado por `session_key` (M07 - carrito persistente para
    invitados). Ambos campos son opcionales pero mutuamente relevantes:
    la fusión de la Etapa 2 reasigna `user` a un carrito de sesión."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="cart",
        on_delete=models.CASCADE,
        verbose_name="usuario",
    )
    session_key = models.CharField(
        max_length=40, null=True, blank=True, db_index=True, verbose_name="sesión de invitado"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "carrito"
        verbose_name_plural = "carritos"
        constraints = [
            models.CheckConstraint(
                check=models.Q(user__isnull=False) | models.Q(session_key__isnull=False),
                name="cart_has_user_or_session",
            )
        ]

    def __str__(self):
        return f"Carrito de {self.user}" if self.user_id else f"Carrito invitado {self.session_key}"

    @property
    def total(self):
        return sum((item.subtotal for item in self.items.all()), start=0)


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, related_name="items", on_delete=models.CASCADE)
    variant = models.ForeignKey(
        "catalog.ProductVariant", related_name="cart_items", on_delete=models.CASCADE
    )
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "artículo del carrito"
        verbose_name_plural = "artículos del carrito"
        constraints = [
            models.UniqueConstraint(fields=["cart", "variant"], name="unique_variant_per_cart")
        ]

    def __str__(self):
        return f"{self.quantity} x {self.variant}"

    @property
    def subtotal(self):
        # El precio final siempre se recalcula en servidor (T06); este
        # subtotal usa el precio vigente de la variante, no uno guardado
        # en el navegador.
        return self.variant.price * self.quantity
