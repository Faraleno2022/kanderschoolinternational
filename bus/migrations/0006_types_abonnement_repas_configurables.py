from datetime import time

from django.db import migrations, models


def creer_parametres_par_defaut(apps, schema_editor):
    TypePeriodicite = apps.get_model('bus', 'TypePeriodiciteAbonnement')
    TypeRepas = apps.get_model('bus', 'TypeRepasCantine')

    periodicites = (
        ('BUS', 'MENSUEL', 'Mensuel', 1, 0, 10),
        ('BUS', 'ANNUEL', 'Annuel', 12, 0, 20),
        ('BUS', 'T1', '1ère Tranche', 0, 0, 30),
        ('BUS', 'T2', '2ème Tranche', 0, 0, 40),
        ('BUS', 'T3', '3ème Tranche', 0, 0, 50),
        ('CANTINE', 'JOURNALIER', 'Journalier', 0, 1, 10),
        ('CANTINE', 'HEBDOMADAIRE', 'Hebdomadaire', 0, 7, 20),
        ('CANTINE', 'MENSUEL', 'Mensuel', 1, 0, 30),
        ('CANTINE', 'TRIMESTRIEL', 'Trimestriel', 3, 0, 40),
        ('CANTINE', 'ANNUEL', 'Annuel', 12, 0, 50),
    )
    for service, code, libelle, mois, jours, ordre in periodicites:
        TypePeriodicite.objects.update_or_create(
            service=service,
            code=code,
            defaults={
                'libelle': libelle,
                'duree_mois': mois,
                'duree_jours': jours,
                'actif': True,
                'ordre': ordre,
            },
        )

    repas = (
        ('DEJEUNER', 'Déjeuner uniquement', None, 10),
        ('GOUTER', 'Goûter uniquement', None, 20),
        ('COMPLET', 'Déjeuner + Goûter', None, 30),
        ('REPAS_14H', 'Repas de 14 h', time(14, 0), 40),
    )
    for code, libelle, heure_service, ordre in repas:
        TypeRepas.objects.update_or_create(
            code=code,
            defaults={
                'libelle': libelle,
                'heure_service': heure_service,
                'actif': True,
                'ordre': ordre,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('bus', '0005_abonnement_references_paiement'),
    ]

    operations = [
        migrations.CreateModel(
            name='TypePeriodiciteAbonnement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('service', models.CharField(choices=[('BUS', 'Bus scolaire'), ('CANTINE', 'Cantine scolaire')], db_index=True, max_length=10)),
                ('code', models.CharField(help_text='Code technique stable, par exemple MENSUEL ou ANNUEL.', max_length=30)),
                ('libelle', models.CharField(max_length=100)),
                ('duree_mois', models.PositiveSmallIntegerField(default=0, help_text='Nombre de mois à ajouter automatiquement à la date de début.')),
                ('duree_jours', models.PositiveSmallIntegerField(default=0, help_text='Nombre de jours à ajouter après les mois (0 si non applicable).')),
                ('actif', models.BooleanField(db_index=True, default=True)),
                ('ordre', models.PositiveSmallIntegerField(default=10)),
            ],
            options={
                'verbose_name': "Type d'abonnement",
                'verbose_name_plural': "Types d'abonnement",
                'ordering': ('service', 'ordre', 'libelle'),
            },
        ),
        migrations.CreateModel(
            name='TypeRepasCantine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(help_text='Code technique stable, par exemple DEJEUNER ou REPAS_14H.', max_length=30, unique=True)),
                ('libelle', models.CharField(max_length=100)),
                ('heure_service', models.TimeField(blank=True, null=True)),
                ('actif', models.BooleanField(db_index=True, default=True)),
                ('ordre', models.PositiveSmallIntegerField(default=10)),
            ],
            options={
                'verbose_name': 'Type de repas cantine',
                'verbose_name_plural': 'Types de repas cantine',
                'ordering': ('ordre', 'libelle'),
            },
        ),
        migrations.AddConstraint(
            model_name='typeperiodiciteabonnement',
            constraint=models.UniqueConstraint(fields=('service', 'code'), name='bus_type_periodicite_service_code_unique'),
        ),
        migrations.RunPython(creer_parametres_par_defaut, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='abonnementbus',
            name='periodicite',
            field=models.CharField(default='MENSUEL', max_length=30, verbose_name="Type d'abonnement"),
        ),
        migrations.AlterField(
            model_name='abonnementcantine',
            name='periodicite',
            field=models.CharField(default='MENSUEL', max_length=30, verbose_name="Type d'abonnement"),
        ),
        migrations.AlterField(
            model_name='abonnementcantine',
            name='type_repas',
            field=models.CharField(default='DEJEUNER', max_length=30, verbose_name='Type de repas'),
        ),
    ]
