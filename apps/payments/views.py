from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from apps.orders.models import Order
from apps.orders.services import expire_pending_orders

from .gateways import PayPalSandbox, PayPalSandboxError
from .models import Payment
from .services import PaymentError, initiate_payment, process_payment


@login_required
@require_POST
def start_payment(request, number):
    """Inicia (o reintenta) el pago de un pedido del usuario con la pasarela configurada."""
    expire_pending_orders()
    order = get_object_or_404(Order, number=number, user=request.user)
    try:
        payment = initiate_payment(order)
    except (PaymentError, PayPalSandboxError) as exc:
        messages.error(request, str(exc))
        return redirect("orders:detail", number=order.number)
    try:
        return redirect(PayPalSandbox().approval_url(payment.reference))
    except PayPalSandboxError as exc:
        messages.error(request, str(exc))
        return redirect("orders:detail", number=order.number)


@login_required
def paypal_return(request):
    """PayPal devuelve ?token=ORDER_ID; el token se cruza con dueño y pedido local."""
    reference = request.GET.get("token", "")[:100]
    payment = get_object_or_404(Payment.objects.select_related("order"),
                                reference=reference, provider=PayPalSandbox.name,
                                order__user=request.user)
    try:
        outcome = process_payment(reference, request.user, "approve")
        (messages.success if outcome.ok else messages.error)(request, outcome.message)
    except (PaymentError, PayPalSandboxError) as exc:
        messages.error(request, str(exc))
    return redirect("orders:detail", number=payment.order.number)


@login_required
def paypal_cancel(request):
    reference = request.GET.get("token", "")[:100]
    payment = get_object_or_404(Payment.objects.select_related("order"),
                                reference=reference, provider=PayPalSandbox.name,
                                order__user=request.user)
    messages.info(request, "Regresaste de PayPal sin confirmar el pago. Puedes continuar mientras el pedido siga vigente.")
    return redirect("orders:detail", number=payment.order.number)
