from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bus', '0004_add_sync_tracking'),
    ]

    operations = [
        migrations.AddField(
            model_name='abonnementbus',
            name='reference_paiement',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='Numéro du reçu, référence Mobile Money, chèque ou virement.',
                max_length=100,
                verbose_name='Référence externe / n° reçu',
            ),
        ),
        migrations.AddField(
            model_name='abonnementcantine',
            name='reference_paiement',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='Numéro du reçu, référence Mobile Money, chèque ou virement.',
                max_length=100,
                verbose_name='Référence externe / n° reçu',
            ),
        ),
    ]
