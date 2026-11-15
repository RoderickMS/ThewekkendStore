from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("cuenta/", include("apps.accounts.urls")),
    path("carrito/", include("apps.carts.urls")),
    path("pedidos/", include("apps.orders.urls")),
    path("pagos/", include("apps.payments.urls")),
    # Panel administrativo (M19, M21). Van antes que catalog, que define /panel/.
    path("panel/pedidos/", include("apps.orders.panel_urls")),
    path("panel/stock/", include("apps.inventory.urls")),
    path("", include("apps.catalog.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
