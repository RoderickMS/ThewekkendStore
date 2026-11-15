from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.carts.models import Cart, CartItem
from apps.carts.services import merge_guest_cart_into_user
from apps.inventory.models import StockReservation
from apps.orders.models import Order
from apps.testing import fill_cart, make_address, make_user, make_variant


class CartCountTests(TestCase):
    def test_navigation_count_tracks_cart_quantity(self):
        variant = make_variant(stock=3)
        home_url = reverse("catalog:home")
        add_url = reverse("carts:add")

        self.assertContains(self.client.get(home_url), "carrito (0)")
        response = self.client.post(add_url, {"variant_id": variant.pk, "quantity": 2})
        self.assertRedirects(response, variant.product.get_absolute_url())

        self.assertContains(self.client.get(home_url), "carrito (2)")


class CheckoutReservationTests(TestCase):
    def setUp(self):
        self.variant = make_variant(stock=3, price="10.00")
        self.user = make_user("ana")
        self.address = make_address(self.user)
        self.client.force_login(self.user)

    def add(self, qty=1):
        return self.client.post(reverse("carts:add"), {"variant_id": self.variant.pk, "quantity": qty})

    def test_reloading_checkout_does_not_extend_reservation(self):
        self.add(2)
        self.client.get(reverse("carts:checkout"))
        reservation = StockReservation.objects.get(is_active=True)
        soon = timezone.now() + timedelta(minutes=2)
        StockReservation.objects.filter(pk=reservation.pk).update(expires_at=soon)
        self.client.get(reverse("carts:checkout"))
        reservation.refresh_from_db()
        self.assertEqual(reservation.expires_at, soon)

    def test_changing_the_cart_releases_the_checkout_reservation(self):
        self.add(2)
        self.client.get(reverse("carts:checkout"))
        self.assertEqual(StockReservation.objects.filter(is_active=True).count(), 1)
        item = CartItem.objects.get()
        self.client.post(reverse("carts:update", args=[item.pk]), {"quantity": 1})
        self.assertFalse(StockReservation.objects.filter(is_active=True).exists())
        self.client.get(reverse("carts:checkout"))
        self.assertEqual(StockReservation.objects.get(is_active=True).quantity, 1)
        self.add(1)  # añadir también libera
        self.assertFalse(StockReservation.objects.filter(is_active=True).exists())

    def test_second_customer_is_blocked_while_first_is_in_checkout(self):
        self.add(3)
        self.client.get(reverse("carts:checkout"))
        beto = make_user("beto")
        fill_cart(beto, (self.variant, 1))
        self.client.force_login(beto)
        response = self.client.get(reverse("carts:checkout"))
        self.assertRedirects(response, reverse("carts:detail"))
        self.assertFalse(StockReservation.objects.filter(user=beto).exists())

    def test_checkout_without_stock_creates_no_order(self):
        self.add(2)
        self.client.get(reverse("carts:checkout"))
        beto = make_user("beto")
        fill_cart(beto, (self.variant, 2))
        self.client.force_login(beto)
        response = self.client.post(reverse("carts:checkout"), {"address_id": make_address(beto).pk})
        self.assertRedirects(response, reverse("carts:detail"))
        self.assertFalse(Order.objects.exists())

    def test_cannot_check_out_with_someone_elses_address(self):
        self.add(1)
        other_address = make_address(make_user("otra"))
        response = self.client.post(reverse("carts:checkout"), {"address_id": other_address.pk})
        self.assertEqual(response.status_code, 200)  # vuelve al formulario con el aviso
        self.assertFalse(Order.objects.exists())

    def test_new_address_is_saved_and_used(self):
        self.add(1)
        response = self.client.post(
            reverse("carts:checkout"),
            {
                "address_id": "new",
                "full_name": "Luis Gómez",
                "line1": "Vía España 10",
                "city": "Panamá",
                "country": "Panamá",
            },
        )
        order = Order.objects.get()
        self.assertRedirects(response, reverse("payments:paypal", args=[order.payment.reference]))
        self.assertEqual(order.shipping_name, "Luis Gómez")
        self.assertEqual(self.user.addresses.count(), 2)

    def test_empty_cart_cannot_check_out(self):
        self.assertRedirects(self.client.get(reverse("carts:checkout")), reverse("carts:detail"))

    def test_guest_cart_merge_releases_stale_reservation(self):
        fill_cart(self.user, (self.variant, 1))
        self.client.get(reverse("carts:checkout"))
        guest = Cart.objects.create(session_key="guest-1")
        CartItem.objects.create(cart=guest, variant=self.variant, quantity=1)
        merge_guest_cart_into_user("guest-1", self.user)
        self.assertEqual(CartItem.objects.get(cart__user=self.user).quantity, 2)
        self.assertFalse(StockReservation.objects.filter(is_active=True).exists())
