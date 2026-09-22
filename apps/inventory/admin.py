from django import forms
from django.contrib import admin

from .models import StockMovement
from .services import register_movement


class StockMovementForm(forms.ModelForm):
    class Meta:
        model = StockMovement
        fields = ["variant", "movement_type", "quantity", "reason"]
        help_texts = {
            "quantity": "Positivo para entradas/devoluciones, negativo para ventas/salidas.",
        }

    def clean(self):
        cleaned = super().clean()
        variant = cleaned.get("variant")
        quantity = cleaned.get("quantity")
        if variant is not None and quantity is not None:
            if quantity == 0:
                self.add_error("quantity", "La cantidad no puede ser cero.")
            elif variant.stock_quantity + quantity < 0:
                self.add_error(
                    "quantity",
                    f"Stock insuficiente: disponible {variant.stock_quantity}, "
                    f"se intentó aplicar {quantity}.",
                )
        return cleaned


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    """Registra movimientos de inventario (M04) siempre a través de
    `register_movement`, para que el stock cacheado en la variante y el
    historial de movimientos nunca queden desincronizados.

    Por trazabilidad, un movimiento ya registrado no se puede editar ni
    borrar desde aquí: para corregir un error se registra un nuevo
    movimiento de tipo 'ajuste'.
    """

    form = StockMovementForm
    list_display = (
        "created_at",
        "variant",
        "movement_type",
        "quantity",
        "stock_after",
        "reason",
        "responsible",
    )
    list_filter = ("movement_type", "created_at")
    search_fields = ("variant__sku", "variant__product__name", "reason")
    readonly_fields = ("stock_after", "responsible", "created_at")
    autocomplete_fields = ["variant"]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        # No llamamos a obj.save(): el movimiento real se crea a través del
        # servicio para que el stock cacheado y el historial queden
        # sincronizados dentro de una misma transacción atómica.
        movement = register_movement(
            variant_id=form.cleaned_data["variant"].pk,
            movement_type=form.cleaned_data["movement_type"],
            quantity=form.cleaned_data["quantity"],
            reason=form.cleaned_data["reason"],
            responsible=request.user,
        )
        # Reflejamos el registro creado en `obj` para que el admin pueda
        # redirigir correctamente a la página de detalle tras guardar.
        obj.pk = movement.pk
        obj.stock_after = movement.stock_after
        obj.responsible = movement.responsible
        obj.created_at = movement.created_at
