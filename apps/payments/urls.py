from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("paypal/retorno/", views.paypal_return, name="paypal_return"),
    path("paypal/cancelado/", views.paypal_cancel, name="paypal_cancel"),
    path("pedido/<str:number>/pagar/", views.start_payment, name="start"),
]
