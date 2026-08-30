from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('eleves', '0019_elevecorbeille_eleve_est_dans_corbeille_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='eleve',
            name='date_evaluation_accueil',
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="Date d'évaluation du test d'accueil",
            ),
        ),
        migrations.AddField(
            model_name='eleve',
            name='test_accueil_evalue',
            field=models.BooleanField(
                db_index=True,
                default=False,
                verbose_name="Test d'accueil évalué",
            ),
        ),
    ]
