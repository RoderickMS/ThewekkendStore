from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import Address, User


class RegisterForm(UserCreationForm):
    """Registro de clientes (M08). El rol siempre queda en 'cliente':
    un administrador se promueve manualmente desde /admin/, nunca desde
    el formulario público de registro (evita escalada de privilegios)."""

    email = forms.EmailField(required=True, label="Correo electrónico")
    phone = forms.CharField(required=False, label="Teléfono")

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "phone"]

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.CLIENTE
        user.email = self.cleaned_data["email"]
        user.phone = self.cleaned_data.get("phone", "")
        if commit:
            user.save()
        return user


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone"]
        labels = {
            "first_name": "Nombre",
            "last_name": "Apellido",
            "email": "Correo electrónico",
            "phone": "Teléfono",
        }


class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = [
            "full_name",
            "line1",
            "line2",
            "city",
            "state",
            "postal_code",
            "country",
            "phone",
            "is_default",
        ]
        labels = {
            "full_name": "Nombre completo",
            "line1": "Dirección",
            "line2": "Referencia / apto (opcional)",
            "city": "Ciudad",
            "state": "Provincia / estado",
            "postal_code": "Código postal",
            "country": "País",
            "phone": "Teléfono de contacto",
            "is_default": "Usar como dirección predeterminada",
        }
