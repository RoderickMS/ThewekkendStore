from django.urls import path

from . import views

app_name = "carts"

urlpatterns = [
    path("", views.cart_detail, name="detail"),
    path("agregar/", views.cart_add, name="add"),
    path("item/<int:item_id>/actualizar/", views.cart_update, name="update"),
    path("item/<int:item_id>/eliminar/", views.cart_remove, name="remove"),
    path("checkout/", views.checkout, name="checkout"),
]
