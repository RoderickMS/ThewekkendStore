from django.urls import path

from . import views

# Se monta en /panel/pedidos/ (config/urls.py). Namespace propio para no
# chocar con las rutas del cliente (`orders:`).
app_name = "orders_panel"

urlpatterns = [
    path("", views.panel_order_list, name="list"),
    path("<str:number>/", views.panel_order_detail, name="detail"),
    path("<str:number>/estado/", views.panel_order_status, name="status"),
]
