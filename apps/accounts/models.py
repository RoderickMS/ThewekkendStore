"""
Modelos de cuentas, roles y direcciones.

- M08 Autenticación y perfiles: modelo de Usuario personalizado + Address.
- M09 Roles y permisos: campo `role` que diferencia Cliente/Administrador.
  La aplicación real del permiso (rechazo en servidor) vive en
  apps/accounts/permissions.py (T05).
"""
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Usuario del sistema. Un mismo modelo cubre Cliente y Administrador
    (M09): se diferencian por el campo `role`, no por tener tablas distintas.
    """

    class Role(models.TextChoices):
        CLIENTE = "cliente", "Cliente"
        ADMIN = "administrador", "Administrador"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CLIENTE,
        help_text="Diferencia Cliente de Administrador (M09).",
    )
    phone = models.CharField(max_length=20, blank=True, verbose_name="Teléfono")

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"

    @property
    def is_admin_role(self) -> bool:
        """True si el usuario debe tratarse como Administrador.

        Un superusuario de Django siempre cuenta como administrador aunque
        el campo `role` no se haya sincronizado manualmente.
        """
        return self.is_superuser or self.role == self.Role.ADMIN

    def save(self, *args, **kwargs):
        # Todo usuario con role=administrador debe poder entrar a /admin/.
        if self.role == self.Role.ADMIN:
            self.is_staff = True
        super().save(*args, **kwargs)

    def __str__(self):
        return self.get_full_name() or self.username


class Address(models.Model):
    """Dirección de un usuario. Se usará para checkout/facturación en la
    Etapa 2 (M12); se modela ahora junto con el resto del esquema (T01)
    para evitar migraciones tardías, según lo pactado en la negociación."""

    user = models.ForeignKey(
        User, related_name="addresses", on_delete=models.CASCADE, verbose_name="usuario"
    )
    full_name = models.CharField(max_length=150, verbose_name="nombre completo")
    line1 = models.CharField(max_length=255, verbose_name="dirección")
    line2 = models.CharField(max_length=255, blank=True, verbose_name="referencia / apto")
    city = models.CharField(max_length=100, verbose_name="ciudad")
    state = models.CharField(max_length=100, blank=True, verbose_name="provincia / estado")
    postal_code = models.CharField(max_length=20, blank=True, verbose_name="código postal")
    country = models.CharField(max_length=100, default="Panamá", verbose_name="país")
    phone = models.CharField(max_length=20, blank=True, verbose_name="teléfono de contacto")
    is_default = models.BooleanField(default=False, verbose_name="dirección predeterminada")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "dirección"
        verbose_name_plural = "direcciones"
        ordering = ["-is_default", "-created_at"]

    def __str__(self):
        return f"{self.full_name} — {self.line1}, {self.city}"

    def save(self, *args, **kwargs):
        # Solo puede existir una dirección predeterminada por usuario.
        if self.is_default:
            Address.objects.filter(user=self.user, is_default=True).exclude(pk=self.pk).update(
                is_default=False
            )
        super().save(*args, **kwargs)
