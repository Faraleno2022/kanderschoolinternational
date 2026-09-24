"""Documents de paie repris du classeur Excel de l'école.

- État de salaire à payer par catégorie (Direction, Primaire, Secondaire...)
- Masse salariale mensuelle
- Relevé des acomptes (bons) du mois
- Fiche d'émargement des salaires (« Acquis »)
- Bulletins de paie de toute une période
"""

from collections import OrderedDict
from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ecole_moderne.security_decorators import require_school_object

from .models import (
    AvanceSalaire,
    CategoriePaie,
    EtatSalaire,
    PeriodeSalaire,
    RUBRIQUES_PRIMES,
    TYPES_PAR_CATEGORIE_PAIE,
)
from .services import nombre_jours_presence


MOIS_NOMS = [
    '', 'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin', 'Juillet',
    'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre',
]
NOMBRE_BONS = 5


# ---------------------------------------------------------------------------
# Montant en lettres
# ---------------------------------------------------------------------------

_UNITES = [
    'zéro', 'un', 'deux', 'trois', 'quatre', 'cinq', 'six', 'sept', 'huit',
    'neuf', 'dix', 'onze', 'douze', 'treize', 'quatorze', 'quinze', 'seize',
    'dix-sept', 'dix-huit', 'dix-neuf',
]
_DIZAINES = {
    2: 'vingt', 3: 'trente', 4: 'quarante', 5: 'cinquante', 6: 'soixante',
}


def _moins_de_cent(n):
    if n < 20:
        return _UNITES[n]
    dizaine, unite = divmod(n, 10)
    if dizaine in (7, 9):
        base = 'soixante' if dizaine == 7 else 'quatre-vingt'
        reste = 10 + unite
        liaison = '-et-' if dizaine == 7 and unite == 1 else '-'
        return f"{base}{liaison}{_UNITES[reste]}"
    if dizaine == 8:
        return 'quatre-vingts' if unite == 0 else f"quatre-vingt-{_UNITES[unite]}"
    base = _DIZAINES[dizaine]
    if unite == 0:
        return base
    if unite == 1:
        return f"{base}-et-un"
    return f"{base}-{_UNITES[unite]}"


def _moins_de_mille(n):
    centaines, reste = divmod(n, 100)
    mots = []
    if centaines:
        if centaines == 1:
            mots.append('cent')
        else:
            mots.append(
                f"{_UNITES[centaines]} cent{'s' if reste == 0 else ''}"
            )
    if reste:
        mots.append(_moins_de_cent(reste))
    return ' '.join(mots)


def nombre_en_lettres(nombre):
    """Écrit un entier positif en toutes lettres (orthographe traditionnelle)."""
    n = int(Decimal(nombre or 0).to_integral_value())
    if n == 0:
        return 'zéro'
    if n < 0:
        return 'moins ' + nombre_en_lettres(-n)

    mots = []
    for valeur, singulier, pluriel in (
        (10 ** 9, 'milliard', 'milliards'),
        (10 ** 6, 'million', 'millions'),
    ):
        quotient, n = divmod(n, valeur)
        if quotient:
            texte = _moins_de_mille(quotient) if quotient < 1000 else nombre_en_lettres(quotient)
            mots.append(f"{texte} {singulier if quotient == 1 else pluriel}")
    milliers, n = divmod(n, 1000)
    if milliers:
        texte = _moins_de_mille(milliers)
        # « quatre-vingts » et « cents » perdent leur s devant « mille ».
        if texte.endswith('vingts') or texte.endswith('cents'):
            texte = texte[:-1]
        mots.append('mille' if milliers == 1 else f"{texte} mille")
    if n:
        mots.append(_moins_de_mille(n))
    return ' '.join(mots)


def montant_en_lettres(montant):
    texte = nombre_en_lettres(montant)
    return f"{texte[0].upper()}{texte[1:]} francs guinéens"


def fmt(valeur):
    """Formate un montant GNF avec un espace comme séparateur de milliers."""
    if valeur is None or valeur == '':
        return ''
    valeur = Decimal(valeur)
    if valeur == 0:
        return '-'
    return f"{valeur:,.0f}".replace(',', ' ')


def _heures(valeur):
    """Affiche 40 plutôt que 40.00 et 12,5 pour une demi-heure."""
    valeur = Decimal(valeur or 0).quantize(Decimal('0.01'))
    texte = f"{valeur:f}".rstrip('0').rstrip('.')
    return texte.replace('.', ',')


# ---------------------------------------------------------------------------
# Données
# ---------------------------------------------------------------------------

def _categorie_demandee(request):
    code = request.GET.get('categorie', '')
    if code and code not in CategoriePaie.values:
        raise Http404("Catégorie inconnue")
    return code or None


def etats_de_la_periode(periode, categorie=None):
    etats = (
        EtatSalaire.objects
        .filter(periode=periode)
        .select_related('enseignant', 'periode', 'periode__ecole')
        .order_by('enseignant__nom', 'enseignant__prenoms')
    )
    if categorie:
        etats = etats.filter(
            enseignant__type_enseignant__in=TYPES_PAR_CATEGORIE_PAIE[categorie]
        )
    return etats


def _fonction(etat):
    enseignant = etat.enseignant
    if enseignant.fonction:
        return enseignant.fonction
    if enseignant.est_affectable_classe:
        matieres = sorted({
            affectation.matiere or affectation.classe.nom
            for affectation in enseignant.affectations.filter(actif=True).select_related('classe')
        })
        if matieres:
            return ' / '.join(matieres)
    return enseignant.get_type_enseignant_display()


def _jours(etat):
    if etat.jours_travailles is not None:
        return etat.jours_travailles
    return nombre_jours_presence(etat.enseignant, etat.periode)


def synthese_masse_salariale(periode):
    """Totaux par catégorie : effectif, brut, acompte, retenues, net."""
    lignes = []
    for categorie in CategoriePaie:
        etats = list(etats_de_la_periode(periode, categorie))
        if not etats:
            continue
        lignes.append({
            'categorie': categorie,
            'libelle': categorie.label,
            'effectif': len(etats),
            'brut': sum((e.salaire_brut for e in etats), Decimal('0')),
            'acompte': sum((e.montant_avances for e in etats), Decimal('0')),
            'retenues': sum((e.deductions for e in etats), Decimal('0')),
            'net': sum((e.salaire_net for e in etats), Decimal('0')),
        })
    total = {
        cle: sum((ligne[cle] for ligne in lignes), Decimal('0'))
        for cle in ('brut', 'acompte', 'retenues', 'net')
    }
    total['effectif'] = sum(ligne['effectif'] for ligne in lignes)
    return lignes, total


# ---------------------------------------------------------------------------
# Mise en page commune
# ---------------------------------------------------------------------------

def _styles():
    styles = getSampleStyleSheet()
    return {
        'titre': ParagraphStyle(
            'titre', parent=styles['Title'], fontSize=13, spaceAfter=2,
        ),
        'centre': ParagraphStyle(
            'centre', parent=styles['Normal'], alignment=TA_CENTER, fontSize=9,
        ),
        'normal': ParagraphStyle('normal', parent=styles['Normal'], fontSize=9),
        'petit': ParagraphStyle('petit', parent=styles['Normal'], fontSize=7, leading=8),
        'entete': ParagraphStyle(
            'entete', parent=styles['Normal'], fontName='Helvetica-Bold',
            fontSize=7, leading=8, alignment=TA_CENTER,
        ),
    }


def _envelopper_entetes(data, nb_lignes):
    """Permet aux intitulés de colonnes de passer à la ligne."""
    style = _styles()['entete']
    for ligne in data[:nb_lignes]:
        for position, cellule in enumerate(ligne):
            if isinstance(cellule, str) and cellule:
                ligne[position] = Paragraph(cellule, style)
    return data


def _entete(periode, titre, sous_titre=None):
    """Bloc d'en-tête : école à gauche, République de Guinée à droite."""
    st = _styles()
    ecole = periode.ecole
    coordonnees = [f"<b>{ecole.nom}</b>"]
    if ecole.adresse:
        coordonnees.append(ecole.adresse)
    telephones = ' / '.join(
        t for t in (ecole.telephone, getattr(ecole, 'telephone2', ''), getattr(ecole, 'telephone3', '')) if t
    )
    if telephones:
        coordonnees.append(f"Tél : {telephones}")
    annee_debut = periode.annee if periode.mois >= 9 else periode.annee - 1
    droite = [
        '<b>RÉPUBLIQUE DE GUINÉE</b>',
        'Travail - Justice - Solidarité',
        f"Année scolaire : {annee_debut} - {annee_debut + 1}",
    ]
    entete = Table(
        [[
            Paragraph('<br/>'.join(coordonnees), st['normal']),
            Paragraph('<br/>'.join(droite), st['centre']),
        ]],
        colWidths=['60%', '40%'],
    )
    entete.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    elements = [entete, Spacer(1, 0.3 * cm), Paragraph(titre, st['titre'])]
    if sous_titre:
        elements.append(Paragraph(sous_titre, st['centre']))
    elements.append(
        Paragraph(f"Mois de : <b>{MOIS_NOMS[periode.mois]} {periode.annee}</b>", st['centre'])
    )
    elements.append(Spacer(1, 0.3 * cm))
    return elements


def _pied(periode, libelle, montant, signataires=None):
    st = _styles()
    ecole = periode.ecole
    elements = [Spacer(1, 0.4 * cm)]
    if montant is not None:
        elements.append(Paragraph(
            f"Arrêté {libelle} du mois de {MOIS_NOMS[periode.mois]} {periode.annee} "
            f"à la somme de : <b>{montant_en_lettres(montant)} ({fmt(montant)} GNF)</b>.",
            st['normal'],
        ))
    lieu = (ecole.adresse or '').split(',')[0].strip() or ecole.nom
    elements.append(Spacer(1, 0.2 * cm))
    elements.append(Paragraph(f"{lieu}, le {date.today().strftime('%d/%m/%Y')}", st['normal']))
    elements.append(Spacer(1, 0.4 * cm))
    signataires = signataires or [
        ('Le Fondateur', ''),
        ('Le Directeur', ecole.directeur or ''),
        ('Le Comptable / Gestionnaire', ''),
    ]
    signatures = Table(
        [[Paragraph(f"<b>{titre}</b>", st['centre']) for titre, _nom in signataires],
         [''] * len(signataires),
         [Paragraph(nom, st['centre']) for _titre, nom in signataires]],
        rowHeights=[None, 1.4 * cm, None],
    )
    elements.append(signatures)
    return elements


def _style_tableau(nb_lignes_entete=1, ligne_total=True):
    commandes = [
        ('GRID', (0, 0), (-1, -1), 0.4, colors.black),
        ('BACKGROUND', (0, 0), (-1, nb_lignes_entete - 1), colors.HexColor('#d9e2f3')),
        ('FONTNAME', (0, 0), (-1, nb_lignes_entete - 1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, nb_lignes_entete - 1), 'CENTER'),
    ]
    if ligne_total:
        commandes += [
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#eeeeee')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ]
    return TableStyle(commandes)


def _reponse_pdf(nom_fichier):
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{nom_fichier}"'
    return response


def _nom_fichier(prefixe, periode, categorie=None):
    suffixe = f"_{categorie.lower()}" if categorie else ''
    return f"{prefixe}{suffixe}_{periode.mois:02d}_{periode.annee}.pdf"


# ---------------------------------------------------------------------------
# Vues
# ---------------------------------------------------------------------------

@login_required
@require_school_object(model=PeriodeSalaire, pk_kwarg='periode_id', field_path='ecole')
def masse_salariale(request, periode_id):
    periode = get_object_or_404(PeriodeSalaire.objects.select_related('ecole'), id=periode_id)
    lignes, total = synthese_masse_salariale(periode)
    return render(request, 'salaires/masse_salariale.html', {
        'periode': periode,
        'lignes': lignes,
        'total': total,
        'total_en_lettres': montant_en_lettres(total['brut']) if lignes else '',
        'categories': [(c.value, c.label) for c in CategoriePaie],
    })


@login_required
@require_school_object(model=PeriodeSalaire, pk_kwarg='periode_id', field_path='ecole')
def masse_salariale_pdf(request, periode_id):
    periode = get_object_or_404(PeriodeSalaire.objects.select_related('ecole'), id=periode_id)
    lignes, total = synthese_masse_salariale(periode)
    response = _reponse_pdf(_nom_fichier('masse_salariale', periode))
    doc = SimpleDocTemplate(response, pagesize=A4, leftMargin=1.5 * cm,
                            rightMargin=1.5 * cm, topMargin=1.2 * cm, bottomMargin=1.2 * cm)
    elements = _entete(periode, 'MASSE SALARIALE')
    data = [['N°', 'Catégorie', 'Effectif', 'Montant brut', 'Acompte', 'Retenues', 'Net à payer']]
    for index, ligne in enumerate(lignes, 1):
        data.append([
            index, ligne['libelle'], ligne['effectif'], fmt(ligne['brut']),
            fmt(ligne['acompte']), fmt(ligne['retenues']), fmt(ligne['net']),
        ])
    data.append(['', 'TOTAL', total['effectif'], fmt(total['brut']),
                 fmt(total['acompte']), fmt(total['retenues']), fmt(total['net'])])
    table = Table(data, repeatRows=1, colWidths=[1 * cm, 5 * cm, 1.7 * cm, 2.7 * cm, 2.5 * cm, 2.3 * cm, 2.7 * cm])
    style = _style_tableau()
    style.add('FONTSIZE', (0, 0), (-1, -1), 9)
    style.add('ALIGN', (2, 1), (-1, -1), 'RIGHT')
    table.setStyle(style)
    elements.append(table)
    elements += _pied(periode, 'la présente masse salariale', total['brut'], [
        ('La Fondation', ''), ('Le Chargé des finances', ''),
    ])
    doc.build(elements)
    return response


@login_required
@require_school_object(model=PeriodeSalaire, pk_kwarg='periode_id', field_path='ecole')
def etat_paie_pdf(request, periode_id):
    """État de salaire à payer, au format des feuilles « Direction », « Primaire »
    ou « Etat Prof final » (secondaire payé à l'heure)."""
    periode = get_object_or_404(PeriodeSalaire.objects.select_related('ecole'), id=periode_id)
    categorie = _categorie_demandee(request)
    etats = list(etats_de_la_periode(periode, categorie))
    st = _styles()

    response = _reponse_pdf(_nom_fichier('etat_salaire', periode, categorie))
    doc = SimpleDocTemplate(response, pagesize=landscape(A4), leftMargin=0.8 * cm,
                            rightMargin=0.8 * cm, topMargin=1 * cm, bottomMargin=1 * cm)
    libelle = CategoriePaie(categorie).label if categorie else 'Tout le personnel'
    elements = _entete(periode, 'ÉTAT DE SALAIRE À PAYER', f"Personnel : <b>{libelle}</b>")

    horaire = categorie == CategoriePaie.SECONDAIRE
    if horaire:
        data = [[
            'N°', 'Prénoms et Nom', 'Matri.', 'Charge ou fonction', 'Jours trav.',
            'Heures prestées', 'Taux', 'Valeur des heures', 'Primes',
            'Salaire brut', 'Acompte payé', 'Retenues', 'Net à payer', 'Émarg.',
        ]]
        largeurs = [0.8, 4.6, 1.8, 3.2, 1.3, 1.5, 1.5, 2.2, 1.9, 2.2, 2.0, 1.7, 2.2, 1.7]
        entetes = 1
    else:
        rubriques_courtes = ['Fonct.', 'Craie/ Révision', 'Ancien.', 'Éloign.', 'Perform.', 'Except.', 'Autres']
        data = [
            ['N°', 'Prénoms et Nom', 'Matri.', 'Charge ou fonction', 'Jours trav.',
             'Salaire de base', 'PRIMES'] + [''] * 6 +
            ['Salaire brut', 'Acompte payé', 'Retenues', 'Net à payer', 'Émarg.'],
            [''] * 6 + rubriques_courtes + [''] * 5,
        ]
        largeurs = [0.7, 3.9, 1.6, 2.6, 1.0, 1.8] + [1.35] * 7 + [1.9, 1.8, 1.4, 1.9, 1.3]
        entetes = 2

    totaux = OrderedDict()

    def cumuler(cle, valeur):
        totaux[cle] = totaux.get(cle, Decimal('0')) + (valeur or Decimal('0'))

    for index, etat in enumerate(etats, 1):
        enseignant = etat.enseignant
        nom = Paragraph(f"{enseignant.prenoms} {enseignant.nom}", st['petit'])
        fonction = Paragraph(_fonction(etat), st['petit'])
        if horaire:
            ligne = [
                index, nom, enseignant.matricule, fonction, _jours(etat),
                _heures(etat.total_heures), fmt(etat.taux_horaire_applique),
                fmt(etat.salaire_base), fmt(etat.primes), fmt(etat.salaire_brut),
                fmt(etat.montant_avances), fmt(etat.deductions), fmt(etat.salaire_net), '',
            ]
            cumuler('heures', etat.total_heures)
            cumuler('base', etat.salaire_base)
            cumuler('primes', etat.primes)
        else:
            primes = [montant for _libelle, montant in etat.lignes_primes]
            ligne = [
                index, nom, enseignant.matricule, fonction, _jours(etat), fmt(etat.salaire_base),
                *[fmt(p) for p in primes],
                fmt(etat.salaire_brut), fmt(etat.montant_avances), fmt(etat.deductions),
                fmt(etat.salaire_net), '',
            ]
            cumuler('base', etat.salaire_base)
            for position, montant in enumerate(primes):
                cumuler(f"prime_{position}", montant)
        cumuler('brut', etat.salaire_brut)
        cumuler('acompte', etat.montant_avances)
        cumuler('retenues', etat.deductions)
        cumuler('net', etat.salaire_net)
        data.append(ligne)

    if horaire:
        data.append([
            '', 'TOTAL', '', '', '', _heures(totaux.get('heures')), '',
            fmt(totaux.get('base')), fmt(totaux.get('primes')), fmt(totaux.get('brut')),
            fmt(totaux.get('acompte')), fmt(totaux.get('retenues')), fmt(totaux.get('net')), '',
        ])
    else:
        data.append([
            '', 'TOTAL', '', '', '', fmt(totaux.get('base')),
            *[fmt(totaux.get(f"prime_{i}")) for i in range(len(RUBRIQUES_PRIMES) + 1)],
            fmt(totaux.get('brut')), fmt(totaux.get('acompte')), fmt(totaux.get('retenues')),
            fmt(totaux.get('net')), '',
        ])

    _envelopper_entetes(data, entetes)
    table = Table(data, repeatRows=entetes, colWidths=[l * cm for l in largeurs])
    style = _style_tableau(entetes)
    style.add('ALIGN', (4, entetes), (-2, -1), 'RIGHT')
    if not horaire:
        for colonne in list(range(0, 6)) + list(range(13, 18)):
            style.add('SPAN', (colonne, 0), (colonne, 1))
        style.add('SPAN', (6, 0), (12, 0))
    table.setStyle(style)
    elements.append(table)
    elements += _pied(periode, 'le présent état de salaire', totaux.get('brut', Decimal('0')))
    doc.build(elements)
    return response


@login_required
@require_school_object(model=PeriodeSalaire, pk_kwarg='periode_id', field_path='ecole')
def emargement_pdf(request, periode_id):
    """Fiche d'émargement des salaires pour acquis."""
    periode = get_object_or_404(PeriodeSalaire.objects.select_related('ecole'), id=periode_id)
    categorie = _categorie_demandee(request)
    etats = etats_de_la_periode(periode, categorie)
    st = _styles()

    response = _reponse_pdf(_nom_fichier('emargement', periode, categorie))
    doc = SimpleDocTemplate(response, pagesize=A4, leftMargin=1.2 * cm,
                            rightMargin=1.2 * cm, topMargin=1.2 * cm, bottomMargin=1.2 * cm)
    elements = _entete(periode, "FICHE D'ÉMARGEMENT DES SALAIRES POUR ACQUIS")
    elements += [
        Paragraph(
            "1- En émargeant la présente fiche, vous attestez avoir perçu votre salaire "
            f"du mois que vous doit {periode.ecole.nom}.", st['normal']),
        Paragraph(
            "2- Le bulletin de paie fournit tous les détails relatifs à votre salaire ; "
            "ce bulletin est personnel !", st['normal']),
        Spacer(1, 0.3 * cm),
    ]
    data = [['N°', 'Prénoms et Nom', 'Matri.', 'Site', 'Charge ou fonction', 'Net à payer', 'Émargement', 'Observation']]
    total = Decimal('0')
    for index, etat in enumerate(etats, 1):
        enseignant = etat.enseignant
        data.append([
            index,
            Paragraph(f"{enseignant.prenoms} {enseignant.nom}", st['petit']),
            enseignant.matricule,
            Paragraph(enseignant.categorie_paie.label, st['petit']),
            Paragraph(_fonction(etat), st['petit']),
            fmt(etat.salaire_net), '', '',
        ])
        total += etat.salaire_net
    data.append(['', 'TOTAL', '', '', '', fmt(total), '', ''])
    _envelopper_entetes(data, 1)
    table = Table(data, repeatRows=1, colWidths=[
        0.8 * cm, 4.4 * cm, 1.8 * cm, 2.2 * cm, 3.2 * cm, 2.2 * cm, 2.6 * cm, 1.9 * cm,
    ])
    style = _style_tableau()
    style.add('FONTSIZE', (0, 1), (-1, -1), 8)
    style.add('ALIGN', (5, 1), (5, -1), 'RIGHT')
    style.add('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white])
    style.add('TOPPADDING', (0, 1), (-1, -2), 9)
    style.add('BOTTOMPADDING', (0, 1), (-1, -2), 9)
    table.setStyle(style)
    elements.append(table)
    elements += _pied(periode, '', None)
    doc.build(elements)
    return response


@login_required
@require_school_object(model=PeriodeSalaire, pk_kwarg='periode_id', field_path='ecole')
def acomptes_pdf(request, periode_id):
    """Relevé des acomptes du mois : chaque avance est un « bon »."""
    periode = get_object_or_404(PeriodeSalaire.objects.select_related('ecole'), id=periode_id)
    categorie = _categorie_demandee(request)
    avances = (
        AvanceSalaire.objects
        .filter(periode=periode, statut__in=(
            AvanceSalaire.Statut.APPROUVEE, AvanceSalaire.Statut.DEDUITE,
        ))
        .select_related('enseignant')
        .order_by('enseignant__nom', 'enseignant__prenoms', 'date_avance', 'id')
    )
    if categorie:
        avances = avances.filter(
            enseignant__type_enseignant__in=TYPES_PAR_CATEGORIE_PAIE[categorie]
        )
    par_employe = OrderedDict()
    for avance in avances:
        par_employe.setdefault(avance.enseignant, []).append(avance.montant)

    st = _styles()
    response = _reponse_pdf(_nom_fichier('acomptes', periode, categorie))
    doc = SimpleDocTemplate(response, pagesize=landscape(A4), leftMargin=1 * cm,
                            rightMargin=1 * cm, topMargin=1 * cm, bottomMargin=1 * cm)
    elements = _entete(periode, 'ACOMPTES DU PERSONNEL')
    data = [['N°', 'Prénoms et Nom', 'Matri.', 'Site', 'Charge ou fonction']
            + [f"Bon {i}" for i in range(1, NOMBRE_BONS + 1)]
            + ['Acompte payé', 'Observation']]
    totaux_bons = [Decimal('0')] * NOMBRE_BONS
    total = Decimal('0')
    for index, (enseignant, montants) in enumerate(par_employe.items(), 1):
        # Au-delà de cinq bons, les suivants sont cumulés dans le dernier.
        bons = montants[:NOMBRE_BONS - 1] + [sum(montants[NOMBRE_BONS - 1:], Decimal('0'))] \
            if len(montants) > NOMBRE_BONS else montants
        bons = bons + [Decimal('0')] * (NOMBRE_BONS - len(bons))
        for position, montant in enumerate(bons):
            totaux_bons[position] += montant
        somme = sum(montants, Decimal('0'))
        total += somme
        data.append([
            index,
            Paragraph(f"{enseignant.prenoms} {enseignant.nom}", st['petit']),
            enseignant.matricule,
            Paragraph(enseignant.categorie_paie.label, st['petit']),
            Paragraph(enseignant.fonction or enseignant.get_type_enseignant_display(), st['petit']),
            *[fmt(b) for b in bons],
            fmt(somme),
            f"{len(montants)} bons" if len(montants) > NOMBRE_BONS else '',
        ])
    data.append(['', 'TOTAL', '', '', '', *[fmt(b) for b in totaux_bons], fmt(total), ''])
    _envelopper_entetes(data, 1)
    table = Table(data, repeatRows=1, colWidths=[
        0.8 * cm, 5 * cm, 1.8 * cm, 2.6 * cm, 3.6 * cm,
    ] + [1.9 * cm] * NOMBRE_BONS + [2.4 * cm, 2.3 * cm])
    style = _style_tableau()
    style.add('FONTSIZE', (0, 1), (-1, -1), 8)
    style.add('ALIGN', (5, 1), (-2, -1), 'RIGHT')
    table.setStyle(style)
    elements.append(table)
    elements += _pied(periode, 'le présent état des acomptes', total)
    doc.build(elements)
    return response


def lignes_bulletin(etat):
    """Lignes du bulletin de paie : (n°, rubrique, base, prime, acompte, solde)."""
    lignes = []
    solde = etat.salaire_base or Decimal('0')
    libelle_base = 'Salaire de base'
    if etat.total_heures is not None:
        libelle_base = (
            f"Salaire de base ({_heures(etat.total_heures)} h × "
            f"{fmt(etat.taux_horaire_applique)} GNF)"
        )
    lignes.append([1, libelle_base, fmt(etat.salaire_base), '', '', fmt(solde)])
    numero = 2
    for libelle, montant in etat.lignes_primes:
        if not montant and libelle == 'Autres primes':
            continue
        solde += montant
        lignes.append([numero, libelle, '', fmt(montant), '', fmt(solde)])
        numero += 1
    if etat.deductions:
        solde -= etat.deductions
        lignes.append([numero, 'Retenues (absences, sanctions...)', '', '', fmt(etat.deductions), fmt(solde)])
        numero += 1
    solde -= etat.montant_avances or Decimal('0')
    lignes.append([numero, 'Avance sur salaire et autres prélèvements', '', '',
                   fmt(etat.montant_avances), fmt(solde)])
    return lignes


@login_required
@require_school_object(model=PeriodeSalaire, pk_kwarg='periode_id', field_path='ecole')
def bulletins_periode_pdf(request, periode_id):
    """Tous les bulletins de paie d'une période (une page par employé)."""
    from reportlab.pdfgen import canvas as pdf_canvas
    from .views import dessiner_fiche_paie

    periode = get_object_or_404(PeriodeSalaire.objects.select_related('ecole'), id=periode_id)
    categorie = _categorie_demandee(request)
    etats = list(etats_de_la_periode(periode, categorie))
    if not etats:
        raise Http404("Aucun état de salaire pour cette période.")
    response = _reponse_pdf(_nom_fichier('bulletins_paie', periode, categorie))
    p = pdf_canvas.Canvas(response, pagesize=A4)
    for etat in etats:
        dessiner_fiche_paie(p, etat)
    p.save()
    return response
