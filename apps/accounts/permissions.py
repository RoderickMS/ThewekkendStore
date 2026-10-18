"""
T05 — Seguridad por rol en servidor.

Estas utilidades son la aplicación real de M09 (Roles y permisos): protegen
vistas basadas en función y basadas en clase para que un Cliente que intente
acceder directamente a una URL administrativa reciba un rechazo (403) del
servidor, sin depender de que el navegador oculte o no un botón.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied


def _is_admin(user) -> bool:
    return bool(user and user.is_authenticated and getattr(user, "is_admin_role", False))


def admin_required(view_func):
    """Decorador para vistas basadas en función: exige sesión iniciada y
    rol Administrador. Lanza 403 (PermissionDenied) en servidor si no se
    cumple, en vez de confiar en ocultar enlaces en el HTML."""

    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not _is_admin(request.user):
            raise PermissionDenied("Se requieren permisos de administrador.")
        return view_func(request, *args, **kwargs)

    return _wrapped


class AdminRequiredMixin(UserPassesTestMixin):
    """Mixin para Class-Based Views administrativas."""

    raise_exception = True

    def test_func(self):
        return _is_admin(self.request.user)

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(self.request.get_full_path(), self.get_login_url())
        raise PermissionDenied("Se requieren permisos de administrador.")
