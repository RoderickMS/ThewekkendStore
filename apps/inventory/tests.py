import threading
from datetime import timedelta

from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.carts.models import CartItem
from apps.inventory.models import StockMovement, StockReservation
from apps.inventory.services import (
    InsufficientStockError,
    get_available_stock,
    register_movement,
    release_user_reservations,
    reserve_cart,
)
from apps.testing import fill_cart, make_user, make_variant


class ReservationTests(TestCase):
    def setUp(self):
        self.variant = make_variant(stock=3)
        self.ana = make_user("ana")
        self.beto = make_user("beto")

    def test_reserve_reduces_availability_for_others_only(self):
        cart = fill_cart(self.ana, (self.variant, 2))
        reserve_cart(self.ana, cart)
        self.assertEqual(get_available_stock(self.variant, exclude_user=self.ana), 3)
        self.assertEqual(get_available_stock(self.variant, exclude_user=self.beto), 1)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 3, "reservar no descuenta stock físico")

    def test_second_customer_cannot_reserve_what_is_held(self):
        reserve_cart(self.ana, fill_cart(self.ana, (self.variant, 2)))
        with self.assertRaises(InsufficientStockError):
            reserve_cart(self.beto, fill_cart(self.beto, (self.variant, 2)))
        self.assertFalse(StockReservation.objects.filter(user=self.beto).exists())

    def test_reload_does_not_extend_expiry(self):
        cart = fill_cart(self.ana, (self.variant, 1))
        first = reserve_cart(self.ana, cart)[0]
        StockReservation.objects.filter(pk=first.pk).update(
            expires_at=timezone.now() + timedelta(minutes=2)
        )
        again = reserve_cart(self.ana, cart)
        self.assertEqual([r.pk for r in again], [first.pk])
        again[0].refresh_from_db()
        self.assertLess(again[0].expires_at, timezone.now() + timedelta(minutes=3))
        self.assertEqual(StockReservation.objects.filter(user=self.ana, is_active=True).count(), 1)

    def test_changed_cart_replaces_reservation(self):
        cart = fill_cart(self.ana, (self.variant, 1))
        reserve_cart(self.ana, cart)
        fill_cart(self.ana, (self.variant, 3))
        res = reserve_cart(self.ana, cart)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].quantity, 3)
        self.assertEqual(StockReservation.objects.filter(user=self.ana, is_active=True).count(), 1)

    def test_expired_reservation_stops_blocking(self):
        reserve_cart(self.ana, fill_cart(self.ana, (self.variant, 3)))
        StockReservation.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(get_available_stock(self.variant, exclude_user=self.beto), 3)
        reserve_cart(self.beto, fill_cart(self.beto, (self.variant, 3)))  # ahora sí puede

    def test_release_frees_stock(self):
        reserve_cart(self.ana, fill_cart(self.ana, (self.variant, 3)))
        release_user_reservations(self.ana)
        self.assertEqual(get_available_stock(self.variant, exclude_user=self.beto), 3)

    def test_multi_item_failure_leaves_no_partial_reservation(self):
        other = make_variant(stock=1)
        cart = fill_cart(self.ana, (self.variant, 1), (other, 5))
        with self.assertRaises(InsufficientStockError):
            reserve_cart(self.ana, cart)
        self.assertFalse(StockReservation.objects.exists())

    def test_inactive_variant_cannot_be_reserved(self):
        cart = fill_cart(self.ana, (self.variant, 1))
        self.variant.is_active = False
        self.variant.save()
        with self.assertRaises(InsufficientStockError):
            reserve_cart(self.ana, cart)

    def test_stock_never_goes_negative(self):
        with self.assertRaises(InsufficientStockError):
            register_movement(
                variant_id=self.variant.pk,
                movement_type=StockMovement.MovementType.VENTA,
                quantity=-4,
                reason="x",
                responsible=self.ana,
            )


class ConcurrentReservationTests(TransactionTestCase):
    """Varios clientes compiten por las mismas unidades desde conexiones
    distintas (hilos): el bloqueo de filas debe dejar pasar solo a los que
    caben en el stock. Requiere PostgreSQL (SQLite no bloquea filas)."""

    def test_only_available_units_can_be_reserved(self):
        if connection.vendor != "postgresql":
            self.skipTest("La concurrencia real se prueba solo en PostgreSQL.")
        variant = make_variant(stock=3)
        users = [make_user(f"c{i}") for i in range(10)]
        carts = [fill_cart(u, (variant, 1)) for u in users]
        barrier = threading.Barrier(len(users))
        results = []

        def worker(user, cart):
            try:
                barrier.wait()
                reserve_cart(user, cart)
                results.append(True)
            except InsufficientStockError:
                results.append(False)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(u, c)) for u, c in zip(users, carts)]
        [t.start() for t in threads]
        [t.join() for t in threads]

        self.assertEqual(sum(results), 3, results)
        reserved = sum(r.quantity for r in StockReservation.objects.filter(is_active=True))
        self.assertEqual(reserved, 3)

    def test_last_unit_goes_to_exactly_one_order(self):
        if connection.vendor != "postgresql":
            self.skipTest("La concurrencia real se prueba solo en PostgreSQL.")
        from apps.orders.models import Order
        from apps.orders.services import OrderError, create_order_from_cart
        from apps.testing import make_address

        variant = make_variant(stock=1)
        users = [make_user(f"o{i}") for i in range(6)]
        prepared = [(u, fill_cart(u, (variant, 1)), make_address(u)) for u in users]
        barrier = threading.Barrier(len(users))
        outcomes = []

        def worker(user, cart, address):
            try:
                barrier.wait()
                create_order_from_cart(user, cart, address)
                outcomes.append("ok")
            except (InsufficientStockError, OrderError):
                outcomes.append("sin stock")
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=p) for p in prepared]
        [t.start() for t in threads]
        [t.join() for t in threads]

        self.assertEqual(outcomes.count("ok"), 1, outcomes)
        self.assertEqual(Order.objects.count(), 1)

    def test_double_payment_confirmation_deducts_stock_once(self):
        if connection.vendor != "postgresql":
            self.skipTest("La concurrencia real se prueba solo en PostgreSQL.")
        from apps.orders.models import Order
        from apps.orders.services import create_order_from_cart
        from apps.payments.services import initiate_payment, process_payment
        from apps.testing import make_address

        variant = make_variant(stock=5)
        user = make_user("doble")
        order = create_order_from_cart(user, fill_cart(user, (variant, 2)), make_address(user))
        reference = initiate_payment(order).reference
        barrier = threading.Barrier(4)

        def worker():
            try:
                barrier.wait()
                process_payment(reference, user, "approve")
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]

        variant.refresh_from_db()
        self.assertEqual(variant.stock_quantity, 3)
        self.assertEqual(StockMovement.objects.filter(movement_type="venta").count(), 1)
        self.assertEqual(Order.objects.get().status, Order.Status.PAID)


class LowStockAlertTests(TestCase):
    def test_email_sent_only_when_crossing_threshold(self):
        from django.core import mail

        make_user("admin1", role="administrador")
        variant = make_variant(stock=4, threshold=2)
        user = make_user("comprador")

        def sell(qty):
            with self.captureOnCommitCallbacks(execute=True):
                register_movement(
                    variant_id=variant.pk,
                    movement_type=StockMovement.MovementType.VENTA,
                    quantity=-qty,
                    reason="venta",
                    responsible=user,
                )

        sell(1)  # 4 -> 3: sigue sobre el umbral
        self.assertEqual(len(mail.outbox), 0)
        sell(1)  # 3 -> 2: cruza el umbral
        self.assertEqual(len(mail.outbox), 1)
        sell(1)  # 2 -> 1: ya estaba bajo, no repite
        self.assertEqual(len(mail.outbox), 1)

    def test_restock_does_not_alert_and_sold_out_says_so(self):
        from django.core import mail

        make_user("admin1", role="administrador")
        variant = make_variant(stock=2, threshold=2)  # ya está en el umbral
        user = make_user("comprador")

        def move(kind, qty):
            with self.captureOnCommitCallbacks(execute=True):
                register_movement(
                    variant_id=variant.pk, movement_type=kind, quantity=qty, reason="x", responsible=user
                )

        move(StockMovement.MovementType.ENTRADA, 5)  # 2 -> 7: sube, sin alerta
        self.assertEqual(len(mail.outbox), 0)
        move(StockMovement.MovementType.VENTA, -7)  # 7 -> 0: cruza el umbral
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("AGOTADO", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["admin1@example.com"])

    def test_rolled_back_sale_sends_no_email(self):
        from django.core import mail
        from django.db import transaction

        make_user("admin1", role="administrador")
        variant = make_variant(stock=3, threshold=2)
        user = make_user("comprador")
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    register_movement(
                        variant_id=variant.pk,
                        movement_type=StockMovement.MovementType.VENTA,
                        quantity=-2,
                        reason="x",
                        responsible=user,
                    )
                    raise RuntimeError("falla posterior: la venta se revierte")
            except RuntimeError:
                pass
        self.assertEqual(len(mail.outbox), 0)
