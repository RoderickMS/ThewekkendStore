from django.core.management.base import BaseCommand

from apps.inventory.services import cleanup_expired_reservations
from apps.orders.services import expire_pending_orders


class Command(BaseCommand):
    help = (
        "Cancela los pedidos pendientes de pago cuya ventana venció y libera "
        "las reservas de stock vencidas. Programar cada pocos minutos "
        "(cron/systemd timer): python manage.py expire_pending_orders"
    )

    def handle(self, *args, **options):
        orders = expire_pending_orders()
        reservations = cleanup_expired_reservations()
        self.stdout.write(
            self.style.SUCCESS(
                f"{orders} pedido(s) expirado(s); {reservations} reserva(s) de checkout liberada(s)."
            )
        )
