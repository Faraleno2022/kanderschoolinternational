from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('salaires', '0007_avances_salaire'),
    ]

    operations = [
        migrations.AddField(
            model_name='enseignant',
            name='fonction',
            field=models.CharField(
                blank=True,
                help_text='Ex. Directeur, secrétaire, surveillant général ou comptable',
                max_length=150,
                verbose_name='Fonction / poste administratif',
            ),
        ),
    ]
