"""
Catálogo: categorías jerárquicas (M01), productos con CRUD administrativo
(M02) y variantes con stock propio (M03).

El stock "real" (cantidad disponible) vive en ProductVariant.stock_quantity
y se modifica exclusivamente a través de apps.inventory.services, para que
todo cambio quede registrado como un StockMovement (M04) y sea imposible
que el stock quede negativo (M05, aplicado en la Etapa 2).
"""
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class Category(models.Model):
    """Categoría con soporte de subcategorías (self-FK) para el catálogo
    jerárquico exigido en M01."""

    name = models.CharField(max_length=100, verbose_name="nombre")
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.CASCADE,
        verbose_name="categoría padre",
    )
    description = models.TextField(blank=True, verbose_name="descripción")
    is_active = models.BooleanField(default=True, verbose_name="activa")
    order = models.PositiveIntegerField(default=0, verbose_name="orden")

    class Meta:
        verbose_name = "categoría"
        verbose_name_plural = "categorías"
        ordering = ["order", "name"]

    def __str__(self):
        return f"{self.parent} › {self.name}" if self.parent_id else self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalog:category_detail", args=[self.slug])

    @property
    def is_root(self) -> bool:
        return self.parent_id is None


class Product(models.Model):
    """Producto del catálogo. Un producto inactivo nunca debe poder
    agregarse al carrito ni comprarse (criterio de aceptación de M01)."""

    category = models.ForeignKey(
        Category, related_name="products", on_delete=models.PROTECT, verbose_name="categoría"
    )
    name = models.CharField(max_length=200, verbose_name="nombre")
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    short_description = models.CharField(
        max_length=255, blank=True, verbose_name="descripción corta"
    )
    description = models.TextField(blank=True, verbose_name="descripción")
    base_price = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name="precio base"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="activo",
        help_text="Un producto inactivo no aparece en el catálogo ni puede comprarse.",
    )
    low_stock_threshold = models.PositiveIntegerField(
        default=5, verbose_name="umbral de bajo stock (M21)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "producto"
        verbose_name_plural = "productos"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                counter += 1
                slug = f"{base_slug}-{counter}"
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalog:product_detail", args=[self.slug])

    @property
    def total_stock(self) -> int:
        return sum(v.stock_quantity for v in self.variants.filter(is_active=True))

    @property
    def is_purchasable(self) -> bool:
        """Regla usada por el carrito (Etapa 2): producto activo y con
        stock en al menos una variante."""
        return self.is_active and self.total_stock > 0

    @property
    def primary_image(self):
        # Se recorre en Python (no .filter()/.first() sobre el manager) para
        # aprovechar prefetch_related("images") en los listados y evitar
        # una consulta extra por producto.
        images = list(self.images.all())
        if not images:
            return None
        return next((img for img in images if img.is_primary), images[0])

    @property
    def secondary_image(self):
        """Segunda imagen de la galería: se usa para el efecto "hover"
        de las tarjetas de producto (como en el sitio original, que muestra
        una foto alternativa — p. ej. de estilo de vida — al pasar el
        cursor). Devuelve None si el producto solo tiene una foto."""
        images = list(self.images.all())
        primary = self.primary_image
        for image in images:
            if image.pk != getattr(primary, "pk", None):
                return image
        return None


class ProductImage(models.Model):
    product = models.ForeignKey(
        Product, related_name="images", on_delete=models.CASCADE, verbose_name="producto"
    )
    image = models.ImageField(upload_to="products/%Y/%m/", verbose_name="imagen")
    alt_text = models.CharField(max_length=150, blank=True, verbose_name="texto alternativo")
    is_primary = models.BooleanField(default=False, verbose_name="imagen principal")
    order = models.PositiveIntegerField(default=0, verbose_name="orden")

    class Meta:
        verbose_name = "imagen de producto"
        verbose_name_plural = "imágenes de producto"
        ordering = ["order", "id"]

    def __str__(self):
        return f"Imagen de {self.product.name} ({'principal' if self.is_primary else self.order})"

    def save(self, *args, **kwargs):
        # Solo puede existir una imagen principal por producto (mismo
        # patrón que Address.is_default en apps.accounts).
        if self.is_primary:
            ProductImage.objects.filter(product=self.product, is_primary=True).exclude(
                pk=self.pk
            ).update(is_primary=False)
        super().save(*args, **kwargs)


class ProductVariant(models.Model):
    """Variante de un producto (talla, color, presentación...). El stock
    se controla aquí y no a nivel de Product (M03): no es posible comprar
    una variante sin stock aunque el producto en general sí tenga otras
    variantes disponibles."""

    product = models.ForeignKey(
        Product, related_name="variants", on_delete=models.CASCADE, verbose_name="producto"
    )
    sku = models.CharField(max_length=64, unique=True, verbose_name="SKU")
    attribute_name = models.CharField(
        max_length=50,
        blank=True,
        default="Presentación",
        verbose_name="atributo",
        help_text="Ej. Talla, Color, Presentación.",
    )
    attribute_value = models.CharField(
        max_length=50,
        blank=True,
        default="Único",
        verbose_name="valor del atributo",
        help_text="Ej. M, Rojo, 30ml, Único (si el producto no tiene variantes reales).",
    )
    price_override = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="precio propio (opcional)",
        help_text="Si se deja vacío, usa el precio base del producto.",
    )
    stock_quantity = models.PositiveIntegerField(default=0, verbose_name="stock disponible")
    is_active = models.BooleanField(default=True, verbose_name="activa")
    image = models.ImageField(
        upload_to="variants/%Y/%m/",
        null=True,
        blank=True,
        verbose_name="imagen de la variante",
        help_text="Opcional: úsala cuando la variante se vea distinto (p. ej. un color). "
        "Si se deja vacía, la vista de producto usa la imagen general del producto.",
    )
    description_override = models.TextField(
        blank=True,
        verbose_name="descripción propia (opcional)",
        help_text="Opcional: úsala cuando esta variante necesite su propio texto "
        "(p. ej. rendimiento distinto según la presentación). Si se deja vacía, "
        "la vista de producto usa la descripción general del producto.",
    )

    class Meta:
        verbose_name = "variante de producto"
        verbose_name_plural = "variantes de producto"
        ordering = ["attribute_name", "attribute_value"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "attribute_name", "attribute_value"],
                name="unique_variant_per_attribute_value",
            )
        ]

    def __str__(self):
        return f"{self.product.name} — {self.label}"

    @property
    def label(self) -> str:
        if self.attribute_name and self.attribute_value:
            return f"{self.attribute_name}: {self.attribute_value}"
        return self.sku

    @property
    def price(self):
        return self.price_override if self.price_override is not None else self.product.base_price

    @property
    def description(self) -> str:
        return self.description_override or self.product.description or self.product.short_description

    @property
    def is_in_stock(self) -> bool:
        return self.is_active and self.stock_quantity > 0

    @property
    def is_low_stock(self) -> bool:
        """Usado por M21 (alertas de bajo inventario, Etapa 3)."""
        return self.stock_quantity <= self.product.low_stock_threshold
