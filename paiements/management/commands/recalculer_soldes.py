"""Rejoue le calcul des soldes sur les échéanciers existants.

Le correctif du recalcul empêche de nouvelles divergences mais ne répare pas
celles déjà inscrites en base — notamment les échéanciers faussés lorsqu'une
correction de paiement visait la classe actuelle de l'élève plutôt que
l'école et l'année de l'encaissement.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from paiements.soldes import echeanciers_a_recalculer, recalculer_echeancier


class Command(BaseCommand):
    help = (
        "Réaligne les échéanciers sur les paiements validés. "
        "Utiliser --simulation d'abord pour mesurer l'écart sans rien écrire."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--simulation', action='store_true',
            help="Affiche les corrections sans les enregistrer.",
        )
        parser.add_argument(
            '--annee', dest='annee_scolaire', default=None,
            help="Limite le rattrapage à une année scolaire (ex. 2025-2026).",
        )
        parser.add_argument(
            '--ecole', dest='ecole_id', type=int, default=None,
            help="Limite le rattrapage à une école (identifiant).",
        )
        parser.add_argument(
            '--detail', dest='detail_max', type=int, default=20,
            help="Nombre d'échéanciers détaillés dans le rapport (0 pour aucun).",
        )

    def handle(self, *args, **options):
        simulation = options['simulation']
        detail_max = options['detail_max']
        queryset = echeanciers_a_recalculer(
            options['annee_scolaire'], options['ecole_id'],
        )

        inspectes = 0
        corriges = []
        # Une transaction unique : un rattrapage partiellement appliqué
        # laisserait la base dans un état plus difficile à diagnostiquer
        # que celui d'où l'on part.
        with transaction.atomic():
            for echeancier in queryset.iterator(chunk_size=500):
                inspectes += 1
                corrections = recalculer_echeancier(
                    echeancier, enregistrer=not simulation,
                )
                if corrections:
                    corriges.append((echeancier, corrections))

        self._rapporter(inspectes, corriges, detail_max, simulation)

    def _rapporter(self, inspectes, corriges, detail_max, simulation):
        for echeancier, corrections in corriges[:detail_max]:
            eleve = echeancier.eleve
            ecole = getattr(echeancier.ecole_reference, 'nom', '—')
            self.stdout.write(
                f"{eleve.matricule} — {eleve.nom_complet} "
                f"({echeancier.annee_scolaire}, {ecole})"
            )
            for champ, (avant, apres) in corrections.items():
                self.stdout.write(f"    {champ} : {avant} → {apres}")

        restants = len(corriges) - detail_max
        if restants > 0:
            self.stdout.write(f"… et {restants} autre(s) échéancier(s) corrigé(s).")

        resume = (
            f"{inspectes} échéancier(s) inspecté(s), "
            f"{len(corriges)} à corriger."
        )
        if simulation:
            self.stdout.write(self.style.WARNING(
                f"Simulation : {resume} Aucune écriture effectuée."
            ))
        elif corriges:
            self.stdout.write(self.style.SUCCESS(f"{resume} Corrections enregistrées."))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"{inspectes} échéancier(s) inspecté(s), tous déjà justes."
            ))
