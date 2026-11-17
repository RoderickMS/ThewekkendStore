from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import number_format

from apps.carts.models import CartItem
from apps.inventory.models import StockMovement, StockReservation
from apps.inventory.services import get_available_stock
from apps.orders.models import Order
from apps.orders.services import (
    InvalidTransition,
    admin_transitions,
    cancel_by_customer,
    change_status,
    create_order_from_cart,
    expire_pending_orders,
)
from apps.payments.models import Payment
from apps.payments.services import initiate_payment, process_payment
from apps.testing import fill_cart, make_address, make_user, make_variant


class OrderFlowTests(TestCase):
    def setUp(self):
        self.variant = make_variant(stock=5, price="12.50", name="Sérum")
        self.user = make_user("ana")
        self.address = make_address(self.user)
        self.cart = fill_cart(self.user, (self.variant, 2))

    def new_order(self):
        return create_order_from_cart(self.user, self.cart, self.address)

    # M14 ---------------------------------------------------------------
    def test_order_snapshot_and_server_side_price(self):
        order = self.new_order()
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)
        self.assertEqual(str(order.total), "25.00")
        item = order.items.get()
        self.assertEqual((item.product_name, str(item.unit_price), item.quantity), ("Sérum", "12.50", 2))
        # cambios posteriores no alteran el historial
        self.variant.product.name = "Otro nombre"
        self.variant.product.base_price = 99
        self.variant.product.save()
        self.address.line1 = "Cambiada"
        self.address.save()
        item.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(item.product_name, "Sérum")
        self.assertEqual(str(item.unit_price), "12.50")
        self.assertIn("Calle 50", order.shipping_address)
        self.assertEqual(order.status_history.count(), 1)

    def test_deleting_address_keeps_order(self):
        order = self.new_order()
        self.address.delete()
        order.refresh_from_db()
        self.assertIsNone(order.address)
        self.assertIn("Calle 50", order.shipping_address)

    def test_order_reserves_but_does_not_deduct(self):
        self.new_order()
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 5)
        self.assertEqual(get_available_stock(self.variant, exclude_user=make_user("otro")), 3)

    def test_new_checkout_replaces_previous_pending_order(self):
        first = self.new_order()
        second = self.new_order()
        first.refresh_from_db()
        self.assertEqual(first.status, Order.Status.CANCELLED)
        self.assertEqual(second.status, Order.Status.PENDING_PAYMENT)
        self.assertEqual(StockReservation.objects.filter(is_active=True).count(), 1)

    def test_cannot_use_someone_elses_address(self):
        other = make_user("otra")
        with self.assertRaises(Exception):
            create_order_from_cart(other, fill_cart(other, (self.variant, 1)), self.address)

    # M16 / M17 ---------------------------------------------------------
    def test_successful_payment_confirms_order_and_deducts_stock(self):
        order = self.new_order()
        payment = initiate_payment(order)
        outcome = process_payment(payment.reference, self.user, "approve")
        self.assertTrue(outcome.ok)
        order.refresh_from_db()
        payment.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertEqual(payment.status, Payment.Status.SUCCESS)
        self.assertIsNotNone(payment.paid_at)
        self.assertEqual(self.variant.stock_quantity, 3)
        movement = StockMovement.objects.get(movement_type="venta")
        self.assertEqual((movement.quantity, movement.stock_after), (-2, 3))
        self.assertFalse(StockReservation.objects.filter(is_active=True).exists())
        self.assertFalse(CartItem.objects.filter(cart=self.cart).exists())
        self.assertEqual(
            list(order.status_history.order_by("id").values_list("to_status", flat=True)),
            ["pendiente_pago", "pagado"],
        )

    def test_payment_is_idempotent(self):
        order = self.new_order()
        ref = initiate_payment(order).reference
        process_payment(ref, self.user, "approve")
        again = process_payment(ref, self.user, "approve")
        self.assertTrue(again.already_paid)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 3)
        self.assertEqual(StockMovement.objects.filter(movement_type="venta").count(), 1)

    def test_declined_payment_keeps_order_pending_and_can_retry(self):
        order = self.new_order()
        payment = initiate_payment(order)
        first_ref = payment.reference
        outcome = process_payment(first_ref, self.user, "decline")
        self.assertFalse(outcome.ok)
        order.refresh_from_db()
        payment.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)
        self.assertEqual(payment.status, Payment.Status.FAILED)
        self.assertEqual(self.variant.stock_quantity, 5)
        self.assertTrue(StockReservation.objects.filter(order=order, is_active=True).exists())

        retry = initiate_payment(order)
        self.assertNotEqual(retry.reference, first_ref)
        # el intento viejo ya no existe: no se puede aprobar ni por error
        with self.assertRaises(Payment.DoesNotExist):
            process_payment(first_ref, self.user, "approve")
        self.assertTrue(process_payment(retry.reference, self.user, "approve").ok)

    def test_cancelled_at_gateway_keeps_order_pending(self):
        order = self.new_order()
        ref = initiate_payment(order).reference
        process_payment(ref, self.user, "cancel")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)
        self.assertEqual(order.payment.status, Payment.Status.CANCELLED)

    def test_other_user_cannot_pay_my_order(self):
        ref = initiate_payment(self.new_order()).reference
        with self.assertRaises(Payment.DoesNotExist):
            process_payment(ref, make_user("intruso"), "approve")

    def test_no_charge_when_stock_vanished_after_reservation_expired(self):
        order = self.new_order()
        ref = initiate_payment(order).reference
        # la reserva vence y otro cliente compra todo el stock
        StockReservation.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        rival = make_user("rival")
        rival_order = create_order_from_cart(
            rival, fill_cart(rival, (self.variant, 5)), make_address(rival)
        )
        process_payment(initiate_payment(rival_order).reference, rival, "approve")

        outcome = process_payment(ref, self.user, "approve")
        self.assertFalse(outcome.ok)
        order.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertNotEqual(order.payment.status, Payment.Status.SUCCESS)
        self.assertEqual(self.variant.stock_quantity, 0)  # solo descontó el rival
        self.assertEqual(StockMovement.objects.filter(movement_type="venta").count(), 1)

    def test_expired_but_unclaimed_stock_still_allows_payment(self):
        order = self.new_order()
        ref = initiate_payment(order).reference
        StockReservation.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertTrue(process_payment(ref, self.user, "approve").ok)

    # M15 ---------------------------------------------------------------
    def test_customer_can_cancel_only_pending(self):
        order = self.new_order()
        cancel_by_customer(order, self.user)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(get_available_stock(self.variant), 5)
        with self.assertRaises(InvalidTransition):
            cancel_by_customer(order, self.user)

    def test_paid_order_cannot_be_cancelled_by_customer(self):
        order = self.new_order()
        process_payment(initiate_payment(order).reference, self.user, "approve")
        order.refresh_from_db()
        with self.assertRaises(InvalidTransition):
            cancel_by_customer(order, self.user)

    def test_invalid_transitions_rejected(self):
        order = self.new_order()
        with self.assertRaises(InvalidTransition):
            change_status(order, Order.Status.DELIVERED)
        cancel_by_customer(order, self.user)
        with self.assertRaises(InvalidTransition):
            change_status(order, Order.Status.PAID)

    def test_admin_cannot_mark_pending_as_paid(self):
        order = self.new_order()
        self.assertEqual([v for v, _ in admin_transitions(order)], ["cancelado"])

    def test_status_history_displays_generic_messages_and_preserves_custom_note(self):
        order = self.new_order()
        entry = order.status_history.get()
        expected = {
            Order.Status.PENDING_PAYMENT: "Pedido creado, en espera del pago.",
            Order.Status.PAID: "Pago confirmado.",
            Order.Status.PREPARING: "Tu pedido está siendo preparado.",
            Order.Status.SHIPPED: "Tu pedido ha sido enviado.",
            Order.Status.DELIVERED: "Tu pedido ha sido entregado.",
            Order.Status.CANCELLED: "Tu pedido ha sido cancelado.",
        }
        for status, message in expected.items():
            entry.to_status = status
            entry.note = ""
            self.assertEqual(entry.display_message, message)

        entry.to_status = Order.Status.PENDING_PAYMENT
        entry.note = "Pedido creado; stock reservado mientras se completa el pago."
        self.assertEqual(entry.display_message, expected[Order.Status.PENDING_PAYMENT])
        entry.to_status = Order.Status.PAID
        entry.note = "Pago confirmado (paypal_sandbox, ref. ABC123)."
        self.assertEqual(entry.display_message, expected[Order.Status.PAID])
        entry.to_status = Order.Status.PREPARING
        entry.note = "preparando tu pedido con cuidado"
        self.assertEqual(entry.display_message, "preparando tu pedido con cuidado")

    def test_cancelling_paid_order_restocks_and_refunds(self):
        order = self.new_order()
        process_payment(initiate_payment(order).reference, self.user, "approve")
        order.refresh_from_db()
        admin = make_user("jefe", role="administrador")
        change_status(order, Order.Status.CANCELLED, user=admin, note="a pedido del cliente")
        order.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(order.payment.status, Payment.Status.REFUNDED)
        self.assertEqual(self.variant.stock_quantity, 5)
        self.assertTrue(StockMovement.objects.filter(movement_type="cancelacion", quantity=2).exists())

    def test_fulfilment_path(self):
        order = self.new_order()
        process_payment(initiate_payment(order).reference, self.user, "approve")
        admin = make_user("jefe", role="administrador")
        for status in ("en_preparacion", "enviado", "entregado"):
            change_status(order, status, user=admin)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.DELIVERED)
        self.assertEqual(order.status_history.count(), 5)
        with self.assertRaises(InvalidTransition):
            change_status(order, Order.Status.CANCELLED, user=admin)

    # Expiración --------------------------------------------------------
    def test_expired_pending_order_is_cancelled_and_stock_released(self):
        order = self.new_order()
        Order.objects.filter(pk=order.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        StockReservation.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(expire_pending_orders(), 1)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)
        self.assertEqual(expire_pending_orders(), 0)

    def test_expiry_never_touches_paid_orders(self):
        order = self.new_order()
        process_payment(initiate_payment(order).reference, self.user, "approve")
        Order.objects.filter(pk=order.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(expire_pending_orders(), 0)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)


class OrderViewsTests(TestCase):
    """Flujo completo por HTTP: checkout -> simulador PayPal -> historial."""

    def setUp(self):
        self.variant = make_variant(stock=4, price="20.00", name="Bálsamo")
        self.user = make_user("ana")
        self.address = make_address(self.user)
        self.client.force_login(self.user)

    def test_full_http_flow(self):
        self.client.post(reverse("carts:add"), {"variant_id": self.variant.pk, "quantity": 2})
        page = self.client.get(reverse("carts:checkout"))
        self.assertContains(page, "reservados")
        self.assertEqual(StockReservation.objects.filter(is_active=True, order__isnull=True).count(), 1)

        response = self.client.post(reverse("carts:checkout"), {"address_id": self.address.pk})
        order = Order.objects.get()
        payment = order.payment
        self.assertRedirects(response, reverse("payments:paypal", args=[payment.reference]))

        sim = self.client.get(reverse("payments:paypal", args=[payment.reference]))
        self.assertContains(sim, "pasarela de pago de pruebas")
        # los importes se muestran con el formato numérico del idioma activo
        self.assertContains(sim, number_format(Decimal("40"), decimal_pos=2))

        done = self.client.post(
            reverse("payments:paypal_resolve", args=[payment.reference]), {"action": "approve"}
        )
        self.assertRedirects(done, reverse("orders:detail", args=[order.number]))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)

        listing = self.client.get(reverse("orders:list"))
        self.assertContains(listing, order.number)
        detail = self.client.get(reverse("orders:detail", args=[order.number]))
        self.assertContains(detail, "bálsamo")
        self.assertContains(detail, "pagado")

    def test_cart_change_releases_checkout_reservation(self):
        self.client.post(reverse("carts:add"), {"variant_id": self.variant.pk, "quantity": 2})
        self.client.get(reverse("carts:checkout"))
        item = CartItem.objects.get()
        self.client.post(reverse("carts:remove", args=[item.pk]))
        self.assertFalse(StockReservation.objects.filter(is_active=True).exists())

    def test_amount_comes_from_server_not_client(self):
        self.client.post(reverse("carts:add"), {"variant_id": self.variant.pk, "quantity": 1})
        self.client.post(
            reverse("carts:checkout"), {"address_id": self.address.pk, "total": "0.01", "price": "0.01"}
        )
        self.assertEqual(str(Order.objects.get().total), "20.00")

    def test_orders_are_private(self):
        self.client.post(reverse("carts:add"), {"variant_id": self.variant.pk, "quantity": 1})
        self.client.post(reverse("carts:checkout"), {"address_id": self.address.pk})
        order = Order.objects.get()
        ref = order.payment.reference
        self.client.logout()
        self.client.force_login(make_user("intruso"))
        self.assertEqual(self.client.get(reverse("orders:detail", args=[order.number])).status_code, 404)
        self.assertEqual(self.client.get(reverse("payments:paypal", args=[ref])).status_code, 404)
        self.assertEqual(
            self.client.post(reverse("payments:paypal_resolve", args=[ref]), {"action": "approve"}).status_code,
            404,
        )
        self.assertEqual(self.client.post(reverse("orders:cancel", args=[order.number])).status_code, 404)
        self.assertNotIn(order.number, self.client.get(reverse("orders:list")).content.decode())

    def test_login_required(self):
        self.client.logout()
        for url in (reverse("orders:list"), reverse("carts:checkout")):
            self.assertEqual(self.client.get(url).status_code, 302)

    def test_simulator_disabled_by_setting(self):
        self.client.post(reverse("carts:add"), {"variant_id": self.variant.pk, "quantity": 1})
        self.client.post(reverse("carts:checkout"), {"address_id": self.address.pk})
        ref = Order.objects.get().payment.reference
        with self.settings(PAYMENT_GATEWAY="otra"):
            self.assertEqual(self.client.get(reverse("payments:paypal", args=[ref])).status_code, 404)

    def test_customer_cancel_via_http(self):
        self.client.post(reverse("carts:add"), {"variant_id": self.variant.pk, "quantity": 1})
        self.client.post(reverse("carts:checkout"), {"address_id": self.address.pk})
        order = Order.objects.get()
        self.client.post(reverse("orders:cancel", args=[order.number]))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELLED)


class AdminPanelTests(TestCase):
    def setUp(self):
        self.admin = make_user("jefe", role="administrador")
        self.customer = make_user("ana")
        self.variant = make_variant(stock=3, price="5.00", threshold=3, name="Gloss")
        cart = fill_cart(self.customer, (self.variant, 1))
        self.order = create_order_from_cart(self.customer, cart, make_address(self.customer))
        process_payment(initiate_payment(self.order).reference, self.customer, "approve")

    def test_customers_get_403(self):
        self.client.force_login(self.customer)
        for url in (
            reverse("orders_panel:list"),
            reverse("orders_panel:detail", args=[self.order.number]),
            reverse("inventory:low_stock"),
            reverse("catalog:panel_home"),
        ):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(
            self.client.post(
                reverse("orders_panel:status", args=[self.order.number]), {"estado": "en_preparacion"}
            ).status_code,
            403,
        )

    def test_admin_sees_order_detail_and_changes_status(self):
        self.client.force_login(self.admin)
        detail = self.client.get(reverse("orders_panel:detail", args=[self.order.number]))
        self.assertContains(detail, "gloss")
        self.assertContains(detail, "ana@example.com")
        self.client.post(
            reverse("orders_panel:status", args=[self.order.number]),
            {"estado": "en_preparacion", "nota": "empacando"},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PREPARING)
        self.assertEqual(self.order.status_history.first().note, "empacando")
        self.assertEqual(self.order.status_history.first().display_message, "empacando")

    def test_admin_only_sees_admin_account_navigation(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse("catalog:panel_home"))
        self.assertContains(page, "panel administrativo")
        self.assertNotContains(page, "mi perfil")
        self.assertNotContains(page, "mis pedidos")

    def test_admin_cannot_access_customer_profile_or_orders(self):
        self.client.force_login(self.admin)
        urls = (
            reverse("accounts:profile"),
            reverse("accounts:address_create"),
            reverse("orders:list"),
            reverse("orders:detail", args=[self.order.number]),
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_admin_cannot_force_invalid_state(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("orders_panel:status", args=[self.order.number]), {"estado": "entregado"}
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)

    def test_list_filters_and_search(self):
        self.client.force_login(self.admin)
        url = reverse("orders_panel:list")
        paid_orders = self.client.get(url, {"estado": "pagado"})
        self.assertContains(paid_orders, self.order.number)
        self.assertContains(
            paid_orders,
            f'aria-label="Gestionar estado del pedido {self.order.number}"',
        )
        self.assertNotContains(self.client.get(url, {"estado": "cancelado"}), self.order.number)
        self.assertContains(self.client.get(url, {"q": "ana@"}), self.order.number)
        self.assertNotContains(self.client.get(url, {"q": "zzz"}), self.order.number)

    def test_low_stock_page_lists_variant(self):
        # stock 3 - 1 vendido = 2 <= umbral 3
        self.client.force_login(self.admin)
        page = self.client.get(reverse("inventory:low_stock"))
        self.assertContains(page, "gloss")
        home = self.client.get(reverse("catalog:panel_home"))
        self.assertEqual(home.context["order_stats"]["low_stock"], 1)
