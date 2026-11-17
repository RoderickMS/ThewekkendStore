"""Pruebas aisladas de configuración y rutas sin contactar a PayPal."""
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import NoReverseMatch, reverse
from django.conf import settings

from .gateways import PayPalSandbox, PayPalSandboxError, get_gateway


class SandboxOnlyTests(SimpleTestCase):
    def test_sandbox_is_only_gateway(self):
        self.assertEqual(settings.PAYMENT_GATEWAY, "paypal_sandbox")
        self.assertIsInstance(get_gateway(), PayPalSandbox)
        with self.assertRaises(PayPalSandboxError):
            get_gateway("paypal_simulator")

    def test_local_manual_approval_routes_removed(self):
        for name in ("paypal", "paypal_resolve"):
            with self.assertRaises(NoReverseMatch):
                reverse("payments:" + name, args=["order-123"])

    def test_sandbox_callback_routes_exist(self):
        self.assertTrue(reverse("payments:paypal_return"))
        self.assertTrue(reverse("payments:paypal_cancel"))

    def test_sandbox_only_endpoint(self):
        with patch.object(PayPalSandbox, "_request", return_value={"id": "ORDER-123"}):
            self.assertIsInstance(get_gateway(), PayPalSandbox)
