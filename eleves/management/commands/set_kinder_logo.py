import os

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from eleves.models import Ecole


class Command(BaseCommand):
    help = (
        "Affiche le logo actuellement enregistre pour chaque ecole, et permet de le "
        "remplacer par le logo Kinder School International (static/logos/logo.png) "
        "avec --apply. Sans --apply, la commande ne fait qu'un rapport (dry-run)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help="Applique reellement le remplacement du logo (sinon, rapport seul).",
        )
        parser.add_argument(
            '--ecole-id',
            type=int,
            default=None,
            help="Limiter l'operation a une seule ecole (par id). Par defaut : toutes.",
        )

    def handle(self, *args, **options):
        source_path = os.path.join(settings.BASE_DIR, 'static', 'logos', 'logo.png')
        if not os.path.exists(source_path):
            raise CommandError(f"Logo source introuvable : {source_path}")

        ecoles = Ecole.objects.all()
        if options['ecole_id']:
            ecoles = ecoles.filter(id=options['ecole_id'])

        if not ecoles.exists():
            self.stdout.write(self.style.WARNING("Aucune ecole trouvee."))
            return

        for ecole in ecoles:
            actuel = ecole.logo.name if ecole.logo else "(aucun logo)"
            self.stdout.write(f"Ecole #{ecole.id} - {ecole.nom} : logo actuel = {actuel}")

        if not options['apply']:
            self.stdout.write(self.style.WARNING(
                "\nMode rapport uniquement. Relancez avec --apply pour remplacer le logo."
            ))
            return

        for ecole in ecoles:
            with open(source_path, 'rb') as f:
                ecole.logo.save('kinder_school_international_logo.png', File(f), save=True)
            self.stdout.write(self.style.SUCCESS(
                f"Logo mis a jour pour l'ecole #{ecole.id} - {ecole.nom}"
            ))

        self.stdout.write(self.style.SUCCESS(f"\n{ecoles.count()} ecole(s) mise(s) a jour."))
