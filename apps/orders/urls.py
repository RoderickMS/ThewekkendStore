from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("", views.order_list, name="list"),
    path("<str:number>/", views.order_detail, name="detail"),
    path("<str:number>/cancelar/", views.order_cancel, name="cancel"),
]
