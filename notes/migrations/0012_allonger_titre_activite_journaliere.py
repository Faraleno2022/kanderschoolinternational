from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notes', '0011_maternelle_cinq_periodes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='activitejournaliere',
            name='titre',
            field=models.CharField(
                max_length=500,
                verbose_name="Titre de l'activité",
            ),
        ),
    ]
