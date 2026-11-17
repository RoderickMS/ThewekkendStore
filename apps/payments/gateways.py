"""Integración exclusiva con PayPal Sandbox mediante OAuth 2.0 y Orders v2.
El servidor obtiene el importe desde el pedido, nunca desde el navegador.
"""
from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class GatewayResult:
    status: str  # COMPLETED | DECLINED | CANCELLED
    detail: str = ""
    capture_id: str = ""

    @property
    def completed(self) -> bool:
        return self.status == "COMPLETED"


class PayPalSandboxError(Exception):
    """Fallo de la API de PayPal; no equivale a pago rechazado."""


class PayPalSandbox:
    """Adaptación de OAuth + Orders v2 del ejemplo del profesor.

    Redirige al comprador al sitio oficial de PayPal Sandbox. La captura
    se solicita únicamente después del retorno de aprobación del comprador.
    """
    name = "paypal_sandbox"

    @staticmethod
    def _base():
        from django.conf import settings
        if getattr(settings, "PAYPAL_ENV", "sandbox") != "sandbox":
            raise PayPalSandboxError("Esta integración está limitada a Sandbox.")
        return "https://api-m.sandbox.paypal.com"

    def _token(self):
        import requests
        client_id = getattr(settings, "PAYPAL_CLIENT_ID", "")
        secret = getattr(settings, "PAYPAL_CLIENT_SECRET", "")
        if not client_id or not secret:
            raise PayPalSandboxError("Configura PAYPAL_CLIENT_ID y PAYPAL_CLIENT_SECRET en .env")
        try:
            response = requests.post(
                self._base() + "/v1/oauth2/token", auth=(client_id, secret),
                data={"grant_type": "client_credentials"}, timeout=15,
            )
            response.raise_for_status()
            return response.json()["access_token"]
        except (requests.RequestException, KeyError, ValueError) as exc:
            raise PayPalSandboxError("No se pudo autenticar con PayPal Sandbox.") from exc

    def _request(self, method, endpoint, *, payload=None, request_id=None):
        import requests
        headers = {"Authorization": "Bearer " + self._token(),
                   "Content-Type": "application/json"}
        if request_id:
            headers["PayPal-Request-Id"] = str(request_id)
        try:
            response = requests.request(method, self._base() + endpoint, headers=headers,
                                        json=payload, timeout=20)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise PayPalSandboxError("No se pudo completar la operación con PayPal Sandbox; verifica su estado antes de reintentar.") from exc

    def create_order(self, order):
        import uuid
        from django.urls import reverse
        base = getattr(settings, "PAYPAL_RETURN_BASE_URL", "").rstrip("/")
        if not base.startswith(("http://localhost:", "http://127.0.0.1:", "https://")):
            raise PayPalSandboxError("Configura PAYPAL_RETURN_BASE_URL con el origen público de tu aplicación.")
        amount = f"{order.total:.2f}"
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [{"reference_id": str(order.number),
                                "custom_id": str(order.number),
                                "amount": {"currency_code": "USD", "value": amount}}],
            "payment_source": {"paypal": {"experience_context": {
                "return_url": base + reverse("payments:paypal_return"),
                "cancel_url": base + reverse("payments:paypal_cancel"),
                "user_action": "PAY_NOW", "shipping_preference": "NO_SHIPPING",
            }}},
        }
        data = self._request("POST", "/v2/checkout/orders", payload=payload,
                             request_id=uuid.uuid4())
        if not data.get("id"):
            raise PayPalSandboxError("PayPal no devolvió un identificador de orden.")
        return data["id"]

    def approval_url(self, reference):
        import requests
        data = self._request("GET", f"/v2/checkout/orders/{reference}")
        for link in data.get("links", []):
            if link.get("rel") in ("payer-action", "approve"):
                url = link.get("href", "")
                if url.startswith("https://www.sandbox.paypal.com/"):
                    return url
        raise PayPalSandboxError("PayPal no proporcionó la URL segura para aprobar el pago.")

    def capture(self, reference, amount, action):
        import uuid
        from decimal import Decimal, InvalidOperation
        if action != "approve":
            return GatewayResult("CANCELLED", "El comprador canceló el pago.")
        # Si hubo error de red en una captura previa, consultar estado antes de reintentar.
        existing = self._request("GET", f"/v2/checkout/orders/{reference}")
        if existing.get("status") == "COMPLETED":
            data = existing
        else:
            data = self._request("POST", f"/v2/checkout/orders/{reference}/capture", payload={},
                                 request_id=uuid.uuid5(uuid.NAMESPACE_URL, f"weekend-capture-{reference}"))
        captures = [c for u in data.get("purchase_units", []) for c in u.get("payments", {}).get("captures", [])]
        if data.get("status") != "COMPLETED" or len(captures) != 1:
            raise PayPalSandboxError("La operación aún no figura como completada; revisa PayPal antes de reintentar.")
        cap = captures[0]
        try:
            valid = (cap.get("status") == "COMPLETED" and
                     cap.get("amount", {}).get("currency_code") == "USD" and
                     Decimal(cap.get("amount", {}).get("value", "")) == Decimal(amount))
        except (InvalidOperation, TypeError):
            valid = False
        if not valid:
            raise PayPalSandboxError("La captura no coincide con el importe o moneda del pedido: requiere conciliación manual.")
        return GatewayResult("COMPLETED", "Pago confirmado por PayPal Sandbox.", cap.get("id", ""))

def get_gateway(provider=None):
    """No se admite ningún proveedor diferente de PayPal Sandbox."""
    if provider is not None and provider != PayPalSandbox.name:
        raise PayPalSandboxError("El proveedor de este pago ya no está disponible.")
    return PayPalSandbox()
