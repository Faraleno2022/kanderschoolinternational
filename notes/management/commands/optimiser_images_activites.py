"""Réduit les photos d'activités déjà enregistrées.

L'optimisation à l'upload ne touche que les nouvelles images ; celles déjà
en ligne — jusqu'à 15 Mo pièce — doivent être reprises une fois.
"""

from django.core.management.base import BaseCommand

from notes.image_optimizer import optimiser_image
from notes.models import ActiviteCulturelle


def _mo(octets):
    return f"{octets / 1048576:.2f} Mo"


class Command(BaseCommand):
    help = "Redimensionne et recompresse les images des activités culturelles."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help="Montre ce qui serait fait sans rien écrire.",
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        total_avant = total_apres = 0
        traitees = ignorees = echecs = 0

        for activite in ActiviteCulturelle.objects.exclude(image=''):
            try:
                taille_avant = activite.image.size
            except Exception:
                self.stderr.write(f"  ! fichier introuvable : {activite.titre}")
                echecs += 1
                continue

            contenu, nom = optimiser_image(activite.image)
            if contenu is None:
                self.stdout.write(f"  = déjà légère ({_mo(taille_avant)}) : {activite.titre}")
                ignorees += 1
                continue

            taille_apres = len(contenu.read())
            contenu.seek(0)
            total_avant += taille_avant
            total_apres += taille_apres
            traitees += 1

            gain = 100 - (taille_apres * 100 / taille_avant) if taille_avant else 0
            self.stdout.write(
                f"  {'~' if dry_run else '>'} {activite.titre} : "
                f"{_mo(taille_avant)} -> {_mo(taille_apres)} (-{gain:.0f} %)"
            )

            if not dry_run:
                ancien_nom = activite.image.name
                activite.image.save(nom, contenu, save=True)
                # L'original n'a plus d'usage : le conserver garderait les
                # 15 Mo sur le disque sans que rien ne les serve.
                if activite.image.name != ancien_nom:
                    try:
                        activite.image.storage.delete(ancien_nom)
                    except Exception:
                        self.stderr.write(f"  ! original non supprimé : {ancien_nom}")

        self.stdout.write("")
        resume = (
            f"{traitees} image(s) optimisée(s), {ignorees} ignorée(s), {echecs} en échec."
        )
        if traitees:
            resume += f" Total {_mo(total_avant)} -> {_mo(total_apres)}."
        if dry_run:
            resume = "[SIMULATION] " + resume
        self.stdout.write(self.style.SUCCESS(resume))
