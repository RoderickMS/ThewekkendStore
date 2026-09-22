from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("registro/", views.RegisterView.as_view(), name="register"),
    path("iniciar-sesion/", views.WeekendStoreLoginView.as_view(), name="login"),
    path("cerrar-sesion/", views.WeekendStoreLogoutView.as_view(), name="logout"),
    path("perfil/", views.profile, name="profile"),
    path("perfil/direcciones/nueva/", views.address_create, name="address_create"),
    path("perfil/direcciones/<int:pk>/editar/", views.address_update, name="address_update"),
    path("perfil/direcciones/<int:pk>/eliminar/", views.address_delete, name="address_delete"),
    # Recuperación de contraseña (M08)
    path(
        "contrasena/restablecer/",
        auth_views.PasswordResetView.as_view(
            template_name="accounts/password_reset.html",
            email_template_name="accounts/password_reset_email.html",
            subject_template_name="accounts/password_reset_subject.txt",
            success_url="/cuenta/contrasena/restablecer/enviado/",
        ),
        name="password_reset",
    ),
    path(
        "contrasena/restablecer/enviado/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "contrasena/restablecer/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url="/cuenta/contrasena/restablecer/completo/",
        ),
        name="password_reset_confirm",
    ),
    path(
        "contrasena/restablecer/completo/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    path(
        "contrasena/cambiar/",
        auth_views.PasswordChangeView.as_view(
            template_name="accounts/password_change.html",
            success_url="/cuenta/perfil/",
        ),
        name="password_change",
    ),
]
