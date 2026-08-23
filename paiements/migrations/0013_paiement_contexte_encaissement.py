from django.db import migrations, models
import django.db.models.deletion


def renseigner_contexte_historique(apps, schema_editor):
    Paiement = apps.get_model('paiements', 'Paiement')
    Profil = apps.get_model('utilisateurs', 'Profil')
    ecole_par_utilisateur = {
        user_id: ecole_id
        for user_id, ecole_id in Profil.objects.exclude(ecole_id=None).values_list(
            'user_id', 'ecole_id',
        )
    }
    batch = []
    queryset = Paiement.objects.select_related('eleve__classe').all().iterator(chunk_size=500)
    for paiement in queryset:
        classe = getattr(paiement.eleve, 'classe', None)
        if classe is None:
            continue
        ecole_operation_id = (
            ecole_par_utilisateur.get(paiement.cree_par_id)
            or ecole_par_utilisateur.get(paiement.valide_par_id)
            or classe.ecole_id
        )
        paiement.ecole_encaissement_id = ecole_operation_id
        if ecole_operation_id == classe.ecole_id:
            paiement.classe_encaissement_id = classe.pk
            paiement.annee_scolaire = classe.annee_scolaire or ''
        else:
            # L'école du caissier permet de récupérer l'établissement source
            # après un ancien transfert. La classe exacte, elle, ne peut pas
            # être devinée sans risque : on la laisse volontairement vide.
            paiement.classe_encaissement_id = None
            paiement.annee_scolaire = (
                f'{paiement.date_paiement.year}-{paiement.date_paiement.year + 1}'
                if paiement.date_paiement.month >= 9
                else f'{paiement.date_paiement.year - 1}-{paiement.date_paiement.year}'
            )
        batch.append(paiement)
        if len(batch) >= 500:
            Paiement.objects.bulk_update(
                batch,
                ['classe_encaissement', 'ecole_encaissement', 'annee_scolaire'],
            )
            batch = []
    if batch:
        Paiement.objects.bulk_update(
            batch,
            ['classe_encaissement', 'ecole_encaissement', 'annee_scolaire'],
        )

    Echeancier = apps.get_model('paiements', 'EcheancierPaiement')
    Grille = apps.get_model('eleves', 'GrilleTarifaire')
    tarifs = {
        (ecole_id, niveau, annee): (inscription or 0, reinscription or 0)
        for ecole_id, niveau, annee, inscription, reinscription in Grille.objects.values_list(
            'ecole_id', 'niveau', 'annee_scolaire',
            'frais_inscription', 'frais_reinscription',
        )
    }
    for echeancier in Echeancier.objects.all().iterator(chunk_size=500):
        classe = getattr(echeancier.eleve, 'classe', None)
        if classe is not None:
            echeancier.classe_reference_id = classe.pk
            echeancier.ecole_reference_id = classe.ecole_id
        types = Paiement.objects.filter(
            eleve_id=echeancier.eleve_id,
            annee_scolaire=echeancier.annee_scolaire,
            statut='VALIDE',
        ).values_list('type_paiement__nom', flat=True)
        reinscription_explicite = any(
            'reinscription' in (
                (nom or '').lower().replace('é', 'e').replace('-', '').replace(' ', '')
            )
            for nom in types
        )
        grille = tarifs.get((
            getattr(classe, 'ecole_id', None),
            getattr(classe, 'niveau', None),
            echeancier.annee_scolaire,
        ))
        reinscription_par_tarif = bool(
            grille
            and echeancier.frais_inscription_du == grille[1]
            and grille[1] != grille[0]
        )
        if reinscription_explicite or reinscription_par_tarif:
            echeancier.nature_frais = 'REINSCRIPTION'
        echeancier.save(update_fields=[
            'nature_frais', 'classe_reference', 'ecole_reference',
        ])


class Migration(migrations.Migration):

    dependencies = [
        ('eleves', '0019_elevecorbeille_eleve_est_dans_corbeille_and_more'),
        ('paiements', '0012_remise_deduite_du_paiement'),
        ('utilisateurs', '0013_licenceserveur'),
    ]

    operations = [
        migrations.AddField(
            model_name='paiement',
            name='annee_scolaire',
            field=models.CharField(blank=True, db_index=True, max_length=9, verbose_name="Année scolaire d'encaissement"),
        ),
        migrations.AddField(
            model_name='paiement',
            name='classe_encaissement',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='paiements_encaissement', to='eleves.classe', verbose_name="Classe d'encaissement"),
        ),
        migrations.AddField(
            model_name='paiement',
            name='ecole_encaissement',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='paiements_encaissement', to='eleves.ecole', verbose_name="École d'encaissement"),
        ),
        migrations.AddField(
            model_name='echeancierpaiement',
            name='nature_frais',
            field=models.CharField(choices=[('INSCRIPTION', 'Inscription'), ('REINSCRIPTION', 'Réinscription')], default='INSCRIPTION', max_length=20, verbose_name="Nature des frais d'admission"),
        ),
        migrations.AlterField(
            model_name='echeancierpaiement',
            name='eleve',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='echeanciers', to='eleves.eleve'),
        ),
        migrations.AddField(
            model_name='echeancierpaiement',
            name='classe_reference',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='echeanciers_paiement', to='eleves.classe', verbose_name="Classe de l'échéancier"),
        ),
        migrations.AddField(
            model_name='echeancierpaiement',
            name='ecole_reference',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='echeanciers_paiement', to='eleves.ecole', verbose_name="École de l'échéancier"),
        ),
        migrations.RunPython(renseigner_contexte_historique, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='echeancierpaiement',
            constraint=models.UniqueConstraint(fields=('eleve', 'annee_scolaire', 'ecole_reference'), name='echeancier_unique_eleve_annee_ecole'),
        ),
        migrations.AddIndex(
            model_name='paiement',
            index=models.Index(fields=['ecole_encaissement', 'annee_scolaire'], name='paiements_p_ecole_e_annee_idx'),
        ),
        migrations.AddIndex(
            model_name='paiement',
            index=models.Index(fields=['classe_encaissement', 'annee_scolaire'], name='paiements_p_classe_e_annee_idx'),
        ),
    ]
