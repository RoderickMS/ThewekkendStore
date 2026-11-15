from django.urls import path

from . import views

# Se monta en /panel/stock/ (config/urls.py).
app_name = "inventory"

urlpatterns = [
    path("", views.low_stock_alerts, name="low_stock"),
]
