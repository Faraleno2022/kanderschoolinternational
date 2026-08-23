"""
Vue pour démarrer une nouvelle année scolaire :
- Duplique les classes (eleves + notes), matières, grilles tarifaires
- Fait passer automatiquement les élèves admis en classe supérieure
  avec détection INTELLIGENTE de la classe correspondante
- Permet de revenir à une année scolaire passée (via session)
"""

import logging
import re
import unicodedata
from typing import Optional, List, Tuple

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Count

from decimal import Decimal
from datetime import date as _date_type

from .models import Ecole, Classe, Eleve, HistoriqueEleve
from utilisateurs.utils import user_school, user_is_admin
from .utils_annee import get_annee_active, get_statut_creation_nouvelle_annee, SESSION_ANNEE_ACTIVE

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  UTILITAIRE : MOYENNE ANNUELLE POUR PASSAGE
# ══════════════════════════════════════════════════════════════════════════════

def _get_moyenne_annuelle(eleve, annee_scolaire):
    """Retourne la meilleure estimation de la moyenne annuelle d'un élève.

    Ordre de priorité :
    1. Classement avec période ANNUEL_TRIM ou ANNUEL_SEM
    2. Moyenne des classements trimestriels/semestriels
    3. Dernier classement disponible (TRIMESTRE_3, SEMESTRE_2, etc.)
    4. None si aucune donnée

    Retourne (moyenne: float|None, sur: int) — sur=10 pour primaire, 20 sinon.
    """
    from notes.models import Classement, ClasseNote
    from notes.calculs_moyennes import detecter_niveau_scolaire

    # Détecter le niveau
    niveau_scolaire = 'COLLEGE'
    try:
        classe_nom = eleve.classe.nom if eleve.classe else ''
        niveau_scolaire = detecter_niveau_scolaire(classe_nom)
    except Exception:
        pass

    if niveau_scolaire == 'MATERNELLE':
        return None, 10  # Pas de notes numériques

    sur = 10 if niveau_scolaire == 'PRIMAIRE' else 20

    # Chercher les classements de cet élève pour l'année
    classements = Classement.objects.filter(
        eleve=eleve,
        annee_scolaire=annee_scolaire,
    ).order_by('-date_calcul')

    if not classements.exists():
        return None, sur

    # 1) Classement annuel
    for c in classements:
        if 'ANNUEL' in c.periode.upper():
            return float(c.moyenne_generale), sur

    # 2) Moyenne des trimestres/semestres
    periodes_finales = ['TRIMESTRE_1', 'TRIMESTRE_2', 'TRIMESTRE_3',
                        'SEMESTRE_1', 'SEMESTRE_2']
    notes_periodes = []
    for c in classements:
        if c.periode in periodes_finales:
            notes_periodes.append(float(c.moyenne_generale))
    if notes_periodes:
        return round(sum(notes_periodes) / len(notes_periodes), 2), sur

    # 3) Dernier classement disponible
    return float(classements[0].moyenne_generale), sur


def _est_admis(moyenne, sur):
    """Vérifie si une moyenne est suffisante pour passer.
    Seuil: 5/10 pour primaire, 10/20 pour secondaire.
    """
    if moyenne is None:
        return False
    seuil = 5.0 if sur == 10 else 10.0
    return moyenne >= seuil


# ══════════════════════════════════════════════════════════════════════════════
#  GESTION DES ANNÉES SCOLAIRES
# ══════════════════════════════════════════════════════════════════════════════

@login_required
def gestion_annees(request):
    """Liste toutes les années scolaires et permet de basculer l'année active."""
    ecole = user_school(request.user)
    if not ecole:
        messages.error(request, "Aucune école associée à votre compte.")
        return redirect('eleves:liste_eleves')

    from django.db.models import Q
    annees_qs = (Classe.objects
                 .filter(ecole=ecole)
                 .values('annee_scolaire')
                 .annotate(
                     nb_classes=Count('id', distinct=True),
                     nb_eleves=Count('eleves', filter=Q(eleves__statut='ACTIF')),
                 )
                 .order_by('-annee_scolaire'))

    annee_active = get_annee_active(request, ecole)

    annees = []
    for a in annees_qs:
        annees.append({
            'annee': a['annee_scolaire'],
            'nb_classes': a['nb_classes'],
            'nb_eleves': a['nb_eleves'],
            'est_active': a['annee_scolaire'] == annee_active,
            'est_recente': a == annees_qs[0],
        })

    context = {
        'ecole': ecole,
        'annees': annees,
        'annee_active': annee_active,
        'nouvelle_annee_status': get_statut_creation_nouvelle_annee(ecole),
        'titre_page': 'Gestion des années scolaires',
    }
    return render(request, 'eleves/gestion_annees.html', context)


@login_required
def changer_annee_active(request):
    """Bascule l'année scolaire active en session."""
    if request.method != 'POST':
        return redirect('eleves:gestion_annees')

    ecole = user_school(request.user)
    if not ecole:
        messages.error(request, "Aucune école associée à votre compte.")
        return redirect('eleves:liste_eleves')

    annee = request.POST.get('annee', '').strip()
    if not annee:
        messages.error(request, "Année scolaire manquante.")
        return redirect('eleves:gestion_annees')

    # Vérifier que cette année existe bien pour cette école
    existe = Classe.objects.filter(ecole=ecole, annee_scolaire=annee).exists()
    if not existe:
        messages.error(request, f"L'année {annee} n'existe pas pour cet établissement.")
        return redirect('eleves:gestion_annees')

    request.session[SESSION_ANNEE_ACTIVE] = annee
    messages.success(request, f"Vous consultez maintenant l'année scolaire {annee}.")
    return redirect('eleves:gestion_annees')


# ══════════════════════════════════════════════════════════════════════════════
#  SYSTÈME INTELLIGENT DE PROGRESSION DES CLASSES
# ══════════════════════════════════════════════════════════════════════════════

def _normaliser(texte: str) -> str:
    """Normalise un nom de classe : MAJUSCULES, sans accents, sans parenthèses.

    Exemples:
        '10ÈME ANNÉE (A)' → '10EME ANNEE A'
        'Petite Section B'  → 'PETITE SECTION B'
        '11 Série Scientifique (B)' → '11 SERIE SCIENTIFIQUE B'
    """
    texte = texte.upper().strip()
    # Retirer les accents
    texte = unicodedata.normalize('NFD', texte)
    texte = ''.join(c for c in texte if unicodedata.category(c) != 'Mn')
    # Retirer les parenthèses
    texte = texte.replace('(', '').replace(')', '')
    # Normaliser les espaces multiples
    texte = ' '.join(texte.split())
    return texte


def _extraire_base_et_lettre(nom_classe: str) -> Tuple[str, Optional[str]]:
    """Extraire le nom de base normalisé et le suffixe lettre (A, B, C…).

    Exemples:
        '10ÈME ANNÉE (A)'             → ('10EME ANNEE', 'A')
        'PETITE SECTION B'             → ('PETITE SECTION', 'B')
        'GARDERIE'                     → ('GARDERIE', None)
        '11 SÉRIE SCIENTIFIQUE (B)'    → ('11 SERIE SCIENTIFIQUE', 'B')
        '12 SCIENCES MATHS'            → ('12 SCIENCES MATHS', None)
        'TERMINALE SCIENCES SOCIALES'  → ('TERMINALE SCIENCES SOCIALES', None)
    """
    nom = _normaliser(nom_classe)
    # Un suffixe lettre = une seule lettre A-Z isolée en fin de chaîne
    match = re.match(r'^(.+?)\s+([A-Z])$', nom)
    if match:
        return match.group(1).strip(), match.group(2)
    return nom, None


# ── Mapping de progression (toutes les clés sont normalisées) ─────────────────
# None = classe terminale → l'élève reste dans la même classe (nouvelle année)
PROGRESSION_CLASSES = {
    # ── Maternelle ──────────────────────────────────────────────
    'TOUT PETITE SECTION':   'PETITE SECTION',
    'TOUTE PETITE SECTION':  'PETITE SECTION',
    'TPS':                   'PS',
    'PETITE SECTION':        'MOYENNE SECTION',
    'PS':                    'MS',
    'MOYENNE SECTION':       'GRANDE SECTION',
    'MS':                    'GS',
    'GRANDE SECTION':        '1ERE ANNEE',      # passage automatique vers primaire
    'GS':                    '1ERE ANNEE',

    # ── Primaire (1ère → 6ème) ──────────────────────────────────
    '1ERE ANNEE':  '2EME ANNEE',
    '2EME ANNEE':  '3EME ANNEE',
    '3EME ANNEE':  '4EME ANNEE',
    '4EME ANNEE':  '5EME ANNEE',
    '5EME ANNEE':  '6EME ANNEE',
    '6EME ANNEE':  '7EME ANNEE',

    # ── Collège (7ème → 10ème) ──────────────────────────────────
    '7EME ANNEE':   '8EME ANNEE',
    '8EME ANNEE':   '9EME ANNEE',
    '9EME ANNEE':  '10EME ANNEE',
    '10EME ANNEE': '11EME ANNEE',

    # ── Lycée 11ème → 12ème ─────────────────────────────────────
    '11EME ANNEE':           '12EME ANNEE',
    '11 SERIE LITTERAIRE':   '12 SCIENCES SOCIALES',
    '11 SERIE SCIENTIFIQUE': '12 SCIENCES',  # → 12 Sc. MATHS ou EXPERIMENTALES

    # ── Lycée 12ème → Terminale ─────────────────────────────────
    '12EME ANNEE':                    'TERMINALE',
    '12 SCIENCES EXPERIMENTALES':     'TERMINALE SCIENCES EXPERIMENTALES',
    '12 SCIENCES MATHS':              'TERMINALE SCIENCES MATHS',
    '12 SCIENCES SOCIALES':           'TERMINALE SCIENCES SOCIALES',
    '12 SERIE LITTERAIRE':            'TERMINALE SCIENCES SOCIALES',

    # ── Garderie → Petite Section ─────────────────────────────────
    'GARDERIE':                           'PETITE SECTION',

    # ── Terminale : fin de cycle (archivage BAC) ──────────────────
    'TERMINALE':                          None,
    'TERMINALE SCIENCES EXPERIMENTALES':  None,
    'TERMINALE SCIENCES MATHS':           None,
    'TERMINALE SCIENCES SOCIALES':        None,
}

# Classes terminales dont les élèves sortent du système
CLASSES_TERMINALES = {
    'TERMINALE', 'TERMINALE SCIENCES EXPERIMENTALES',
    'TERMINALE SCIENCES MATHS', 'TERMINALE SCIENCES SOCIALES',
}

# Classes de fin de cycle avec examen national
# Les élèves passent en classe supérieure, mais on enregistre le diplôme
CLASSES_EXAMEN = {
    '6EME ANNEE': {'diplome': 'CEP', 'label': "Certificat d'Études Primaires (CEP)"},
    '10EME ANNEE': {'diplome': 'BEPC', 'label': 'Brevet d\'Études du Premier Cycle (BEPC)'},
}

# Labels lisibles pour l'affichage dans le tableau de prévisualisation
PROGRESSION_LABELS = {
    'PETITE SECTION':         'Petite Section',
    'PS':                     'PS',
    'MOYENNE SECTION':        'Moyenne Section',
    'MS':                     'MS',
    'GRANDE SECTION':         'Grande Section',
    'GS':                     'GS',
    '1ERE ANNEE':             '1ère Année',
    '2EME ANNEE':             '2ème Année',
    '3EME ANNEE':             '3ème Année',
    '4EME ANNEE':             '4ème Année',
    '5EME ANNEE':             '5ème Année',
    '6EME ANNEE':             '6ème Année',
    '7EME ANNEE':             '7ème Année',
    '8EME ANNEE':             '8ème Année',
    '9EME ANNEE':             '9ème Année',
    '10EME ANNEE':            '10ème Année',
    '11EME ANNEE':            '11ème Année',
    '12EME ANNEE':            '12ème Année',
    '12 SCIENCES':            '12 Sciences (Maths ou Exp.)',
    '12 SCIENCES SOCIALES':   '12 Sciences Sociales',
    'TERMINALE':                          'Terminale',
    'TERMINALE SCIENCES EXPERIMENTALES':  'Terminale Sciences Expérimentales',
    'TERMINALE SCIENCES MATHS':           'Terminale Sciences Maths',
    'TERMINALE SCIENCES SOCIALES':        'Terminale Sciences Sociales',
}


def _annee_suivante(annee: str) -> str:
    """Calcule l'année scolaire suivante. Ex: '2024-2025' → '2025-2026'"""
    try:
        debut, fin = annee.split('-')
        return f"{int(debut)+1}-{int(fin)+1}"
    except Exception:
        return annee


def _classe_superieure_label(nom_classe: str) -> Optional[str]:
    """Retourne le libellé lisible de la classe supérieure, ou None si terminale.

    Exemples:
        '10ÈME ANNÉE (A)' → '11ème Année A'
        'GRANDE SECTION (A)' → '1ère Année A'
        '11 SÉRIE LITTÉRAIRE (A)' → '12 Sciences Sociales A'
        'GARDERIE' → None  (dernière année)
        'TERMINALE SCIENCES MATHS' → None  (dernière année)
    """
    base, lettre = _extraire_base_et_lettre(nom_classe)
    cible_base = PROGRESSION_CLASSES.get(base)

    if cible_base is None:
        return None  # Classe terminale ou inconnue

    label = PROGRESSION_LABELS.get(cible_base, cible_base)
    if lettre:
        label += f' {lettre}'
    return label


def _construire_index_classes(classes) -> List[Tuple]:
    """Construit un index normalisé (base, lettre) pour chaque classe.

    Retourne une liste de tuples (classe_obj, base_normalisée, lettre).
    """
    index = []
    for cls in classes:
        base, lettre = _extraire_base_et_lettre(cls.nom)
        index.append((cls, base, lettre))
    return index


def _trouver_classe_cible(nom_classe_actuelle: str, index_nouvelles: List[Tuple]) -> Optional[Classe]:
    """Trouve la meilleure classe cible par matching intelligent multi-niveaux.

    Algorithme de correspondance (du plus précis au plus souple) :

    Niveau 1 — Match exact : base normalisée + même lettre
        Ex: cible '2EME ANNEE' + lettre 'A' → trouve '2ÈME ANNÉE A'

    Niveau 2 — Match base exacte sans contrainte de lettre
        Ex: cible 'MOYENNE SECTION' → trouve 'MOYENNE SECTION' (unique)

    Niveau 3 — Match par préfixe (pour séries scientifiques)
        Ex: cible '12 SCIENCES' → trouve '12 SCIENCES MATHS' ou '12 SCIENCES EXPERIMENTALES'

    Niveau 4 — Match par numéro de niveau + lettre
        Ex: cible '11EME ANNEE' → trouve '11 SÉRIE LITTÉRAIRE (A)' si pas de 11ème générique

    Retourne la classe trouvée ou None.
    """
    base_actuelle, lettre = _extraire_base_et_lettre(nom_classe_actuelle)
    cible_base = PROGRESSION_CLASSES.get(base_actuelle)

    if cible_base is None:
        return None  # Classe terminale → pas de progression

    # ── Niveau 1 : Base exacte + même lettre ──
    for cls, c_base, c_lettre in index_nouvelles:
        if c_base == cible_base and c_lettre == lettre:
            return cls

    # ── Niveau 2 : Base exacte, n'importe quelle lettre ──
    for cls, c_base, c_lettre in index_nouvelles:
        if c_base == cible_base:
            return cls

    # ── Niveau 3 : Préfixe de la base cible ──
    # Utile pour '12 SCIENCES' → '12 SCIENCES MATHS', '12 SCIENCES EXPERIMENTALES'
    prefix = cible_base + ' '
    # D'abord avec la même lettre
    if lettre:
        for cls, c_base, c_lettre in index_nouvelles:
            if c_base.startswith(prefix) and c_lettre == lettre:
                return cls
    # Puis sans contrainte de lettre
    for cls, c_base, c_lettre in index_nouvelles:
        if c_base.startswith(prefix):
            return cls

    # ── Niveau 4 : Numéro de niveau (ex: 11 → n'importe quelle 11ème) ──
    num_match = re.match(r'^(\d+)', cible_base)
    if num_match:
        num_str = num_match.group(1)
        # Pattern : le numéro suivi de EME, ERE, un espace, ou fin de chaîne
        pattern = re.compile(rf'^{re.escape(num_str)}(?:EME|ERE|\s|$)')
        # D'abord avec la même lettre
        if lettre:
            for cls, c_base, c_lettre in index_nouvelles:
                if pattern.match(c_base) and c_lettre == lettre:
                    return cls
        # Puis sans contrainte de lettre
        for cls, c_base, c_lettre in index_nouvelles:
            if pattern.match(c_base):
                return cls

    return None


# ══════════════════════════════════════════════════════════════════════════════
#  VUES : APERÇU & CRÉATION DE LA NOUVELLE ANNÉE
# ══════════════════════════════════════════════════════════════════════════════

@login_required
def nouvelle_annee_apercu(request):
    """Affiche un aperçu de ce qui sera créé pour la nouvelle année."""
    ecole = user_school(request.user)
    if not ecole:
        messages.error(request, "Aucune école associée à votre compte.")
        return redirect('eleves:liste_eleves')

    # Détecter l'année courante (la plus récente)
    annees = (Classe.objects
              .filter(ecole=ecole)
              .values_list('annee_scolaire', flat=True)
              .distinct()
              .order_by('-annee_scolaire'))
    if not annees:
        messages.warning(request, "Aucune classe trouvée pour cet établissement.")
        return redirect('eleves:gestion_classes')

    annee_courante = annees[0]
    annee_nouvelle = _annee_suivante(annee_courante)

    # Vérifier si la nouvelle année existe déjà
    deja_existante = Classe.objects.filter(ecole=ecole, annee_scolaire=annee_nouvelle).exists()

    classes_actuelles = (Classe.objects
                         .filter(ecole=ecole, annee_scolaire=annee_courante)
                         .prefetch_related('eleves')
                         .order_by('niveau', 'nom'))

    preview_classes = []
    for cls in classes_actuelles:
        sup_label = _classe_superieure_label(cls.nom)
        nb_eleves = cls.eleves.filter(statut='ACTIF').count()
        preview_classes.append({
            'classe': cls,
            'nb_eleves': nb_eleves,
            'classe_superieure': sup_label,
        })

    # Grilles tarifaires courantes
    from .models import GrilleTarifaire
    grilles = GrilleTarifaire.objects.filter(ecole=ecole, annee_scolaire=annee_courante)

    # Classes notes (du module notes)
    from notes.models import ClasseNote, MatiereNote
    classes_notes = ClasseNote.objects.filter(
        ecole=ecole, annee_scolaire=annee_courante, actif=True
    ).prefetch_related('matieres')
    preview_notes = []
    for cn in classes_notes:
        preview_notes.append({
            'classe_note': cn,
            'nb_matieres': cn.matieres.filter(actif=True).count(),
        })

    # Élèves de Terminale (pour que l'utilisateur coche ceux qui ont le BAC)
    eleves_terminale = []
    for cls in classes_actuelles:
        base, _ = _extraire_base_et_lettre(cls.nom)
        if base in CLASSES_TERMINALES:
            for eleve in cls.eleves.filter(statut='ACTIF').order_by('nom', 'prenom'):
                eleves_terminale.append({
                    'eleve': eleve,
                    'classe_nom': cls.nom,
                })

    # Élèves de 6ème (CEP) et 10ème (BEPC)
    eleves_examens = []  # liste de {'diplome': 'CEP'/'BEPC', 'label': ..., 'eleves': [...]}
    for base_classe, info_examen in CLASSES_EXAMEN.items():
        eleves_de_ce_niveau = []
        for cls in classes_actuelles:
            base, _ = _extraire_base_et_lettre(cls.nom)
            if base == base_classe:
                for eleve in cls.eleves.filter(statut='ACTIF').order_by('nom', 'prenom'):
                    eleves_de_ce_niveau.append({
                        'eleve': eleve,
                        'classe_nom': cls.nom,
                    })
        if eleves_de_ce_niveau:
            eleves_examens.append({
                'diplome': info_examen['diplome'],
                'label': info_examen['label'],
                'eleves': eleves_de_ce_niveau,
            })

    # Élèves sans la moyenne (non admis) — hors maternelle/garderie/terminale
    from notes.calculs_moyennes import detecter_niveau_scolaire
    eleves_non_admis = []
    classes_skip = CLASSES_TERMINALES | {'GARDERIE', 'TOUTE PETITE SECTION', 'TOUT PETITE SECTION',
                                          'TPS', 'PETITE SECTION', 'PS', 'MOYENNE SECTION', 'MS',
                                          'GRANDE SECTION', 'GS'}
    for cls in classes_actuelles:
        base, _ = _extraire_base_et_lettre(cls.nom)
        niveau_scol = detecter_niveau_scolaire(cls.nom)
        if base in CLASSES_TERMINALES or niveau_scol == 'MATERNELLE':
            continue
        for eleve in cls.eleves.filter(statut='ACTIF').order_by('nom', 'prenom'):
            moyenne, sur = _get_moyenne_annuelle(eleve, annee_courante)
            if not _est_admis(moyenne, sur):
                eleves_non_admis.append({
                    'eleve': eleve,
                    'classe_nom': cls.nom,
                    'moyenne': moyenne,
                    'sur': sur,
                    'seuil': 5.0 if sur == 10 else 10.0,
                })

    context = {
        'ecole': ecole,
        'annee_courante': annee_courante,
        'annee_nouvelle': annee_nouvelle,
        'deja_existante': deja_existante,
        'preview_classes': preview_classes,
        'grilles': grilles,
        'preview_notes': preview_notes,
        'nb_total_eleves': sum(p['nb_eleves'] for p in preview_classes),
        'eleves_terminale': eleves_terminale,
        'eleves_examens': eleves_examens,
        'eleves_non_admis': eleves_non_admis,
        'titre_page': f'Nouvelle Année Scolaire {annee_nouvelle}',
    }
    return render(request, 'eleves/nouvelle_annee.html', context)


@login_required
def nouvelle_annee_creer(request):
    """Exécute la création de la nouvelle année scolaire."""
    if request.method != 'POST':
        return redirect('eleves:nouvelle_annee_apercu')

    ecole = user_school(request.user)
    if not ecole:
        messages.error(request, "Aucune école associée à votre compte.")
        return redirect('eleves:liste_eleves')

    annee_courante = request.POST.get('annee_courante', '').strip()
    annee_nouvelle = request.POST.get('annee_nouvelle', '').strip()
    dupliquer_grilles = request.POST.get('dupliquer_grilles') == '1'
    dupliquer_notes_classes = request.POST.get('dupliquer_notes_classes') == '1'
    faire_passer_eleves = request.POST.get('faire_passer_eleves') == '1'
    # Liste des IDs d'élèves qui ont eu le BAC (cochés par l'utilisateur)
    eleves_bac_ids = set(request.POST.getlist('eleves_bac', []))
    # Liste des IDs d'élèves qui ont eu le CEP / BEPC
    eleves_cep_ids = set(request.POST.getlist('eleves_cep', []))
    eleves_bepc_ids = set(request.POST.getlist('eleves_bepc', []))
    # Liste des IDs d'élèves non admis mais forcés par convention (direction/parents)
    eleves_convention_ids = set(request.POST.getlist('eleves_convention', []))

    if not annee_courante or not annee_nouvelle:
        messages.error(request, "Paramètres manquants.")
        return redirect('eleves:nouvelle_annee_apercu')

    resultats = {
        'classes_creees': 0,
        'grilles_creees': 0,
        'configs_paiement_creees': 0,
        'classes_notes_creees': 0,
        'matieres_creees': 0,
        'eleves_passes': 0,
        'eleves_conserves': 0,
        'eleves_diplomes': 0,
        'eleves_sortis': 0,
        'eleves_cep': 0,
        'eleves_bepc': 0,
        'eleves_convention': 0,
        'eleves_redoublants': 0,
        'echeanciers_crees': 0,
        'erreurs': [],
    }

    try:
        with transaction.atomic():
            # ─── Étape 1 : Dupliquer les classes (eleves.Classe) ─────────
            classes_actuelles = Classe.objects.filter(
                ecole=ecole, annee_scolaire=annee_courante
            ).order_by('niveau', 'nom')

            map_anciennes_nouvelles = {}  # ancienne_pk → nouvelle_classe

            for cls in classes_actuelles:
                nouvelle_cls, created = Classe.objects.get_or_create(
                    ecole=ecole,
                    nom=cls.nom,
                    annee_scolaire=annee_nouvelle,
                    defaults={
                        'niveau': cls.niveau,
                        'capacite_max': cls.capacite_max,
                        'code_matricule': cls.code_matricule,
                    }
                )
                if created:
                    resultats['classes_creees'] += 1
                map_anciennes_nouvelles[cls.pk] = nouvelle_cls

            # ─── Étape 1bis : Dupliquer ConfigurationPaiement ─────────
            from paiements.models import ConfigurationPaiement
            for ancien_pk, nouvelle_cls in map_anciennes_nouvelles.items():
                try:
                    ancien_cls = Classe.objects.get(pk=ancien_pk)
                    config_ancienne = getattr(ancien_cls, 'configuration_paiement', None)
                    if config_ancienne and not hasattr(nouvelle_cls, 'configuration_paiement'):
                        # Vérifier que la nouvelle classe n'a pas déjà une config
                        if not ConfigurationPaiement.objects.filter(classe=nouvelle_cls).exists():
                            ConfigurationPaiement.objects.create(
                                classe=nouvelle_cls,
                                montant_inscription=config_ancienne.montant_inscription,
                                montant_scolarite=config_ancienne.montant_scolarite,
                                nombre_tranches=config_ancienne.nombre_tranches,
                                cree_par=request.user,
                            )
                            resultats['configs_paiement_creees'] += 1
                except Exception as exc:
                    logger.warning(f"Config paiement non copiée pour {nouvelle_cls.nom}: {exc}")

            # ─── Étape 2 : Dupliquer les grilles tarifaires ─────────────
            if dupliquer_grilles:
                from .models import GrilleTarifaire
                grilles = GrilleTarifaire.objects.filter(
                    ecole=ecole, annee_scolaire=annee_courante
                )
                for g in grilles:
                    _, created = GrilleTarifaire.objects.get_or_create(
                        ecole=ecole,
                        niveau=g.niveau,
                        annee_scolaire=annee_nouvelle,
                        defaults={
                            'frais_inscription': g.frais_inscription,
                            'frais_reinscription': g.frais_reinscription,
                            'tranche_1': g.tranche_1,
                            'tranche_2': g.tranche_2,
                            'tranche_3': g.tranche_3,
                            'periode_1': g.periode_1,
                            'periode_2': g.periode_2,
                            'periode_3': g.periode_3,
                        }
                    )
                    if created:
                        resultats['grilles_creees'] += 1

            # ─── Étape 3 : Dupliquer ClasseNote + MatiereNote ───────────
            if dupliquer_notes_classes:
                from notes.models import ClasseNote, MatiereNote
                classes_notes = ClasseNote.objects.filter(
                    ecole=ecole, annee_scolaire=annee_courante, actif=True
                )
                for cn in classes_notes:
                    nouvelle_cn, created = ClasseNote.objects.get_or_create(
                        ecole=ecole,
                        nom=cn.nom,
                        annee_scolaire=annee_nouvelle,
                        defaults={
                            'niveau': cn.niveau,
                            'niveau_enseignement': cn.niveau_enseignement,
                            'effectif': cn.effectif,
                            'description': cn.description,
                            'actif': True,
                            'cree_par': request.user,
                        }
                    )
                    if created:
                        resultats['classes_notes_creees'] += 1
                        # Dupliquer les matières
                        for m in cn.matieres.filter(actif=True):
                            _, m_created = MatiereNote.objects.get_or_create(
                                classe=nouvelle_cn,
                                code=m.code,
                                defaults={
                                    'nom': m.nom,
                                    'coefficient': m.coefficient,
                                    'description': m.description,
                                    'actif': True,
                                    'cree_par': request.user,
                                }
                            )
                            if m_created:
                                resultats['matieres_creees'] += 1

            # ─── Étape 4 : Passage intelligent des élèves ───────────────
            if faire_passer_eleves:
                eleves_actifs = Eleve.objects.filter(
                    classe__ecole=ecole,
                    classe__annee_scolaire=annee_courante,
                    statut='ACTIF'
                ).select_related('classe')

                # Construire l'index des classes de la nouvelle année (une seule fois)
                classes_nouvelles = list(Classe.objects.filter(
                    ecole=ecole, annee_scolaire=annee_nouvelle
                ))
                index_nouvelles = _construire_index_classes(classes_nouvelles)

                for eleve in eleves_actifs:
                    ancienne_classe = eleve.classe
                    base_actuelle, _ = _extraire_base_et_lettre(ancienne_classe.nom)

                    # Vérifier si c'est une classe terminale (Terminale)
                    est_terminale = base_actuelle in CLASSES_TERMINALES

                    if est_terminale:
                        eleve_id_str = str(eleve.pk)
                        if eleve_id_str in eleves_bac_ids:
                            # L'élève a eu le BAC → archiver (DIPLOME)
                            eleve.statut = 'DIPLOME'
                            eleve.save()
                            HistoriqueEleve.objects.create(
                                eleve=eleve,
                                action='DIPLOME',
                                description=(
                                    f"Diplômé(e) — BAC obtenu, archivé(e) lors du passage "
                                    f"à l'année {annee_nouvelle}. Classe: {ancienne_classe.nom}"
                                ),
                                utilisateur=request.user,
                            )
                            resultats['eleves_diplomes'] += 1
                        else:
                            # Pas de BAC → sortie du système (fin de cycle)
                            eleve.statut = 'TRANSFERE'
                            eleve.save()
                            HistoriqueEleve.objects.create(
                                eleve=eleve,
                                action='FIN_CYCLE',
                                description=(
                                    f"Fin de cycle — sorti(e) du système lors du passage "
                                    f"à l'année {annee_nouvelle}. Classe: {ancienne_classe.nom}"
                                ),
                                utilisateur=request.user,
                            )
                            resultats['eleves_sortis'] += 1
                        continue

                    # Vérifier la moyenne de l'élève (hors maternelle)
                    from notes.calculs_moyennes import detecter_niveau_scolaire as _det_niv
                    _niveau_scol = _det_niv(ancienne_classe.nom)
                    eleve_id_str = str(eleve.pk)

                    if _niveau_scol != 'MATERNELLE':
                        moyenne, sur = _get_moyenne_annuelle(eleve, annee_courante)
                        admis = _est_admis(moyenne, sur)
                        par_convention = eleve_id_str in eleves_convention_ids
                    else:
                        # Maternelle: pas de contrôle de moyenne
                        admis = True
                        par_convention = False
                        moyenne = None

                    # Si non admis et non forcé par convention → redoublant
                    if not admis and not par_convention:
                        nouvelle_meme = map_anciennes_nouvelles.get(ancienne_classe.pk)
                        if nouvelle_meme:
                            eleve._current_user = request.user
                            eleve.classe = nouvelle_meme
                            eleve.save()
                            moy_txt = f"{moyenne}/{sur}" if moyenne is not None else "non évaluée"
                            HistoriqueEleve.objects.create(
                                eleve=eleve,
                                action='CHANGEMENT_CLASSE',
                                description=(
                                    f"Redoublant — année {annee_nouvelle}: "
                                    f"maintenu(e) en {ancienne_classe.nom} "
                                    f"(moyenne: {moy_txt})"
                                ),
                                utilisateur=request.user,
                            )
                            resultats['eleves_redoublants'] += 1
                        continue

                    # Matching intelligent de la classe supérieure
                    sup_cls = _trouver_classe_cible(ancienne_classe.nom, index_nouvelles)

                    if sup_cls:
                        eleve._current_user = request.user
                        eleve.classe = sup_cls
                        eleve.save()
                        convention_txt = " (par convention direction/parents)" if par_convention else ""
                        moy_txt = f" — moyenne: {moyenne}/{sur}" if moyenne is not None else ""
                        desc_passage = (
                            f"Passage nouvelle année {annee_nouvelle}: "
                            f"{ancienne_classe.nom} → {sup_cls.nom}{moy_txt}{convention_txt}"
                        )
                        HistoriqueEleve.objects.create(
                            eleve=eleve,
                            action='CHANGEMENT_CLASSE',
                            description=desc_passage,
                            utilisateur=request.user,
                        )
                        if par_convention:
                            resultats['eleves_convention'] += 1
                        resultats['eleves_passes'] += 1

                        # Enregistrer le diplôme CEP/BEPC si l'élève est coché
                        if base_actuelle == '6EME ANNEE' and eleve_id_str in eleves_cep_ids:
                            HistoriqueEleve.objects.create(
                                eleve=eleve,
                                action='DIPLOME',
                                description=(
                                    f"Certificat d'Études Primaires (CEP) obtenu — "
                                    f"année {annee_courante}, classe: {ancienne_classe.nom}"
                                ),
                                utilisateur=request.user,
                            )
                            resultats['eleves_cep'] += 1
                        elif base_actuelle == '10EME ANNEE' and eleve_id_str in eleves_bepc_ids:
                            HistoriqueEleve.objects.create(
                                eleve=eleve,
                                action='DIPLOME',
                                description=(
                                    f"Brevet d'Études du Premier Cycle (BEPC) obtenu — "
                                    f"année {annee_courante}, classe: {ancienne_classe.nom}"
                                ),
                                utilisateur=request.user,
                            )
                            resultats['eleves_bepc'] += 1
                    else:
                        # Aucune correspondance → garder dans même classe (nouvelle année)
                        nouvelle_meme = map_anciennes_nouvelles.get(ancienne_classe.pk)
                        if nouvelle_meme:
                            eleve._current_user = request.user
                            eleve.classe = nouvelle_meme
                            eleve.save()
                            HistoriqueEleve.objects.create(
                                eleve=eleve,
                                action='CHANGEMENT_CLASSE',
                                description=(
                                    f"Conservation nouvelle année {annee_nouvelle}: "
                                    f"{ancienne_classe.nom} → {nouvelle_meme.nom} "
                                    f"(classe supérieure non trouvée)"
                                ),
                                utilisateur=request.user,
                            )
                            resultats['eleves_conserves'] += 1

            # ─── Étape 5 : Recréer les échéanciers pour la nouvelle année ─
            # Pour chaque élève qui a changé de classe, garantir l'échéancier
            # cible sans supprimer les échéanciers/paiements des années passées.
            if faire_passer_eleves:
                from paiements.models import EcheancierPaiement
                from .models import GrilleTarifaire

                eleves_nouvelle_annee = Eleve.objects.filter(
                    classe__ecole=ecole,
                    classe__annee_scolaire=annee_nouvelle,
                    statut='ACTIF',
                ).select_related('classe', 'classe__ecole')

                try:
                    annee_debut = int(annee_nouvelle.split('-')[0])
                except Exception:
                    annee_debut = _date_type.today().year
                annee_fin = annee_debut + 1

                for eleve in eleves_nouvelle_annee:
                    try:
                        # Chercher la grille tarifaire de la nouvelle année
                        niveau = getattr(eleve.classe, 'niveau', None)
                        grille = None
                        if niveau:
                            grille = GrilleTarifaire.objects.filter(
                                ecole=ecole, niveau=niveau, annee_scolaire=annee_nouvelle
                            ).first()

                        # Montants depuis la grille (ou 0 si pas de grille)
                        fi = Decimal(str(grille.frais_reinscription or 0)) if grille else Decimal('0')
                        t1 = Decimal(str(grille.tranche_1 or 0)) if grille else Decimal('0')
                        t2 = Decimal(str(grille.tranche_2 or 0)) if grille else Decimal('0')
                        t3 = Decimal(str(grille.tranche_3 or 0)) if grille else Decimal('0')

                        _, echeancier_cree = EcheancierPaiement.objects.get_or_create(
                            eleve=eleve,
                            annee_scolaire=annee_nouvelle,
                            ecole_reference=ecole,
                            defaults={
                                'classe_reference': eleve.classe,
                                'nature_frais': EcheancierPaiement.NATURE_REINSCRIPTION,
                                'frais_inscription_du': fi,
                                'tranche_1_due': t1,
                                'tranche_2_due': t2,
                                'tranche_3_due': t3,
                                'date_echeance_inscription': _date_type(annee_debut, 10, 1),
                                'date_echeance_tranche_1': _date_type(annee_fin, 1, 15),
                                'date_echeance_tranche_2': _date_type(annee_fin, 3, 15),
                                'date_echeance_tranche_3': _date_type(annee_fin, 5, 15),
                                'statut': 'A_PAYER',
                                'cree_par': request.user,
                            },
                        )
                        if echeancier_cree:
                            resultats['echeanciers_crees'] += 1
                    except Exception as exc:
                        logger.warning(f"Échéancier non créé pour {eleve}: {exc}")
                        resultats['erreurs'].append(f"Échéancier {eleve}: {exc}")

    except Exception as e:
        logger.error(f"Erreur création nouvelle année: {e}", exc_info=True)
        messages.error(request, f"Erreur lors de la création : {e}")
        return redirect('eleves:nouvelle_annee_apercu')

    # Message de succès
    msg_parts = []
    if resultats['classes_creees']:
        msg_parts.append(f"{resultats['classes_creees']} classe(s) créée(s)")
    if resultats['configs_paiement_creees']:
        msg_parts.append(f"{resultats['configs_paiement_creees']} config(s) paiement copiée(s)")
    if resultats['grilles_creees']:
        msg_parts.append(f"{resultats['grilles_creees']} grille(s) tarifaire(s) copiée(s)")
    if resultats['classes_notes_creees']:
        msg_parts.append(f"{resultats['classes_notes_creees']} classe(s) notes avec {resultats['matieres_creees']} matière(s)")
    if resultats['eleves_passes']:
        msg_parts.append(f"{resultats['eleves_passes']} élève(s) passé(s) en classe supérieure")
    if resultats['eleves_conserves']:
        msg_parts.append(f"{resultats['eleves_conserves']} élève(s) conservé(s) dans leur classe")
    if resultats['eleves_cep']:
        msg_parts.append(f"{resultats['eleves_cep']} élève(s) titulaire(s) du CEP")
    if resultats['eleves_bepc']:
        msg_parts.append(f"{resultats['eleves_bepc']} élève(s) titulaire(s) du BEPC")
    if resultats['eleves_diplomes']:
        msg_parts.append(f"{resultats['eleves_diplomes']} élève(s) diplômé(s) (BAC) archivé(s)")
    if resultats['eleves_sortis']:
        msg_parts.append(f"{resultats['eleves_sortis']} élève(s) sorti(s) du système (fin de cycle)")
    if resultats['eleves_convention']:
        msg_parts.append(f"{resultats['eleves_convention']} élève(s) promu(s) par convention (direction/parents)")
    if resultats['eleves_redoublants']:
        msg_parts.append(f"{resultats['eleves_redoublants']} élève(s) redoublant(s)")
    if resultats['echeanciers_crees']:
        msg_parts.append(f"{resultats['echeanciers_crees']} échéancier(s) de paiement créé(s)")

    messages.success(
        request,
        f"Année scolaire {annee_nouvelle} créée avec succès ! "
        + ((' | '.join(msg_parts)) if msg_parts else '')
    )
    return redirect('eleves:gestion_classes')
