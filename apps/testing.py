"""Fábricas mínimas para las pruebas de las etapas 2 y 3."""
from decimal import Decimal
from itertools import count

from apps.accounts.models import Address, User
from apps.carts.models import Cart, CartItem
from apps.catalog.models import Category, Product, ProductVariant

_seq = count(1)


def make_user(username=None, role=User.Role.CLIENTE, **extra):
    username = username or f"user{next(_seq)}"
    return User.objects.create_user(
        username=username, password="pass12345!", email=f"{username}@example.com", role=role, **extra
    )


def make_address(user, **extra):
    data = dict(full_name="Ana Pérez", line1="Calle 50", city="Panamá", country="Panamá")
    data.update(extra)
    return Address.objects.create(user=user, **data)


def make_category(name, parent=None, **extra):
    return Category.objects.create(name=name, parent=parent, **extra)


def make_variant(stock=5, price="10.00", category=None, name=None, threshold=1, **extra):
    n = next(_seq)
    category = category or make_category(f"Categoría {n}")
    product = Product.objects.create(
        category=category,
        name=name or f"Producto {n}",
        base_price=Decimal(price),
        low_stock_threshold=threshold,
    )
    return ProductVariant.objects.create(
        product=product, sku=f"SKU-{n}", stock_quantity=stock, **extra
    )


def fill_cart(user, *pairs):
    """pairs: (variant, qty)."""
    cart, _ = Cart.objects.get_or_create(user=user)
    for variant, qty in pairs:
        CartItem.objects.update_or_create(cart=cart, variant=variant, defaults={"quantity": qty})
    return cart
