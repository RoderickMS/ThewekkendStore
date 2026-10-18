from django.contrib import admin

from .models import Order, OrderItem, OrderStatusHistory


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("variant", "product_name", "variant_label", "unit_price", "quantity", "subtotal")
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    # Etapa 1: solo consulta. El cambio de estado validado (M15/M19) y el
    # detalle administrativo completo se agregan en la Etapa 3.
    list_display = ("number", "user", "status", "total", "created_at")
    list_filter = ("status",)
    search_fields = ("number", "user__username")
    readonly_fields = [f.name for f in Order._meta.fields]
    inlines = [OrderItemInline]

    def has_add_permission(self, request):
        return False


@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("order", "from_status", "to_status", "changed_by", "created_at")
    readonly_fields = [f.name for f in OrderStatusHistory._meta.fields]

    def has_add_permission(self, request):
        return False
