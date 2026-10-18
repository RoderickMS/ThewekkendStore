from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("", views.home, name="home"),
    path("panel/", views.panel_home, name="panel_home"),
    path("buscar/", views.search, name="search"),
    path("buscar/sugerencias/", views.search_suggestions, name="search_suggestions"),
    path("categoria/<slug:slug>/", views.category_detail, name="category_detail"),
    path("producto/<slug:slug>/", views.product_detail, name="product_detail"),
]