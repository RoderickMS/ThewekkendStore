from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0004_category_image"),
    ]

    operations = [
        migrations.AlterField(
            model_name="product",
            name="low_stock_threshold",
            field=models.PositiveIntegerField(
                default=5,
                verbose_name="umbral de bajo stock",
            ),
        ),
    ]