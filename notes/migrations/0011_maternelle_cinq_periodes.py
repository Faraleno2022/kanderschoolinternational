from django.db import migrations, models


PERIODES_MATERNELLE = [
    ('PERIODE_1', 'Première période'),
    ('PERIODE_2', 'Deuxième période'),
    ('PERIODE_3', 'Troisième période'),
    ('PERIODE_4', 'Quatrième période'),
    ('PERIODE_5', 'Cinquième période'),
    ('TRIMESTRE_1', 'Trimestre 1'),
    ('TRIMESTRE_2', 'Trimestre 2'),
    ('TRIMESTRE_3', 'Trimestre 3'),
]


class Migration(migrations.Migration):

    dependencies = [
        ('notes', '0010_alter_activiteculturelle_image'),
    ]

    operations = [
        migrations.AlterField(
            model_name='appreciationmaternelle',
            name='trimestre',
            field=models.CharField(
                choices=PERIODES_MATERNELLE,
                max_length=20,
                verbose_name='Période',
            ),
        ),
        migrations.AlterField(
            model_name='bulletinmaternelle',
            name='trimestre',
            field=models.CharField(
                choices=PERIODES_MATERNELLE,
                max_length=20,
                verbose_name='Période',
            ),
        ),
        migrations.AlterField(
            model_name='evaluationmaternelle',
            name='trimestre',
            field=models.CharField(
                choices=PERIODES_MATERNELLE,
                max_length=20,
                verbose_name='Période',
            ),
        ),
    ]
