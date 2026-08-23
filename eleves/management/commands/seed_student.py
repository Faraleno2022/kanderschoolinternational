from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from eleves.models import Ecole, Classe, Eleve, Responsable, GrilleTarifaire
from paiements.models import EcheancierPaiement


class Command(BaseCommand):
    help = "Crée un élève avec un responsable et initialise l'échéancier à partir de la grille tarifaire."

    def add_arguments(self, parser):
        parser.add_argument("matricule", help="Matricule de l'élève, ex: 0005")
        parser.add_argument("prenom", help="Prénom de l'élève")
        parser.add_argument("nom", help="Nom de l'élève")
        parser.add_argument("sexe", choices=["M", "F"], help="Sexe: M ou F")
        parser.add_argument("annee", help="Année scolaire ex: 2025-2026")

        parser.add_argument("--ecole", required=True, help="Nom exact de l'école")
        parser.add_argument("--niveau", required=True, help="Code niveau (ex: COLLEGE_7, PRIMAIRE_6)")
        parser.add_argument("--classe", default=None, help="Nom de la classe (ex: 7ème). Par défaut le libellé du niveau.")

        parser.add_argument("--date-naissance", default=None, help="YYYY-MM-DD (défaut: 2015-01-01)")
        parser.add_argument("--lieu-naissance", default="Conakry")
        parser.add_argument("--date-inscription", default=None, help="YYYY-MM-DD (défaut: 1er oct de l'année début)")

        parser.add_argument("--resp-prenom", default="Parent")
        parser.add_argument("--resp-nom", default="Test")
        parser.add_argument("--resp-telephone", default="+224622999999")
        parser.add_argument("--resp-relation", default="PERE", help="PERE/MERE/TUTEUR/TUTRICE/AUTRE ...")
        parser.add_argument("--resp-adresse", default="Adresse parent")

    @transaction.atomic
    def handle(self, *args, **opts):
        matricule = opts["matricule"]
        prenom = opts["prenom"]
        nom = opts["nom"]
        sexe = opts["sexe"]
        annee = opts["annee"]
        ecole_nom = opts["ecole"]
        niveau = opts["niveau"]
        nom_classe = opts["classe"]

        # Dates par défaut
        try:
            if opts["date_naissance"]:
                y, m, d = [int(x) for x in opts["date_naissance"].split("-")]
                date_naissance = date(y, m, d)
            else:
                date_naissance = date(2015, 1, 1)
        except Exception:
            raise CommandError("Format --date-naissance invalide. Utiliser YYYY-MM-DD")

        try:
            if opts["date_inscription"]:
                y, m, d = [int(x) for x in opts["date_inscription"].split("-")]
                date_inscription = date(y, m, d)
            else:
                # par défaut: 1er octobre de l'année de début
                annee_debut = int(annee.split("-")[0])
                date_inscription = date(annee_debut, 10, 1)
        except Exception:
            raise CommandError("Format --date-inscription invalide. Utiliser YYYY-MM-DD")

        # 1) École
        try:
            ecole = Ecole.objects.get(nom=ecole_nom)
        except Ecole.DoesNotExist:
            raise CommandError(f"École introuvable: {ecole_nom}")

        # 2) Classe (créée si absente)
        if not nom_classe:
            # fallback: utiliser le libellé du niveau basique
            # On peut avoir besoin de mapper codes->labels; pour simplicité on garde le code comme nom
            nom_classe = {
                'GARDERIE': 'Garderie',
                'MATERNELLE': 'Maternelle',
                'PRIMAIRE_1': '1ère',
                'PRIMAIRE_2': '2ème',
                'PRIMAIRE_3': '3ème',
                'PRIMAIRE_4': '4ème',
                'PRIMAIRE_5': '5ème',
                'PRIMAIRE_6': '6ème',
                'COLLEGE_7': '7ème',
                'COLLEGE_8': '8ème',
                'COLLEGE_9': '9ème',
                'COLLEGE_10': '10ème',
                'LYCEE_11': '11ème',
                'LYCEE_12': '12ème',
                'TERMINALE': 'Terminale',
            }.get(niveau, niveau)

        classe, _ = Classe.objects.get_or_create(
            ecole=ecole,
            nom=nom_classe,
            annee_scolaire=annee,
            defaults={"niveau": niveau, "capacite_max": 40},
        )

        # 3) Responsable (get_or_create par téléphone)
        resp, _ = Responsable.objects.get_or_create(
            telephone=opts["resp_telephone"],
            defaults={
                "prenom": opts["resp_prenom"],
                "nom": opts["resp_nom"],
                "relation": opts["resp_relation"],
                "email": None,
                "adresse": opts["resp_adresse"],
                "profession": None,
            },
        )

        # 4) Élève
        eleve, created = Eleve.objects.get_or_create(
            matricule=matricule,
            defaults={
                "prenom": prenom,
                "nom": nom,
                "sexe": sexe,
                "date_naissance": date_naissance,
                "lieu_naissance": opts["lieu_naissance"],
                "photo": None,
                "classe": classe,
                "date_inscription": date_inscription,
                "responsable_principal": resp,
            },
        )

        if not created:
            self.stdout.write(self.style.WARNING(f"Élève déjà existant: {eleve.matricule} - {eleve.nom_complet}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Élève créé: {eleve.matricule} - {eleve.nom_complet}"))

        # 5) Échéancier depuis la grille
        try:
            grille = GrilleTarifaire.objects.get(ecole=ecole, niveau=classe.niveau, annee_scolaire=annee)
        except GrilleTarifaire.DoesNotExist:
            raise CommandError(f"Grille tarifaire introuvable pour {ecole.nom} - {classe.get_niveau_display()} ({annee}).")

        # Dates d'échéance simples
        annee_debut = int(annee.split("-")[0])
        echeancier_values = {
            "eleve": eleve,
            "annee_scolaire": annee,
            "frais_inscription_du": grille.frais_inscription,
            "tranche_1_due": grille.tranche_1,
            "tranche_2_due": grille.tranche_2,
            "tranche_3_due": grille.tranche_3,
            "date_echeance_inscription": date(annee_debut, 10, 1),
            "date_echeance_tranche_1": date(annee_debut + 1, 1, 10),
            "date_echeance_tranche_2": date(annee_debut + 1, 3, 5),
            "date_echeance_tranche_3": date(annee_debut + 1, 4, 6),
        }

        echeancier, e_created = EcheancierPaiement.objects.get_or_create(
            eleve=eleve,
            annee_scolaire=annee,
            ecole_reference=classe.ecole,
            defaults=echeancier_values,
        )
        if e_created:
            self.stdout.write(self.style.SUCCESS(
                f"Échéancier créé: total {echeancier.total_du:,.0f} GNF | {eleve.nom_complet}"
            ))
        else:
            # Mettre à jour les dues si vide
            updated = False
            for f in [
                "frais_inscription_du", "tranche_1_due", "tranche_2_due", "tranche_3_due",
                "date_echeance_inscription", "date_echeance_tranche_1", "date_echeance_tranche_2", "date_echeance_tranche_3",
            ]:
                old = getattr(echeancier, f)
                new = echeancier_values[f]
                if (isinstance(old, (int, Decimal)) and old == 0) or old is None:
                    setattr(echeancier, f, new)
                    updated = True
            if updated:
                echeancier.save()
                self.stdout.write(self.style.WARNING("Échéancier existant mis à jour avec la grille."))
            else:
                self.stdout.write(self.style.WARNING("Échéancier déjà existant et complet."))

        self.stdout.write(self.style.SUCCESS("Terminé."))
