from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("payments", "0002_etapa3")]

    operations = [
        migrations.AlterField(
            model_name="payment",
            name="provider",
            field=models.CharField(max_length=50, default="paypal_sandbox", verbose_name="proveedor"),
        ),
    ]
