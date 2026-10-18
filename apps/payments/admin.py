from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    # Etapa 1: solo consulta. El flujo de pago simulado se agrega en Etapa 3.
    list_display = ("reference", "order", "amount", "status", "created_at")
    list_filter = ("status", "provider")
    search_fields = ("reference", "order__number")
    readonly_fields = [f.name for f in Payment._meta.fields]

    def has_add_permission(self, request):
        return False
