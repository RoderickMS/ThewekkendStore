# PayPal Sandbox: único método de pago

TheWeekendStore usa exclusivamente **PayPal Sandbox** (Orders API v2). No existe selección manual de resultados de pago ni una pantalla local para aprobar o rechazar operaciones.

## Configuración

1. Crear una aplicación **Sandbox** en https://developer.paypal.com/dashboard/.
2. Copiar las credenciales **Client ID** y **Secret** de esa aplicación al archivo `.env`.
3. Ajustar `PAYPAL_RETURN_BASE_URL` al origen desde donde accedes a Django, por ejemplo `http://127.0.0.1:8000`. Para desarrollo local, navegar al mismo host elegido.
4. Configurar la base de datos (`DJANGO_DB_ENGINE=postgresql` o `sqlite` para pruebas locales). Instalar dependencias y ejecutar migraciones.
5. Iniciar Django y comprar con una **cuenta comprador Sandbox** diferente de la cuenta comercial.

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

## Flujo de compra

1. El cliente agrega productos al carrito y confirma su dirección en Checkout.
2. Django crea un pedido pendiente y redirige a la ruta de inicio de pago.
3. El backend solicita un token OAuth a PayPal Sandbox, crea la orden por el total calculado en el servidor y obtiene la URL de aprobación.
4. El comprador inicia sesión y aprueba la orden **en la página de PayPal Sandbox**.
5. PayPal regresa al sitio con `token=ORDER_ID`. Django valida el usuario y la referencia, solicita la captura y verifica que sea `COMPLETED` con USD y el mismo importe.
6. Se marca el pedido como pagado y se actualizan las existencias.

En caso de cancelación, el cliente regresa al pedido sin que este se marque como pagado.


## Archivos principales

- `apps/payments/gateways.py`: API PayPal Sandbox, OAuth, crear/consultar/capturar.
- `apps/payments/views.py`: inicio de pago y retorno/cancelación PayPal.
- `apps/payments/services.py`: pago, pedido e inventario.
- `apps/carts/views.py`: checkout y redirección.
- `config/settings.py`: configuración PayPal.
