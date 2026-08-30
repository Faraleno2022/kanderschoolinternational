import uuid
from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('salaires', '0006_etatsalaire_source_heures'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='etatsalaire',
            name='montant_avances',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0'),
                help_text='Total des avances approuvées à déduire pour cette période.',
                max_digits=12,
                validators=[django.core.validators.MinValueValidator(Decimal('0'))],
                verbose_name='Avances sur salaire',
            ),
        ),
        migrations.CreateModel(
            name='AvanceSalaire',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sync_uuid', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ('sync_created_at', models.DateTimeField(auto_now_add=True)),
                ('sync_updated_at', models.DateTimeField(auto_now=True)),
                ('sync_deleted_at', models.DateTimeField(blank=True, null=True)),
                ('sync_version', models.PositiveIntegerField(default=1)),
                ('is_synced', models.BooleanField(db_index=True, default=False)),
                ('montant', models.DecimalField(decimal_places=2, max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('1'))], verbose_name='Montant de l’avance')),
                ('date_avance', models.DateField(verbose_name='Date de versement')),
                ('mode_paiement', models.CharField(choices=[('ESPECES', 'Espèces'), ('ORANGE_MONEY', 'Orange Money'), ('MOBILE_MONEY', 'Mobile Money'), ('VIREMENT', 'Virement bancaire'), ('CHEQUE', 'Chèque'), ('AUTRE', 'Autre')], default='ESPECES', max_length=20, verbose_name='Mode de versement')),
                ('reference_paiement', models.CharField(blank=True, max_length=100, verbose_name='Référence / n° reçu')),
                ('motif', models.CharField(max_length=255, verbose_name='Motif de l’avance')),
                ('statut', models.CharField(choices=[('EN_ATTENTE', 'En attente'), ('APPROUVEE', 'Approuvée'), ('DEDUITE', 'Déduite du salaire'), ('ANNULEE', 'Annulée')], db_index=True, default='EN_ATTENTE', max_length=20)),
                ('observations', models.TextField(blank=True)),
                ('motif_annulation', models.CharField(blank=True, max_length=255)),
                ('date_creation', models.DateTimeField(auto_now_add=True)),
                ('date_modification', models.DateTimeField(auto_now=True)),
                ('date_approbation', models.DateTimeField(blank=True, null=True)),
                ('date_deduction', models.DateTimeField(blank=True, null=True)),
                ('date_annulation', models.DateTimeField(blank=True, null=True)),
                ('annulee_par', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='avances_salaire_annulees', to=settings.AUTH_USER_MODEL)),
                ('approuvee_par', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='avances_salaire_approuvees', to=settings.AUTH_USER_MODEL)),
                ('cree_par', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='avances_salaire_creees', to=settings.AUTH_USER_MODEL)),
                ('enseignant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='avances_salaire', to='salaires.enseignant', verbose_name='Employé / enseignant')),
                ('periode', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='avances_salaire', to='salaires.periodesalaire', verbose_name='Période de déduction')),
            ],
            options={
                'verbose_name': 'Avance sur salaire',
                'verbose_name_plural': 'Avances sur salaire',
                'ordering': ('-date_avance', '-id'),
                'indexes': [
                    models.Index(fields=['enseignant', 'periode'], name='sal_av_ens_per_idx'),
                    models.Index(fields=['statut', 'date_avance'], name='sal_av_stat_date_idx'),
                ],
            },
        ),
    ]
