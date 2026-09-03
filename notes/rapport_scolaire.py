"""
Rapport Scolaire Public — Accessible aux parents sans authentification.
Le parent renseigne le matricule de l'élève, son numéro de téléphone
et la classe. Le système vérifie que les informations correspondent
et génère un PDF complet : situation scolaire, notes, activités journalières.
"""
import io
import os
import re
from datetime import datetime
from urllib.parse import urlencode
from xml.sax.saxutils import escape
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace

from django.http import HttpResponse, Http404, JsonResponse
from django.shortcuts import render, redirect
from django.db.models import Q, Avg
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.utils import ImageReader
from PIL import Image

from eleves.models import Eleve, Classe, Ecole, VisiteMedicale
from notes.models import (
    ClasseNote, MatiereNote, NoteEleve, NoteMensuelle,
    CompositionNote, AppreciationMaternelle, BulletinMaternelle,
    ActiviteJournaliere, PieceJointeActivite, Classement,
)
from paiements.models import Paiement, EcheancierPaiement
from ecole_moderne.pdf_utils import draw_logo_watermark
from ecole_moderne.theme import get_school_palette

from django.utils.crypto import get_random_string
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired


# ────────────────────────────────────────────────────────────────
# UTILITAIRE : Token signé pour sécuriser l'accès
# ────────────────────────────────────────────────────────────────
_signer = TimestampSigner(salt='rapport-scolaire')


def _make_token(eleve_id):
    return _signer.sign(str(eleve_id))


def _verify_token(token, max_age=1800):
    """Vérifie le token et retourne l'eleve_id. Expire après 30 min."""
    try:
        return int(_signer.unsign(token, max_age=max_age))
    except (BadSignature, SignatureExpired, ValueError):
        return None


class ClassementList(list):
    def last(self):
        return self[-1] if self else None


def _classements_courants(eleve, classe_note, annee):
    """Construit les classements depuis le calcul central, pas depuis un snapshot."""
    if not classe_note:
        return []

    from .calculs_moyennes import (
        detecter_niveau_scolaire,
        obtenir_appreciation_intelligente,
        obtenir_mention_intelligente,
    )
    from .utils_rangs import calculer_rangs_classe_periode

    periodes = []
    periodes.extend(
        NoteMensuelle.objects.filter(
            eleve=eleve,
            matiere__classe=classe_note,
            annee_scolaire=annee,
            note__isnull=False,
        ).values_list('mois', flat=True).distinct()
    )
    periodes.extend(
        CompositionNote.objects.filter(
            eleve=eleve,
            matiere__classe=classe_note,
            annee_scolaire=annee,
            note__isnull=False,
        ).values_list('periode', flat=True).distinct()
    )

    ordre = {
        'OCTOBRE': 1, 'NOVEMBRE': 2, 'DECEMBRE': 3,
        'TRIMESTRE_1': 4, 'JANVIER': 5, 'FEVRIER': 6, 'MARS': 7,
        'TRIMESTRE_2': 8, 'SEMESTRE_1': 9, 'AVRIL': 10, 'MAI': 11,
        'JUIN': 12, 'TRIMESTRE_3': 13, 'SEMESTRE_2': 14,
    }
    resultats = []
    niveau = detecter_niveau_scolaire(classe_note.nom)
    for periode in sorted(set(periodes), key=lambda p: ordre.get(p, 999)):
        rangs = calculer_rangs_classe_periode(classe_note, periode, use_cache=False)
        info = rangs.get(eleve.id)
        if not info:
            continue
        moyenne = Decimal(str(info['moyenne']))
        total_eleves = info.get('total_eleves') or 0
        rang = info.get('rang_num') or info.get('rang')
        resultats.append(SimpleNamespace(
            periode=periode,
            moyenne_generale=moyenne,
            rang=rang,
            rang_formate=f"{info['rang']}/{total_eleves}" if total_eleves else str(info['rang']),
            effectif=total_eleves,
            mention=obtenir_mention_intelligente(moyenne, niveau),
            appreciation=obtenir_appreciation_intelligente(moyenne, eleve.prenom, niveau),
        ))
    return ClassementList(resultats)


# ────────────────────────────────────────────────────────────────
# UTILITAIRE : Collecter toutes les données scolaires
# ────────────────────────────────────────────────────────────────

def _collecter_donnees_scolaires(eleve):
    """Collecte toutes les données scolaires d'un élève pour le template et le PDF."""
    annee = eleve.classe.annee_scolaire if eleve.classe else ''
    ecole = eleve.classe.ecole if eleve.classe else None

    # ─── Classe Note ───
    classe_note = ClasseNote.objects.filter(
        nom=eleve.classe.nom,
        ecole=eleve.classe.ecole,
        annee_scolaire=annee,
        actif=True,
    ).first() if eleve.classe else None

    # ─── Notes mensuelles ───
    MOIS_ORDRE = ['OCTOBRE', 'NOVEMBRE', 'DECEMBRE', 'JANVIER', 'FEVRIER', 'MARS', 'AVRIL', 'MAI', 'JUIN']
    MOIS_LABELS = ['Oct', 'Nov', 'Déc', 'Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin']

    matieres = []
    matieres_data = []
    compo_periodes = []

    if classe_note:
        matieres_qs = MatiereNote.objects.filter(classe=classe_note, actif=True).order_by('nom')
        matieres = list(matieres_qs)
        from .calculs_moyennes import calculer_moyenne_annuelle_matiere, calculer_moyenne_generale_annuelle

        # Collecter les périodes de composition existantes
        compo_periodes_set = set()
        for mat in matieres:
            compos = CompositionNote.objects.filter(
                eleve=eleve, matiere=mat, annee_scolaire=annee
            )
            for c in compos:
                compo_periodes_set.add((c.periode, c.get_periode_display()))
        compo_periodes = sorted(compo_periodes_set, key=lambda x: x[0])
        compo_codes = {p[0] for p in compo_periodes}
        annual_system = None
        if any(p.startswith('TRIMESTRE') for p in compo_codes):
            annual_system = 'annuel_trimestriel'
        elif any(p.startswith('SEMESTRE') for p in compo_codes):
            annual_system = 'annuel_semestriel'

        for mat in matieres:
            # Notes mensuelles
            notes_m = NoteMensuelle.objects.filter(eleve=eleve, matiere=mat, annee_scolaire=annee)
            mois_dict = {n.mois: n for n in notes_m}
            notes_par_mois = []
            total_notes = 0
            count_notes = 0
            for m in MOIS_ORDRE:
                n = mois_dict.get(m)
                if n:
                    if n.absent:
                        notes_par_mois.append('ABS')
                    elif n.note is not None:
                        notes_par_mois.append(str(n.note))
                        total_notes += float(n.note)
                        count_notes += 1
                    else:
                        notes_par_mois.append('—')
                else:
                    notes_par_mois.append('—')

            # Compositions
            compos = CompositionNote.objects.filter(
                eleve=eleve, matiere=mat, annee_scolaire=annee
            ).order_by('periode')
            compo_dict = {c.periode: ('ABS' if c.absent else str(c.note or '—')) for c in compos}
            notes_compo = [compo_dict.get(p[0], '—') for p in compo_periodes]

            moyenne_matiere = round(total_notes / count_notes, 2) if count_notes > 0 else None
            if annual_system:
                moyenne_centrale = calculer_moyenne_annuelle_matiere(eleve, mat, annual_system).get('moyenne_annuelle')
                if moyenne_centrale is not None:
                    moyenne_matiere = moyenne_centrale

            matieres_data.append({
                'nom': mat.nom,
                'coefficient': mat.coefficient,
                'notes_mensuelles': notes_par_mois,
                'notes_compo': notes_compo,
                'moyenne': moyenne_matiere,
            })

    # ─── Classements ───
    classements = _classements_courants(eleve, classe_note, annee)

    # ─── Forces et faiblesses (déduit des notes) ───
    forces = []
    faiblesses = []
    for md in matieres_data:
        if md['moyenne'] is not None:
            if md['moyenne'] >= 14:
                forces.append({'matiere': md['nom'], 'moyenne': md['moyenne']})
            elif md['moyenne'] < 10:
                faiblesses.append({'matiere': md['nom'], 'moyenne': md['moyenne']})
    forces.sort(key=lambda x: x['moyenne'], reverse=True)
    faiblesses.sort(key=lambda x: x['moyenne'])

    # ─── Conseils personnalisés ───
    conseils = []
    if faiblesses:
        for f in faiblesses[:3]:
            conseils.append(f"Renforcer les efforts en {f['matiere']} (moyenne actuelle : {f['moyenne']}/20)")
    if forces:
        conseils.append(f"Continuer les excellents résultats en {forces[0]['matiere']}")
    if not forces and not faiblesses:
        conseils.append("Continuer les efforts pour maintenir un bon niveau général")

    # Moyenne générale
    moyenne_generale = None
    if classe_note and matieres and 'annual_system' in locals() and annual_system:
        moyenne_generale = calculer_moyenne_generale_annuelle(eleve, matieres_qs, annual_system).get('moyenne_generale')
    if moyenne_generale is None:
        moyennes_valides = [md['moyenne'] for md in matieres_data if md['moyenne'] is not None]
        moyenne_generale = round(sum(moyennes_valides) / len(moyennes_valides), 2) if moyennes_valides else None

    # ─── Activités journalières ───
    activites = ActiviteJournaliere.objects.filter(
        eleve=eleve
    ).select_related('classe').prefetch_related('pieces_jointes').order_by('-date')[:50]

    # Les parents voient les passages à l'infirmerie du seul enfant vérifié.
    visites_sante = VisiteMedicale.objects.filter(
        eleve=eleve,
    ).order_by('-date_visite')[:30]

    # Proposer uniquement les bulletins pour lesquels des données existent.
    periodes_codes = set()
    if classe_note:
        periodes_codes.update(
            NoteMensuelle.objects.filter(
                eleve=eleve,
                matiere__classe=classe_note,
                annee_scolaire=annee,
            ).filter(Q(note__isnull=False) | Q(absent=True)).values_list('mois', flat=True)
        )
        periodes_codes.update(
            CompositionNote.objects.filter(
                eleve=eleve,
                matiere__classe=classe_note,
                annee_scolaire=annee,
            ).filter(Q(note__isnull=False) | Q(absent=True)).values_list('periode', flat=True)
        )
        periodes_codes.update(
            AppreciationMaternelle.objects.filter(
                eleve=eleve,
                matiere__classe=classe_note,
                annee_scolaire=annee,
            ).values_list('trimestre', flat=True)
        )
        periodes_codes.update(
            BulletinMaternelle.objects.filter(
                eleve=eleve,
                classe=classe_note,
                annee_scolaire=annee,
            ).values_list('trimestre', flat=True)
        )

    labels_periodes = dict(
        list(NoteMensuelle.MOIS_CHOICES)
        + list(CompositionNote.PERIODE_CHOICES)
        + list(BulletinMaternelle.TRIMESTRE_CHOICES)
    )
    ordre_periodes = {
        'OCTOBRE': 1, 'NOVEMBRE': 2, 'DECEMBRE': 3,
        'TRIMESTRE_1': 4, 'SEMESTRE_1': 5,
        'JANVIER': 6, 'FEVRIER': 7, 'MARS': 8,
        'TRIMESTRE_2': 9, 'AVRIL': 10, 'MAI': 11, 'JUIN': 12,
        'TRIMESTRE_3': 13, 'SEMESTRE_2': 14,
        'PERIODE_1': 21, 'PERIODE_2': 22, 'PERIODE_3': 23,
        'PERIODE_4': 24, 'PERIODE_5': 25,
    }
    bulletins_disponibles = [
        {'code': code, 'label': labels_periodes.get(code, code.replace('_', ' ').title())}
        for code in sorted(periodes_codes, key=lambda value: ordre_periodes.get(value, 999))
    ]

    return {
        'eleve': eleve,
        'ecole': ecole,
        'annee': annee,
        'classe_note': classe_note,
        'mois_labels': MOIS_LABELS,
        'compo_periodes': compo_periodes,
        'matieres_data': matieres_data,
        'classements': classements,
        'forces': forces,
        'faiblesses': faiblesses,
        'conseils': conseils,
        'moyenne_generale': moyenne_generale,
        'activites': activites,
        'visites_sante': visites_sante,
        'bulletins_disponibles': bulletins_disponibles,
    }


# ────────────────────────────────────────────────────────────────
# VUE : Formulaire de recherche (public, pas de login_required)
# ────────────────────────────────────────────────────────────────

def rapport_scolaire_recherche(request):
    """Affiche le formulaire de recherche et traite la soumission."""
    erreur = None
    eleve = None

    if request.method == 'POST':
        matricule = request.POST.get('matricule', '').strip().upper()
        telephone = request.POST.get('telephone', '').strip()
        classe_id = request.POST.get('classe', '').strip()

        if not matricule or not telephone or not classe_id:
            erreur = "Veuillez remplir tous les champs."
        else:
            # Normaliser le téléphone : accepter avec ou sans +224
            tel_normalise = re.sub(r'[\s\-\.]', '', telephone)
            if not tel_normalise.startswith('+'):
                tel_normalise = '+224' + tel_normalise.lstrip('0')

            # Chercher l'élève
            try:
                eleve = Eleve.objects.select_related(
                    'classe', 'classe__ecole',
                    'responsable_principal', 'responsable_secondaire'
                ).get(matricule=matricule, statut='ACTIF')
            except Eleve.DoesNotExist:
                erreur = "Aucun élève actif trouvé avec ce matricule."

            if eleve and not erreur:
                # Vérifier la classe (par ID ou par nom)
                try:
                    cid = int(classe_id)
                    if eleve.classe_id != cid:
                        erreur = "La classe ne correspond pas à cet élève."
                except (ValueError, TypeError):
                    if classe_id.lower() not in eleve.classe.nom.lower():
                        erreur = "La classe ne correspond pas à cet élève."

                # Vérifier le téléphone du responsable
                if not erreur:
                    tel_match = False
                    for resp in [eleve.responsable_principal, eleve.responsable_secondaire]:
                        if resp and resp.telephone:
                            resp_tel = re.sub(r'[\s\-\.]', '', resp.telephone)
                            if not resp_tel.startswith('+'):
                                resp_tel = '+224' + resp_tel.lstrip('0')
                            if resp_tel == tel_normalise:
                                tel_match = True
                                break
                    if not tel_match:
                        erreur = "Le numéro de téléphone ne correspond à aucun responsable de cet élève."

        if eleve and not erreur:
            # Tout est valide — rediriger vers la page détail
            token = _make_token(eleve.pk)
            return redirect(f'/rapport-scolaire/detail/?token={token}')

    # GET ou erreur — PAS de liste de classes (sécurité : ne pas exposer les écoles/classes)
    return render(request, 'rapport_scolaire/recherche.html', {
        'erreur': erreur,
    })


# ────────────────────────────────────────────────────────────────
# VUE AJAX : Charger les classes après validation matricule+téléphone
# ────────────────────────────────────────────────────────────────

@require_POST
def rapport_scolaire_classes_ajax(request):
    """Retourne la liste des classes pour un élève après validation du matricule et téléphone."""
    import json
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Requête invalide.'}, status=400)

    matricule = (data.get('matricule') or '').strip().upper()
    telephone = (data.get('telephone') or '').strip()

    if not matricule or not telephone:
        return JsonResponse({'error': 'Matricule et téléphone requis.'}, status=400)

    # Normaliser le téléphone
    tel_normalise = re.sub(r'[\s\-\.]', '', telephone)
    if not tel_normalise.startswith('+'):
        tel_normalise = '+224' + tel_normalise.lstrip('0')

    # Chercher l'élève
    try:
        eleve = Eleve.objects.select_related(
            'classe', 'classe__ecole',
            'responsable_principal', 'responsable_secondaire'
        ).get(matricule=matricule, statut='ACTIF')
    except Eleve.DoesNotExist:
        return JsonResponse({'error': 'Aucun élève actif trouvé avec ce matricule.'}, status=404)

    # Vérifier le téléphone du responsable
    tel_match = False
    for resp in [eleve.responsable_principal, eleve.responsable_secondaire]:
        if resp and resp.telephone:
            resp_tel = re.sub(r'[\s\-\.]', '', resp.telephone)
            if not resp_tel.startswith('+'):
                resp_tel = '+224' + resp_tel.lstrip('0')
            if resp_tel == tel_normalise:
                tel_match = True
                break

    if not tel_match:
        return JsonResponse({'error': 'Le numéro de téléphone ne correspond pas.'}, status=403)

    # Retourner uniquement la classe de cet élève (pas toute la base)
    classe = eleve.classe
    return JsonResponse({
        'classes': [{
            'id': classe.id,
            'nom': classe.nom,
            'ecole': classe.ecole.nom if classe.ecole else '',
        }]
    })


# ────────────────────────────────────────────────────────────────
# VUE : Page détail complète (public, sécurisé par token signé)
# ────────────────────────────────────────────────────────────────

def rapport_scolaire_detail(request):
    """Affiche le rapport scolaire complet en HTML pour les parents."""
    token = request.GET.get('token', '')
    eleve_id = _verify_token(token)
    if not eleve_id:
        return render(request, 'rapport_scolaire/recherche.html', {
            'erreur': "Lien expiré ou invalide. Veuillez relancer la recherche.",
        })

    try:
        eleve = Eleve.objects.select_related(
            'classe', 'classe__ecole',
            'responsable_principal', 'responsable_secondaire'
        ).get(pk=eleve_id, statut='ACTIF')
    except Eleve.DoesNotExist:
        raise Http404

    donnees = _collecter_donnees_scolaires(eleve)
    donnees['token'] = token

    # Chaque lien de bulletin est signé pour l'élève, sa classe et sa période.
    from .bulletin_public import generer_token_bulletin
    for bulletin in donnees['bulletins_disponibles']:
        bulletin_token = generer_token_bulletin(
            eleve.pk,
            donnees['classe_note'].pk,
            bulletin['code'],
        )
        bulletin['url'] = reverse(
            'notes:bulletin_public_pdf',
            args=[eleve.pk, donnees['classe_note'].pk, bulletin['code']],
        ) + '?' + urlencode({'token': bulletin_token})

    # ─── Paiements validés de l'élève ───
    paiements = Paiement.objects.filter(
        eleve=eleve, statut='VALIDE'
    ).select_related('type_paiement', 'mode_paiement').order_by('-date_paiement')
    donnees['paiements'] = paiements
    donnees['carnet_disponible'] = paiements.exists()

    # ─── Situation financière (échéancier) ───
    try:
        ech = eleve.echeancier
    except EcheancierPaiement.DoesNotExist:
        ech = None
    if ech:
        donnees['echeancier'] = {
            'total_du': ech.total_du,
            'total_paye': ech.total_paye,
            'solde_restant': ech.solde_restant,
            'pourcentage_paye': ech.pourcentage_paye,
        }
    else:
        donnees['echeancier'] = None

    return render(request, 'rapport_scolaire/detail.html', donnees)


# ────────────────────────────────────────────────────────────────
# VUE : Téléchargement PDF (public, sécurisé par token signé)
# ────────────────────────────────────────────────────────────────

def rapport_scolaire_pdf(request):
    """Télécharge le rapport scolaire en PDF."""
    token = request.GET.get('token', '')
    eleve_id = _verify_token(token)
    if not eleve_id:
        return render(request, 'rapport_scolaire/recherche.html', {
            'erreur': "Lien expiré ou invalide. Veuillez relancer la recherche.",
        })

    try:
        eleve = Eleve.objects.select_related(
            'classe', 'classe__ecole',
            'responsable_principal', 'responsable_secondaire'
        ).get(pk=eleve_id, statut='ACTIF')
    except Eleve.DoesNotExist:
        raise Http404

    return _generer_rapport_pdf(eleve)


# ────────────────────────────────────────────────────────────────
# VUE : Téléchargement d'un reçu de paiement (public, token signé)
# ────────────────────────────────────────────────────────────────

def rapport_scolaire_recu_pdf(request, paiement_id):
    """Télécharge le reçu PDF d'un paiement, sécurisé par le token rapport-scolaire."""
    token = request.GET.get('token', '')
    eleve_id = _verify_token(token)
    if not eleve_id:
        return render(request, 'rapport_scolaire/recherche.html', {
            'erreur': "Lien expiré ou invalide. Veuillez relancer la recherche.",
        })

    # Vérifier que le paiement appartient bien à cet élève
    try:
        paiement = Paiement.objects.select_related(
            'eleve', 'type_paiement', 'mode_paiement',
            'eleve__classe', 'eleve__classe__ecole'
        ).get(pk=paiement_id, eleve_id=eleve_id, statut='VALIDE')
    except Paiement.DoesNotExist:
        raise Http404

    return _generer_recu_paiement_pdf(paiement)


def rapport_scolaire_carnet_pdf(request):
    """Télécharge le carnet du seul élève autorisé par le jeton parent."""
    token = request.GET.get('token', '')
    eleve_id = _verify_token(token)
    if not eleve_id:
        return render(request, 'rapport_scolaire/recherche.html', {
            'erreur': "Lien expiré ou invalide. Veuillez relancer la recherche.",
        })

    eleve = Eleve.objects.select_related('classe', 'classe__ecole').filter(
        pk=eleve_id,
        statut='ACTIF',
    ).first()
    if not eleve:
        raise Http404

    paiements = Paiement.objects.filter(
        eleve=eleve,
        statut='VALIDE',
    ).select_related(
        'eleve', 'eleve__classe', 'eleve__classe__ecole',
        'ecole_encaissement', 'classe_encaissement',
    ).order_by('-date_paiement', '-date_creation')

    paiement = paiements.filter(
        annee_scolaire=eleve.classe.annee_scolaire,
        ecole_encaissement=eleve.classe.ecole,
    ).first() or paiements.first()
    if not paiement:
        raise Http404("Aucun paiement validé pour cet élève.")

    from paiements.carnet_paiement import _generer_carnet_paiement_pdf
    return _generer_carnet_paiement_pdf(paiement)


def _generer_recu_paiement_pdf(paiement):
    """Génère le reçu PDF pour un paiement (version publique rapport-scolaire)."""
    from django.db.models import Sum

    buf = io.BytesIO()
    width, height = A4
    c = canvas.Canvas(buf, pagesize=A4)
    ecole_obj = paiement.eleve.classe.ecole if paiement.eleve.classe else None
    palette = get_school_palette(ecole_obj)

    # Filigrane
    try:
        draw_logo_watermark(c, width, height, ecole=ecole_obj)
    except Exception:
        pass

    left = 40
    top = height - 40
    line_h = 18

    # ── En-tête ──
    c.setFillColor(colors.HexColor(palette['primary']))
    c.setFont('Helvetica-Bold', 18)
    c.drawString(left, top, "REÇU DE PAIEMENT")
    top -= 25
    c.setFillColor(colors.HexColor(palette['text']))
    if ecole_obj:
        c.setFont('Helvetica-Bold', 12)
        c.drawString(left, top, ecole_obj.nom)
        top -= 15
        c.setFont('Helvetica', 9)
        if getattr(ecole_obj, 'telephone', None):
            c.drawString(left, top, f"Tél: {ecole_obj.telephone}")
            top -= 12
        if getattr(ecole_obj, 'email', None):
            c.drawString(left, top, f"Email: {ecole_obj.email}")
            top -= 12
    top -= 20

    # ── Informations du reçu ──
    c.setFont('Helvetica-Bold', 11)
    c.drawString(left, top, f"Numéro de reçu: {paiement.numero_recu or 'N/A'}")
    top -= line_h
    c.drawString(left, top, f"Date: {paiement.date_paiement.strftime('%d/%m/%Y')}")
    top -= line_h * 2

    # ── Informations élève ──
    c.setFont('Helvetica-Bold', 12)
    c.drawString(left, top, "ÉLÈVE")
    top -= line_h
    c.setFont('Helvetica', 11)
    c.drawString(left, top, f"Nom: {paiement.eleve.prenom or ''} {paiement.eleve.nom or ''}")
    top -= line_h
    c.drawString(left, top, f"Matricule: {paiement.eleve.matricule or 'N/A'}")
    top -= line_h
    if paiement.eleve.classe:
        c.drawString(left, top, f"Classe: {paiement.eleve.classe.nom}")
        top -= line_h
    top -= line_h

    # ── Détails du paiement ──
    remises_total = paiement.remises.aggregate(total=Sum('montant_remise')).get('total') or 0
    montant_net = paiement.montant - remises_total if remises_total > 0 else paiement.montant

    c.setFont('Helvetica-Bold', 12)
    c.drawString(left, top, "DÉTAILS DU PAIEMENT")
    top -= line_h
    c.setFont('Helvetica', 11)
    c.drawString(left, top, f"Type: {paiement.type_paiement.nom if paiement.type_paiement else 'N/A'}")
    top -= line_h
    c.drawString(left, top, f"Mode: {paiement.mode_paiement.nom if paiement.mode_paiement else 'N/A'}")
    top -= line_h
    c.drawString(left, top, f"Montant: {paiement.montant:,.0f} GNF".replace(",", " "))
    top -= line_h

    if remises_total > 0:
        c.drawString(left, top, f"Remises: -{remises_total:,.0f} GNF".replace(",", " "))
        top -= line_h
        c.setFont('Helvetica-Bold', 11)
        c.drawString(left, top, f"Net payé: {montant_net:,.0f} GNF".replace(",", " "))
        c.setFont('Helvetica', 11)
        top -= line_h

    top -= 10

    # ── Situation financière ──
    try:
        ech = paiement.eleve.echeancier
        total_du = ech.total_du
        total_paye = ech.total_paye
        solde_restant = ech.solde_restant
    except EcheancierPaiement.DoesNotExist:
        total_du = total_paye = solde_restant = Decimal('0')

    if total_du > 0:
        c.setFont('Helvetica-Bold', 12)
        c.drawString(left, top, "SITUATION FINANCIÈRE")
        top -= line_h
        c.setFont('Helvetica', 11)
        c.drawString(left, top, f"Total frais de scolarité: {total_du:,.0f} GNF".replace(",", " "))
        top -= line_h
        c.drawString(left, top, f"Total déjà payé: {total_paye:,.0f} GNF".replace(",", " "))
        top -= line_h
        c.setFont('Helvetica-Bold', 11)
        if solde_restant > 0:
            c.setFillColor(colors.HexColor(palette['danger']))
            c.drawString(left, top, f"Reste à payer: {solde_restant:,.0f} GNF".replace(",", " "))
            c.setFillColor(colors.HexColor(palette['text']))
        else:
            c.setFillColor(colors.HexColor(palette['success']))
            c.drawString(left, top, "Scolarité entièrement payée")
            c.setFillColor(colors.HexColor(palette['text']))
        top -= line_h

    top -= 10
    c.setFont('Helvetica-Bold', 11)
    c.drawString(left, top, f"Statut: {paiement.get_statut_display()}")

    c.showPage()
    c.save()

    buf.seek(0)
    response = HttpResponse(buf.getvalue(), content_type='application/pdf')
    filename = f"recu_{paiement.numero_recu}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ────────────────────────────────────────────────────────────────
# GÉNÉRATION PDF COMPLÈTE
# ────────────────────────────────────────────────────────────────

def _generer_rapport_pdf(eleve):
    """Génère le PDF complet du rapport scolaire pour un élève."""
    buf = io.BytesIO()
    width, height = A4
    c = canvas.Canvas(buf, pagesize=A4)
    margin = 1.5 * cm
    col_width = width - 2 * margin

    ecole = eleve.classe.ecole if eleve.classe else None
    palette = get_school_palette(ecole)
    annee = eleve.classe.annee_scolaire if eleve.classe else ''

    # ── Filigrane ─────────────────────────────────────────────
    _watermark = lambda pdf_canvas, w, h: draw_logo_watermark(
        pdf_canvas, w, h, rotate=30, scale=1.5, ecole=ecole
    )

    def new_page():
        c.showPage()
        _watermark(c, width, height)
        return height - margin

    _watermark(c, width, height)
    y = height - margin

    # ══════════════════════════════════════════════════════════
    # PAGE 1 : EN-TÊTE + INFORMATIONS ÉLÈVE
    # ══════════════════════════════════════════════════════════
    y = _draw_report_header(c, ecole, eleve, annee, y, margin, width, palette)

    # ── Informations de l'élève ──
    y -= 15
    y = _draw_section_title(c, "INFORMATIONS DE L'ÉLÈVE", y, margin, col_width, palette)
    y -= 5

    infos = [
        ("Matricule", eleve.matricule),
        ("Nom complet", f"{eleve.prenom} {eleve.nom}"),
        ("Sexe", eleve.get_sexe_display()),
        ("Date de naissance", eleve.date_naissance.strftime('%d/%m/%Y') if eleve.date_naissance else '—'),
        ("Lieu de naissance", eleve.lieu_naissance or '—'),
        ("Classe", eleve.classe.nom if eleve.classe else '—'),
        ("Statut", eleve.get_statut_display()),
    ]
    # Responsables
    for label, resp in [("Responsable principal", eleve.responsable_principal),
                        ("Responsable secondaire", eleve.responsable_secondaire)]:
        if resp:
            infos.append((label, f"{resp.nom_complet} ({resp.get_relation_display()}) — Tél: {resp.telephone}"))

    for label, val in infos:
        if y < margin + 30:
            y = new_page()
        c.setFont('Helvetica-Bold', 9)
        c.drawString(margin, y, f"{label} :")
        c.setFont('Helvetica', 9)
        c.drawString(margin + 140, y, str(val))
        y -= 14

    # ══════════════════════════════════════════════════════════
    # SECTION NOTES – notes mensuelles & compositions
    # ══════════════════════════════════════════════════════════
    y -= 10
    if y < margin + 60:
        y = new_page()
    y = _draw_section_title(c, "NOTES ET RÉSULTATS SCOLAIRES", y, margin, col_width, palette)
    y -= 5

    # Trouver la ClasseNote correspondante
    classe_note = ClasseNote.objects.filter(
        nom=eleve.classe.nom,
        ecole=eleve.classe.ecole,
        annee_scolaire=annee,
        actif=True,
    ).first()

    if classe_note:
        matieres = MatiereNote.objects.filter(classe=classe_note, actif=True).order_by('nom')
        if matieres.exists():
            y = _draw_notes_table(c, eleve, classe_note, matieres, y, margin, col_width, new_page, palette)
        else:
            c.setFont('Helvetica-Oblique', 9)
            c.drawString(margin, y, "Aucune matière configurée pour cette classe.")
            y -= 14
    else:
        c.setFont('Helvetica-Oblique', 9)
        c.drawString(margin, y, "Aucune donnée de notes trouvée pour cette classe.")
        y -= 14

    # ── Classements courants ──
    classements = _classements_courants(eleve, classe_note, annee)
    if classements:
        y -= 10
        if y < margin + 60:
            y = new_page()
        y = _draw_section_title(c, "CLASSEMENTS", y, margin, col_width, palette)
        y -= 5
        y = _draw_classements(c, classements, y, margin, col_width, new_page, palette)

    # ══════════════════════════════════════════════════════════
    # SECTION SANTÉ / INFIRMERIE
    # ══════════════════════════════════════════════════════════
    visites_sante = VisiteMedicale.objects.filter(
        eleve=eleve,
    ).order_by('-date_visite')[:20]

    if visites_sante.exists():
        y -= 10
        if y < margin + 60:
            y = new_page()
        y = _draw_section_title(c, "SUIVI DE SANTÉ — INFIRMERIE", y, margin, col_width, palette)
        y -= 5
        y = _draw_visites_sante(c, visites_sante, y, margin, col_width, new_page, palette)

    # ══════════════════════════════════════════════════════════
    # SECTION ACTIVITÉS JOURNALIÈRES
    # ══════════════════════════════════════════════════════════
    activites = ActiviteJournaliere.objects.filter(
        eleve=eleve
    ).select_related('classe').prefetch_related('pieces_jointes').order_by('-date')[:50]

    if activites.exists():
        y -= 10
        if y < margin + 60:
            y = new_page()
        y = _draw_section_title(c, "ACTIVITÉS JOURNALIÈRES", y, margin, col_width, palette)
        y -= 5
        y = _draw_activites(c, activites, y, margin, col_width, new_page, palette)

    # ══════════════════════════════════════════════════════════
    # PIED DE PAGE
    # ══════════════════════════════════════════════════════════
    y -= 20
    if y < margin + 40:
        y = new_page()
    c.setFont('Helvetica-Oblique', 7)
    c.setFillColor(colors.grey)
    c.drawString(margin, margin, f"Rapport généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')} — MySchoolGN")
    c.setFillColor(colors.black)

    c.save()
    buf.seek(0)

    response = HttpResponse(buf, content_type='application/pdf')
    filename = f"rapport_scolaire_{eleve.nom}_{eleve.prenom}_{annee}.pdf"
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    return response


# ────────────────────────────────────────────────────────────────
# FONCTIONS UTILITAIRES PDF
# ────────────────────────────────────────────────────────────────

def _draw_report_header(c, ecole, eleve, annee, y, margin, page_width, palette):
    """En-tête officiel du rapport."""
    center = page_width / 2

    # Ligne République
    c.setFont('Helvetica-Bold', 14)
    c.drawCentredString(center, y, "République de Guinée")
    y -= 13
    c.setFont('Helvetica-Oblique', 9)
    c.drawCentredString(center, y, "Travail - Justice - Solidarité")
    y -= 18

    # Nom de l'école
    if ecole:
        c.setFont('Helvetica-Bold', 13)
        c.drawCentredString(center, y, ecole.nom.upper())
        y -= 14
        if ecole.adresse:
            c.setFont('Helvetica', 8)
            c.drawCentredString(center, y, ecole.adresse)
            y -= 11
        if ecole.telephone:
            c.setFont('Helvetica', 8)
            c.drawCentredString(center, y, f"Tél: {ecole.telephone}")
            y -= 11

    # Logo
    if ecole and hasattr(ecole, 'logo') and ecole.logo:
        try:
            logo_path = ecole.logo.path
            if os.path.exists(logo_path):
                img = Image.open(logo_path)
                aspect = img.width / img.height
                logo_h = 50
                logo_w = logo_h * aspect
                c.drawImage(ImageReader(logo_path), margin, y, width=logo_w, height=logo_h,
                            preserveAspectRatio=True, mask='auto')
        except Exception:
            pass

    # Titre du document
    y -= 10
    c.setFillColor(colors.HexColor(palette['primary']))
    c.setFont('Helvetica-Bold', 16)
    c.drawCentredString(center, y, "RAPPORT SCOLAIRE COMPLET")
    y -= 14
    c.setFont('Helvetica', 10)
    c.drawCentredString(center, y, f"Année scolaire : {annee}")
    c.setFillColor(colors.black)
    y -= 6

    # Ligne séparatrice
    c.setStrokeColor(colors.HexColor(palette['primary']))
    c.setLineWidth(1.5)
    c.line(margin, y, page_width - margin, y)
    y -= 6
    return y


def _draw_section_title(c, title, y, margin, col_width, palette):
    """Dessine un titre de section avec fond coloré."""
    c.setFillColor(colors.HexColor(palette['primary']))
    c.roundRect(margin, y - 4, col_width, 18, 3, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 10)
    c.drawString(margin + 8, y, title)
    c.setFillColor(colors.black)
    return y - 20


def _draw_notes_table(c, eleve, classe_note, matieres, y, margin, col_width, new_page, palette):
    """Dessine le tableau des notes mensuelles et compositions."""

    # Collecter les données
    MOIS = ['OCTOBRE', 'NOVEMBRE', 'DECEMBRE', 'JANVIER', 'FEVRIER', 'MARS', 'AVRIL', 'MAI', 'JUIN']
    MOIS_COURT = ['Oct', 'Nov', 'Déc', 'Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin']

    annee = classe_note.annee_scolaire

    rows_data = []
    for mat in matieres:
        row = {'matiere': mat.nom, 'coeff': str(mat.coefficient or ''), 'mois': [], 'compo': []}

        # Notes mensuelles
        notes_m = NoteMensuelle.objects.filter(
            eleve=eleve, matiere=mat, annee_scolaire=annee
        )
        mois_dict = {n.mois: n for n in notes_m}
        for m in MOIS:
            note_obj = mois_dict.get(m)
            if note_obj:
                row['mois'].append('ABS' if note_obj.absent else (str(note_obj.note) if note_obj.note is not None else '—'))
            else:
                row['mois'].append('—')

        # Compositions
        compos = CompositionNote.objects.filter(
            eleve=eleve, matiere=mat, annee_scolaire=annee
        ).order_by('periode')
        for comp in compos:
            row['compo'].append((comp.get_periode_display(), 'ABS' if comp.absent else str(comp.note or '—')))

        rows_data.append(row)

    if not rows_data:
        c.setFont('Helvetica-Oblique', 9)
        c.drawString(margin, y, "Aucune note enregistrée.")
        return y - 14

    # Dessiner un tableau compact
    # En-tête
    header = ['Matière', 'Coeff'] + MOIS_COURT
    # Trouver les périodes de compo qui existent
    compo_periodes = set()
    for rd in rows_data:
        for p, _ in rd['compo']:
            compo_periodes.add(p)
    compo_periodes = sorted(compo_periodes)
    header += [p[:6] for p in compo_periodes]  # Trim to 6 chars

    num_cols = len(header)
    # Calculer largeurs de colonnes
    mat_w = 90
    coeff_w = 30
    note_w = (col_width - mat_w - coeff_w) / max((num_cols - 2), 1)
    col_widths = [mat_w, coeff_w] + [note_w] * (num_cols - 2)

    data = [header]
    for rd in rows_data:
        row_vals = [rd['matiere'][:18], rd['coeff']] + rd['mois']
        # Ajouter les compos dans l'ordre des périodes
        compo_dict = dict(rd['compo'])
        for p in compo_periodes:
            row_vals.append(compo_dict.get(p, '—'))
        data.append(row_vals)

    # Vérifier l'espace disponible
    table_height = len(data) * 14 + 10
    if y - table_height < margin:
        y = new_page()

    # Créer table ReportLab
    table = Table(data, colWidths=col_widths, repeatRows=1)
    style = TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 6.5),
        ('FONTSIZE', (0, 0), (-1, 0), 7),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(palette['primary'])),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor(palette['light'])]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ])
    table.setStyle(style)

    tw, th = table.wrap(col_width, 0)
    if y - th < margin:
        y = new_page()
    table.drawOn(c, margin, y - th)
    y -= th + 5

    return y


def _draw_classements(c, classements, y, margin, col_width, new_page, palette):
    """Dessine le tableau des classements."""
    header = ['Période', 'Moyenne', 'Rang', 'Mention', 'Appréciation']
    data = [header]
    for cl in classements:
        data.append([
            cl.periode.replace('_', ' '),
            str(cl.moyenne_generale),
            cl.rang_formate,
            cl.mention or '—',
            (cl.appreciation or '—')[:40],
        ])

    col_widths = [100, 60, 70, 80, col_width - 310]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(palette['primary'])),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (4, 1), (4, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor(palette['light'])]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))

    tw, th = table.wrap(col_width, 0)
    if y - th < margin:
        y = new_page()
    table.drawOn(c, margin, y - th)
    return y - th - 5


def _draw_activites(c, activites, y, margin, col_width, new_page, palette):
    """Dessine le tableau des activités journalières."""
    TYPE_COLORS = {
        'EVALUATION': colors.HexColor(palette['primary']),
        'SPORTIVE': colors.HexColor(palette['success']),
        'CULTURELLE': colors.HexColor(palette['warning']),
        'ARTISTIQUE': colors.HexColor(palette['accent']),
        'SORTIE': colors.HexColor(palette['secondary']),
        'AUTRE': colors.HexColor(palette['text']),
    }

    header = ['Date', 'Type', 'Titre', 'Appréciation', 'PJ']
    data = [header]
    type_cells = []  # (row, type) pour coloriser

    for i, act in enumerate(activites):
        pj_count = act.pieces_jointes.count()
        data.append([
            act.date.strftime('%d/%m/%Y'),
            act.get_type_activite_display(),
            act.titre[:35],
            act.appreciation[:25] if act.appreciation else '—',
            str(pj_count) if pj_count else '—',
        ])
        type_cells.append((i + 1, act.type_activite))

    col_widths = [65, 75, col_width - 260, 80, 40]
    table = Table(data, colWidths=col_widths, repeatRows=1)

    base_style = [
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(palette['secondary'])),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (2, 1), (2, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor(palette['light'])]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]

    # Coloriser les cellules "Type" par type d'activité
    for row_idx, type_act in type_cells:
        color = TYPE_COLORS.get(type_act, colors.grey)
        base_style.append(('TEXTCOLOR', (1, row_idx), (1, row_idx), color))

    table.setStyle(TableStyle(base_style))

    tw, th = table.wrap(col_width, 0)
    if y - th < margin:
        y = new_page()
    table.drawOn(c, margin, y - th)
    return y - th - 5


def _draw_visites_sante(c, visites, y, margin, col_width, new_page, palette):
    """Dessine l'historique récent de santé dans le rapport PDF parent."""
    cell_style = ParagraphStyle(
        'SanteCellule', fontName='Helvetica', fontSize=6.5, leading=8,
        textColor=colors.black,
    )
    data = [['Date / heure', 'Motif', 'Temp.', 'Suite donnée', 'Soins / observation']]
    for visite in visites:
        details = visite.soins or visite.observations or visite.symptomes or '—'
        details = ' '.join(str(details).split())[:180]
        data.append([
            timezone.localtime(visite.date_visite).strftime('%d/%m/%Y %H:%M'),
            Paragraph(escape(visite.motif), cell_style),
            f"{visite.temperature} °C" if visite.temperature is not None else '—',
            Paragraph(escape(visite.get_statut_display()), cell_style),
            Paragraph(escape(details), cell_style),
        ])

    col_widths = [82, 92, 42, 100, col_width - 316]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(palette['danger'])),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor(palette['light'])]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    _, height = table.wrap(col_width, 0)
    if y - height < margin:
        y = new_page()
    table.drawOn(c, margin, y - height)
    return y - height - 5
