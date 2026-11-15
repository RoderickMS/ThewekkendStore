from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[("cliente", "Cliente"), ("administrador", "Administrador")],
                default="cliente",
                help_text="Diferencia Cliente de Administrador.",
                max_length=20,
            ),
        ),
    ]