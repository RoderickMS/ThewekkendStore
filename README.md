# The Weekend Store

Ecommerce en Django + PostgreSQL, con la estética editorial del prototipo
original (clone de RHODE UX en React), migrada a un backend real con
catálogo, inventario, roles y control de stock en servidor.

Este proyecto sigue el plan pactado en la "Respuesta del equipo a la
solicitud de cambio de requerimientos" (MoSCoW, matriz de impacto y orden
de implementación por etapas). **Este repositorio implementa la Etapa 1
completa.**

## Estado del alcance

### mplementado (Etapa 1 — Base del sistema)

| # | Requisito | Dónde |
|---|-----------|-------|
| T01–T03 | Proyecto Django organizado por apps, PostgreSQL y modelo de datos completo | `config/settings.py`, todas las apps en `apps/` |
| M08 | Autenticación y perfiles (registro, login, logout, recuperar/cambiar contraseña, perfil, direcciones) | `apps/accounts` |
| M09 / T05 | Roles (Cliente/Administrador) y rechazo de acceso en servidor | `apps/accounts/permissions.py`, vista `catalog:panel_home` |
| M01 → M02 | Catálogo jerárquico (categorías/subcategorías) y CRUD de productos desde administración | `apps/catalog` (modelos + `admin.py`) |
| M03 | Variantes de producto con stock propio | `apps/catalog/models.py::ProductVariant` |
| M04 | Inventario y movimientos (entrada/ajuste/venta/cancelación/devolución) con trazabilidad | `apps/inventory` |

El resto del **modelo de datos completo** (carritos, pedidos, pagos) ya
está diseñado y migrado (`apps/carts`, `apps/orders`, `apps/payments`)
para evitar refactors tardíos, tal como se pactó en la negociación, pero
su lógica de negocio y vistas se implementan en las etapas siguientes:

- **Etapa 2** (Stock y carrito): M05, M10→M11, M06→T06, M07, M12, M13→T04.
- **Etapa 3** (Pedidos y pagos): M14+M16, M15, M17, M18, M19, M21.
- **Etapa 4** (Administración, pruebas y extras): M20, M22, T08–T09, S01/S02/S04/S06, Could Have.

## Cómo funciona el panel administrativo (Etapa 1)

Se usa el **admin de Django** (personalizado) como panel administrativo:
ya exige `is_staff=True` (que solo tienen los usuarios con
`role=administrador`) y cubre el CRUD completo de categorías, productos,
imágenes y variantes, más el registro de movimientos de inventario (a
través de un formulario que llama a `apps.inventory.services.register_movement`,
nunca editando el stock directamente).

Además existe `/panel/`, una vista propia protegida con
`@admin_required` (decorador, no solo `is_staff`), pensada como base para
el dashboard y el detalle administrativo de pedidos de etapas
posteriores (M19/M20). **Un cliente que entra directo a `/panel/` o a
`/admin/` recibe 403/redirect del servidor**, verificado durante el
desarrollo.

## Puesta en marcha

### 1. Crear el entorno conda

```bash
conda env create -f environment.yml
conda activate the_weekend_store
```

### 2. Configurar PostgreSQL

Crea la base de datos y el usuario (ajusta como prefieras):

```sql
CREATE DATABASE the_weekend_store;
CREATE USER weekend_store_user WITH PASSWORD 'weekend_store_pass';
GRANT ALL PRIVILEGES ON DATABASE the_weekend_store TO weekend_store_user;
```

Copia `.env.example` a `.env` y ajusta las variables si usaste otros
valores:

```bash
cp .env.example .env
```

### 3. Migrar y crear un superusuario

```bash
python manage.py migrate
python manage.py createsuperuser
```

Para que ese superusuario también aparezca marcado como
`role=administrador` en la tienda, entra a `/admin/accounts/user/`,
edítalo y pon el campo "Rol de la tienda" en *Administrador* (los
superusuarios ya tienen acceso total de todas formas gracias a
`is_admin_role`).

### 4. Correr el servidor

```bash
python manage.py runserver
```

- Tienda: <http://127.0.0.1:8000/>
- Panel administrativo propio: <http://127.0.0.1:8000/panel/>
- Admin de Django (CRUD de catálogo/inventario): <http://127.0.0.1:8000/admin/>

## Notas de diseño

- **Visual**: `static/css/style.css` es una adaptación directa del CSS
  del prototipo original (`clone de RHODE UX`), sin Tailwind (no se usaba
  ninguna utilidad de Tailwind en el markup original, solo clases
  propias). Las imágenes de producto del hero/manifiesto siguen apuntando
  al CDN del prototipo (`ext.same-assets.com`) como **placeholder visual**
  — reemplázalas por fotografía propia antes de una demo/entrega final.
- **JS**: `static/js/site.js` reemplaza en JS vanilla la interactividad
  que el prototipo resolvía con React (`useState`/`useRef`): paneles de
  menú/búsqueda y el rail de productos. El carrito real se conecta en la
  Etapa 2.
- **Stock**: `ProductVariant.stock_quantity` es un caché que **solo**
  debe modificarse a través de `apps.inventory.services.register_movement`
  (usa `select_for_update` dentro de una transacción atómica), para que
  nunca quede desincronizado del historial de movimientos y sentando la
  base de la reserva/validación concurrente de la Etapa 2 (M13/T04).
