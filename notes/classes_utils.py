import re
import unicodedata

from django.db.models import Count, Q

from eleves.models import Classe as ClasseEleve


def normaliser_nom_classe(nom):
    """Retourne un nom comparable en ignorant accents, casse et ponctuation."""
    texte = unicodedata.normalize('NFKD', nom or '')
    texte = ''.join(caractere for caractere in texte if not unicodedata.combining(caractere))
    texte = texte.casefold().replace('œ', 'oe')
    return re.sub(r'[^a-z0-9]+', ' ', texte).strip()


def trouver_classe_eleve(classe_note):
    """Trouve sans ambiguïté la classe réelle liée à une classe du module Notes.

    L'établissement est toujours imposé. Une classe qui contient des élèves actifs
    est préférée lorsqu'une ancienne et une nouvelle année portent le même nom.
    """
    candidats = list(
        ClasseEleve.objects.filter(ecole_id=classe_note.ecole_id)
        .annotate(
            nombre_eleves_actifs=Count(
                'eleves', filter=Q(eleves__statut='ACTIF'), distinct=True
            )
        )
        .order_by('-annee_scolaire', 'id')
    )
    if not candidats:
        return None

    nom_recherche = normaliser_nom_classe(classe_note.nom)
    memes_noms = [
        classe for classe in candidats
        if normaliser_nom_classe(classe.nom) == nom_recherche
    ]

    # 1. Même nom et même année, à condition que la classe contienne des élèves.
    for classe in memes_noms:
        if (
            classe.annee_scolaire == classe_note.annee_scolaire
            and classe.nombre_eleves_actifs
        ):
            return classe

    # 2. Même nom normalisé dans une autre année contenant les élèves actuels.
    for classe in memes_noms:
        if classe.nombre_eleves_actifs:
            return classe

    # 3. Conserver la correspondance exacte même si la classe est réellement vide.
    for classe in memes_noms:
        if classe.annee_scolaire == classe_note.annee_scolaire:
            return classe
    if len(memes_noms) == 1:
        return memes_noms[0]

    # 4. CRECHE/GARDERIE et autres libellés différents : le niveau permet la
    # liaison uniquement lorsqu'une seule classe active est possible.
    meme_niveau_actif = [
        classe for classe in candidats
        if classe.niveau == classe_note.niveau and classe.nombre_eleves_actifs
    ]
    meme_niveau_meme_annee = [
        classe for classe in meme_niveau_actif
        if classe.annee_scolaire == classe_note.annee_scolaire
    ]
    if len(meme_niveau_meme_annee) == 1:
        return meme_niveau_meme_annee[0]
    if len(meme_niveau_actif) == 1:
        return meme_niveau_actif[0]

    return None
