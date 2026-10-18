"""
Panel administrativo de catálogo (M02 CRUD de productos).

Se usa el admin de Django como "panel administrativo" para esta etapa:
ya exige `is_staff=True` (solo usuarios con role=administrador lo tienen,
ver apps.accounts.models.User.save) y cubre crear, editar,
activar/desactivar y consultar productos con todos sus datos, incluyendo
categoría, precio, imágenes y variantes/inventario en la misma pantalla.
"""
from django.contrib import admin
from django.utils.html import format_html

from .models import Category, Product, ProductImage, ProductVariant


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ("image", "alt_text", "is_primary", "order")


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1
    fields = (
        "sku",
        "attribute_name",
        "attribute_value",
        "image",
        "description_override",
        "price_override",
        "stock_quantity",
        "is_active",
    )
    help_text = (
        "El stock se controla por variante (M03). Movimientos de entrada/ajuste "
        "deben registrarse desde Inventario para dejar trazabilidad (M04)."
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "is_active", "order")
    list_filter = ("is_active", "parent")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("order", "name")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "base_price",
        "is_active",
        "total_stock_display",
        "low_stock_threshold",
    )
    list_filter = ("is_active", "category")
    search_fields = ("name", "description", "short_description")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ProductImageInline, ProductVariantInline]
    actions = ["activate_products", "deactivate_products"]

    @admin.display(description="Stock total")
    def total_stock_display(self, obj):
        stock = obj.total_stock
        color = "#b3261e" if stock == 0 else ("#8a6d00" if stock <= obj.low_stock_threshold else "#1b7a3d")
        return format_html('<b style="color:{}">{}</b>', color, stock)

    @admin.action(description="Activar productos seleccionados")
    def activate_products(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description="Desactivar productos seleccionados")
    def deactivate_products(self, request, queryset):
        queryset.update(is_active=False)


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = (
        "sku",
        "product",
        "attribute_name",
        "attribute_value",
        "stock_quantity",
        "is_active",
        "is_low_stock",
    )
    list_filter = ("is_active", "product__category")
    search_fields = ("sku", "product__name")
    autocomplete_fields = ["product"]
