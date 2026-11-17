from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0003_productvariant_description_override"),
    ]

    operations = [
        migrations.AddField(
            model_name="category",
            name="image",
            field=models.ImageField(
                blank=True,
                upload_to="categories/%Y/%m/",
                verbose_name="imagen de fondo",
            ),
        ),
    ]