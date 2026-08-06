"""
Fonctions utilitaires pour le module Rapports
"""
from datetime import datetime, date, timedelta
from decimal import Decimal
from django.db.models import Sum, Count, Q
from django.utils import timezone as django_timezone
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

from eleves.models import Eleve, Ecole
from paiements.models import Paiement, EcheancierPaiement, PaiementRemise, RemiseReduction
from paiements.views import _is_reinscription_type
from depenses.models import Depense
from salaires.models import Enseignant, EtatSalaire
from utilisateurs.utils import user_is_admin, user_is_superadmin, user_school
from django.contrib.staticfiles import finders
from django.conf import settings


def _remises_par_categorie(paiements_qs):
    """Agrège les remises appliquées sur `paiements_qs` par motif du catalogue.

    Retourne une liste ordonnée de dicts {motif, libelle, total}, motifs sans
    remise omis, prête à afficher en PDF/Excel.
    """
    motif_labels = dict(RemiseReduction.MOTIF_CHOICES)
    rows = (
        PaiementRemise.objects
        .filter(paiement__in=paiements_qs)
        .values('remise__motif')
        .annotate(total=Sum('montant_remise'))
        .order_by('-total')
    )
    resultat = []
    for row in rows:
        motif = row['remise__motif'] or 'AUTRE'
        total = row['total'] or Decimal('0')
        if total:
            resultat.append({
                'motif': motif,
                'libelle': motif_labels.get(motif, motif),
                'total': total,
            })
    return resultat


def _get_logo_path(ecole=None):
    """Retourne le chemin absolu du logo.

    Priorité au logo d'école si fourni, sinon fallback staticfiles.
    """
    # Priorité au logo d'école si disponible
    try:
        if ecole and getattr(ecole, 'logo', None) and hasattr(ecole.logo, 'path'):
            import os
            if os.path.exists(ecole.logo.path):
                return ecole.logo.path
    except Exception:
        pass
    # Fallback: staticfiles
    candidate = 'logos/logo.png'
    path = finders.find(candidate)
    return path or ''


def _draw_header_and_watermark(c, doc, ecole=None, titre_override=None):
    """Dessine l'entête (logo + titre) et un filigrane logo géant sur chaque page.

    - Filigrane: logo agrandi (~500% largeur) centré, faible opacité si disponible
    - Entête: logo à gauche + nom de l'établissement
    """
    width, height = A4
    logo_path = _get_logo_path(ecole)

    c.saveState()
    try:
        # Filigrane
        if logo_path:
            # Taille ~500%: on couvre 1.5x la largeur de page (grand watermark)
            wm_width = width * 1.5
            wm_height = wm_width  # carré approximatif, preserveAspectRatio activera le ratio réel
            wm_x = (width - wm_width) / 2
            wm_y = (height - wm_height) / 2

            # Opacité visible mais discrète (comme dans les reçus de paiement)
            try:
                c.setFillAlpha(0.15)
            except Exception:
                # Certaines versions de reportlab ne supportent pas l'alpha, on continue sans transparence
                pass

            # Légère rotation pour l'effet filigrane
            c.translate(width / 2.0, height / 2.0)
            c.rotate(30)
            c.translate(-width / 2.0, -height / 2.0)

            c.drawImage(
                logo_path,
                wm_x,
                wm_y,
                width=wm_width,
                height=wm_height,
                preserveAspectRatio=True,
                mask='auto'
            )
    finally:
        # Restaurer l'état avant de dessiner l'entête
        c.restoreState()

    # Entête (après restauration, pas d'opacité)
    c.saveState()
    try:
        margin_x = 40
        margin_y = 30
        if logo_path:
            c.drawImage(logo_path, margin_x, height - margin_y - 30, width=60, height=30, preserveAspectRatio=True, mask='auto')

        # Titre à droite du logo avec taille réduite
        c.setFillColor(colors.HexColor('#0d47a1'))
        c.setFont('Helvetica-Bold', 12)
        school_name = (getattr(ecole, 'nom', None) or "").strip() or "Rapport"
        # Si un titre explicite est fourni par l'appelant, l'afficher à droite
        header_text = school_name
        if titre_override:
            header_text = f"{school_name} — {titre_override}" if school_name else titre_override
        c.drawString(margin_x + 70, height - margin_y - 10, header_text)

        # Ligne de séparation
        c.setStrokeColor(colors.HexColor('#0d47a1'))
        c.setLineWidth(0.7)
        c.line(margin_x, height - margin_y - 38, width - margin_x, height - margin_y - 38)
    finally:
        c.restoreState()

def collecter_donnees_periode(debut, fin, type_periode, user=None):
    """Collecte les données pour une période donnée"""
    donnees = {
        'debut': debut,
        'fin': fin,
        'type': type_periode,
        'ecoles': {},
        # Dépenses non reliées à l'école: on les calcule une seule fois au niveau global
        'depenses_globales': {
            'nombre': 0,
            'montant_total': Decimal('0')
        }
    }

    # Restreindre le périmètre des écoles selon l'utilisateur
    # IMPORTANT: Seul le superuser peut voir toutes les écoles
    ecoles_qs = Ecole.objects.all()
    if user is not None and not user_is_superadmin(user):
        ecole_user = user_school(user)
        ecoles_qs = ecoles_qs.filter(id=getattr(ecole_user, 'id', None)) if ecole_user else Ecole.objects.none()

    # Dépenses de la période (GLOBAL - pas de relation à Ecole)
    depenses_periode_global = Depense.objects.filter(
        date_facture__range=[debut, fin]
    ).exclude(statut='ANNULEE')  # Exclure seulement les annulées
    
    # Si pas de dépenses dans la période, essayer avec toutes les dépenses validées
    if not depenses_periode_global.exists():
        depenses_periode_global = Depense.objects.filter(
            statut='VALIDEE'
        )
    
    donnees['depenses_globales']['nombre'] = depenses_periode_global.count()
    donnees['depenses_globales']['montant_total'] = depenses_periode_global.aggregate(
        total=Sum('montant_ttc')
    )['total'] or Decimal('0')

    for ecole in ecoles_qs:
        # Normalisation nom école (SONFONIA)
        _nom_affiche = ecole.nom
        _nom_upper = (ecole.nom or '').upper()
        if any(key in _nom_upper for key in ['SONFONIA', 'SONFONIE']):
            _nom_affiche = "GROUPE SCOLAIRE myschool-SONFONIA"

        donnees_ecole = {
            'nom': _nom_affiche,
            'nouveaux_eleves': Eleve.objects.filter(
                classe__ecole=ecole,
                date_inscription__range=[debut, fin]
            ).count(),
            'paiements': {
                'nombre': 0,
                'montant_total': Decimal('0'),
                'frais_inscription': Decimal('0'),
                'reinscription': Decimal('0'),
                'scolarite': Decimal('0'),
                # Ajouts pour alignement journalier
                'montant_original': Decimal('0'),
                'total_remises': Decimal('0'),
                'total_du_concernes': Decimal('0'),
                'reste_a_payer': Decimal('0'),
            },
            'remises_par_categorie': [],
            'classes': [],
            # Dépenses affichées par école mises à 0 pour éviter toute confusion,
            # car le modèle Depense n'est pas lié à Ecole
            'depenses': {
                'nombre': 0,
                'montant_total': Decimal('0')
            },
            'salaires': {
                'etats_valides': 0,
                'montant_total': Decimal('0')
            }
        }
        
        # Paiements de la période (liaison via Eleve -> Classe -> École)
        paiements_periode = Paiement.objects.filter(
            eleve__classe__ecole=ecole,
            date_paiement__range=[debut, fin]
        ).exclude(statut='ANNULE')

        # Si pas de paiements dans la période, fallback: tous les paiements validés de l'école
        if not paiements_periode.exists():
            paiements_periode = Paiement.objects.filter(
                eleve__classe__ecole=ecole,
                statut='VALIDE'
            )

        donnees_ecole['paiements']['nombre'] = paiements_periode.count()
        montant_total_paiements = paiements_periode.aggregate(total=Sum('montant'))['total'] or Decimal('0')
        # Total des remises sur la période
        total_remises = PaiementRemise.objects.filter(paiement__in=paiements_periode).aggregate(total=Sum('montant_remise'))['total'] or Decimal('0')
        donnees_ecole['paiements']['montant_total'] = montant_total_paiements
        donnees_ecole['paiements']['total_remises'] = total_remises
        donnees_ecole['paiements']['montant_original'] = montant_total_paiements + total_remises

        # Classification sans double comptage
        frais_inscription = Decimal('0')
        reinscription = Decimal('0')
        scolarite = Decimal('0')
        non_categorises = Decimal('0')

        for p in paiements_periode.select_related('type_paiement'):
            montant = p.montant or Decimal('0')
            type_nom = getattr(getattr(p, 'type_paiement', None), 'nom', '') or ''
            nom = type_nom.lower()

            has_reinscription = _is_reinscription_type(type_nom)
            has_inscription = (not has_reinscription) and ('inscription' in nom)
            has_scolarite = ('scolar' in nom) or ('tranche' in nom) or ('1ère tranche' in nom) or ('2ème tranche' in nom) or ('3ème tranche' in nom)

            if has_reinscription and has_scolarite:
                # Paiement combiné: 30 000 GNF pour réinscription, reste en scolarité
                part_reinsc = min(Decimal('30000'), montant)
                reinscription += part_reinsc
                scolarite += montant - part_reinsc
            elif has_reinscription:
                reinscription += montant
            elif has_inscription and has_scolarite:
                # Paiement combiné: 30 000 GNF pour inscription, reste en scolarité
                part_ins = min(Decimal('30000'), montant)
                part_sco = montant - part_ins
                frais_inscription += part_ins
                scolarite += part_sco
            elif has_inscription:
                # Pur frais d'inscription
                frais_inscription += montant
            elif has_scolarite:
                scolarite += montant
            else:
                non_categorises += montant

        # Estimation/fallback: couvrir les frais d'inscription théoriques avec non catégorisés si besoin
        nb_nouveaux = donnees_ecole['nouveaux_eleves']
        theorique_insc = Decimal('30000') * nb_nouveaux

        if frais_inscription == 0 and nb_nouveaux > 0 and non_categorises > 0:
            a_affecter = min(theorique_insc, non_categorises)
            frais_inscription += a_affecter
            non_categorises -= a_affecter

        # Plafond: ne jamais dépasser 30 000 GNF par nouvel élève
        if nb_nouveaux > 0 and frais_inscription > theorique_insc:
            excedent = frais_inscription - theorique_insc
            frais_inscription = theorique_insc
            scolarite += excedent

        # Cohérence: si 0 nouveaux élèves, ne pas compter des frais d'inscription → reclasser en scolarité
        if nb_nouveaux == 0 and frais_inscription > 0:
            scolarite += frais_inscription
            frais_inscription = Decimal('0')

        # Ajouter le reste non catégorisé à la scolarité (par défaut)
        scolarite += non_categorises

        donnees_ecole['paiements']['frais_inscription'] = frais_inscription
        donnees_ecole['paiements']['reinscription'] = reinscription
        donnees_ecole['paiements']['scolarite'] = scolarite
        donnees_ecole['remises_par_categorie'] = _remises_par_categorie(paiements_periode)

        # Élèves concernés de la période (paiements dans période + inscriptions dans période)
        eleves_concernes_ids = set(paiements_periode.values_list('eleve_id', flat=True).distinct())
        inscrits_ids = set(
            Eleve.objects.filter(
                classe__ecole=ecole,
                date_inscription__range=[debut, fin]
            ).values_list('id', flat=True)
        )
        eleves_concernes_ids |= inscrits_ids

        # Déterminer la/les années scolaires couvertes par la période (pivot: août)
        def annee_scolaire_for(d):
            return f"{d.year}-{d.year + 1}" if d.month >= 8 else f"{d.year - 1}-{d.year}"
        annees_couvertes = {annee_scolaire_for(debut), annee_scolaire_for(fin)}

        # Calculs Total dû (Scolarité normale) et Reste à payer + répartition par classe
        total_du_concernes = Decimal('0')
        reste_a_payer = Decimal('0')
        classes_map = {}
        # Pré-calcul des remises par classe sur la période (basé sur les paiements de la période)
        remises_par_classe_map = {}
        try:
            remises_group = PaiementRemise.objects.filter(
                paiement__in=paiements_periode
            ).values(
                'paiement__eleve__classe_id'
            ).annotate(
                total=Sum('montant_remise')
            )
            remises_par_classe_map = {row['paiement__eleve__classe_id']: (row['total'] or Decimal('0')) for row in remises_group}
        except Exception:
            remises_par_classe_map = {}
        if eleves_concernes_ids:
            qs_ech = EcheancierPaiement.objects.filter(
                eleve_id__in=list(eleves_concernes_ids),
                annee_scolaire__in=list(annees_couvertes)
            ).values(
                'eleve__classe_id', 'eleve__classe__nom',
                'frais_inscription_du', 'tranche_1_due', 'tranche_2_due', 'tranche_3_due',
                'frais_inscription_paye', 'tranche_1_payee', 'tranche_2_payee', 'tranche_3_payee'
            )
            for row in qs_ech:
                classe_id = row.get('eleve__classe_id')
                classe_nom = row.get('eleve__classe__nom') or 'Classe'
                du = (row.get('frais_inscription_du') or Decimal('0')) \
                     + (row.get('tranche_1_due') or Decimal('0')) \
                     + (row.get('tranche_2_due') or Decimal('0')) \
                     + (row.get('tranche_3_due') or Decimal('0'))
                paye = (row.get('frais_inscription_paye') or Decimal('0')) \
                       + (row.get('tranche_1_payee') or Decimal('0')) \
                       + (row.get('tranche_2_payee') or Decimal('0')) \
                       + (row.get('tranche_3_payee') or Decimal('0'))
                solde = du - paye

                total_du_concernes += du
                if solde > 0:
                    reste_a_payer += solde

                if classe_id not in classes_map:
                    classes_map[classe_id] = {
                        'classe': classe_nom,
                        'effectif': 0,
                        'total_du': Decimal('0'),
                        'total_paye': Decimal('0'),
                        'reste': Decimal('0'),
                        'remises': Decimal('0'),
                    }
                cm = classes_map[classe_id]
                cm['effectif'] += 1
                cm['total_du'] += du
                cm['total_paye'] += paye
                if solde > 0:
                    cm['reste'] += solde
                # Injecter remises agrégées pour cette classe
                try:
                    cm['remises'] = remises_par_classe_map.get(classe_id, cm['remises'])
                except Exception:
                    pass

        donnees_ecole['paiements']['total_du_concernes'] = total_du_concernes
        donnees_ecole['paiements']['reste_a_payer'] = reste_a_payer
        donnees_ecole['classes'] = sorted(classes_map.values(), key=lambda x: x['classe'])
        
        # Dépenses: pas de répartition par école (le modèle n'est pas rattaché à Ecole)
        # On laisse 0 au niveau de l'école et on affiche un total global dans le résumé
        
        # États de salaire de la période
        etats_periode = EtatSalaire.objects.filter(
            enseignant__ecole=ecole,
            date_validation__range=[debut, fin],
            valide=True
        )
        
        # Si pas d'états dans la période, essayer avec tous les états validés de l'école
        if not etats_periode.exists():
            etats_periode = EtatSalaire.objects.filter(
                enseignant__ecole=ecole,
                valide=True
            )
        
        donnees_ecole['salaires']['etats_valides'] = etats_periode.count()
        donnees_ecole['salaires']['montant_total'] = etats_periode.aggregate(
            total=Sum('salaire_net')
        )['total'] or Decimal('0')
        
        donnees['ecoles'][ecole.id] = donnees_ecole
    
    return donnees

def generer_pdf_periode(donnees, debut, fin, type_periode, ecole=None):
    """Génère le PDF pour un rapport de période"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []
    
    # Titre
    titre_style = ParagraphStyle(
        'TitreRapport',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.darkblue,
        alignment=1
    )
    
    titre = f"RAPPORT {type_periode.upper()} - {debut.strftime('%d/%m/%Y')} au {fin.strftime('%d/%m/%Y')}"
    story.append(Paragraph(titre, titre_style))
    story.append(Spacer(1, 20))
    
    # Pour chaque école
    for ecole_id, donnees_ecole in donnees['ecoles'].items():
        story.append(Paragraph(f"École: {donnees_ecole['nom']}", styles['Heading2']))
        story.append(Spacer(1, 10))
        
        # Tableau des données (aligné avec le journalier)
        data = [
            ['Indicateur', 'Valeur'],
            ['Nouveaux élèves inscrits', str(donnees_ecole['nouveaux_eleves'])],
            ['Nombre de paiements', str(donnees_ecole['paiements']['nombre'])],
            ['Scolarité normale', f"{donnees_ecole['paiements'].get('total_du_concernes', Decimal('0')):,} GNF".replace(',', ' ')],
            ['Scolarité payé', f"{donnees_ecole['paiements']['scolarite']:,} GNF".replace(',', ' ')],
            ['Frais d\'inscription', f"{donnees_ecole['paiements']['frais_inscription']:,} GNF".replace(',', ' ')],
            ['Réinscription', f"{donnees_ecole['paiements'].get('reinscription', Decimal('0')):,} GNF".replace(',', ' ')],
            ['Reste à payer', f"{donnees_ecole['paiements'].get('reste_a_payer', Decimal('0')):,} GNF".replace(',', ' ')],
            ['Montant original (avant remises)', f"{donnees_ecole['paiements']['montant_original']:,} GNF".replace(',', ' ')],
            ['Total des remises accordées', f"{donnees_ecole['paiements']['total_remises']:,} GNF".replace(',', ' ')],
            ['Montant net encaissé', f"{donnees_ecole['paiements']['montant_total']:,} GNF".replace(',', ' ')],
            ['Nombre de dépenses', str(donnees_ecole['depenses']['nombre'])],
            ['Montant total des dépenses', f"{donnees_ecole['depenses']['montant_total']:,} GNF".replace(',', ' ')],
            ['États de salaire validés', str(donnees_ecole['salaires']['etats_valides'])],
            ['Montant total des salaires', f"{donnees_ecole['salaires']['montant_total']:,} GNF".replace(',', ' ')],
        ]
        
        table = Table(data, colWidths=[3*inch, 2*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(table)
        story.append(Spacer(1, 12))

        # Répartition par classe
        if donnees_ecole.get('classes'):
            story.append(Paragraph("Répartition par classe", styles['Heading3']))
            story.append(Spacer(1, 6))
            class_data = [[
                'Classe', 'Effectif', 'Total dû', 'Total payé', 'Remises', 'Reste à payer'
            ]]
            for c in donnees_ecole['classes']:
                class_data.append([
                    c['classe'],
                    str(c['effectif']),
                    f"{c['total_du']:,} GNF".replace(',', ' '),
                    f"{c['total_paye']:,} GNF".replace(',', ' '),
                    f"{c.get('remises', 0):,} GNF".replace(',', ' '),
                    f"{c['reste']:,} GNF".replace(',', ' '),
                ])

            class_table = Table(class_data, colWidths=[120, 60, 90, 90, 90, 90])
            class_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                ('TEXTCOLOR', (0,0), (-1,0), colors.black),
                ('ALIGN', (1,1), (-1,-1), 'RIGHT'),
                ('ALIGN', (0,0), (0,-1), 'LEFT'),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('BOTTOMPADDING', (0,0), (-1,0), 6),
                ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
            ]))
            story.append(class_table)
            story.append(Spacer(1, 16))

        # Remises par catégorie (motif du catalogue de remises)
        if donnees_ecole.get('remises_par_categorie'):
            story.append(Paragraph("Remises par catégorie", styles['Heading3']))
            story.append(Spacer(1, 6))
            remise_data = [['Catégorie', 'Total remisé']]
            for r in donnees_ecole['remises_par_categorie']:
                remise_data.append([r['libelle'], f"{r['total']:,} GNF".replace(',', ' ')])
            remise_table = Table(remise_data, colWidths=[200, 150])
            remise_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                ('TEXTCOLOR', (0,0), (-1,0), colors.black),
                ('ALIGN', (1,1), (-1,-1), 'RIGHT'),
                ('ALIGN', (0,0), (0,-1), 'LEFT'),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('BOTTOMPADDING', (0,0), (-1,0), 6),
                ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
            ]))
            story.append(remise_table)
            story.append(Spacer(1, 16))

    # Section Dépenses globales (non rattachées à une école)
    story.append(Paragraph("DÉPENSES GLOBALES (période)", styles['Heading2']))
    story.append(Spacer(1, 8))
    dep_global = donnees.get('depenses_globales', {'nombre': 0, 'montant_total': Decimal('0')})
    depenses_data = [
        ['Nombre de dépenses', str(dep_global.get('nombre', 0))],
        ['Montant total des dépenses', f"{dep_global.get('montant_total', Decimal('0')):,} GNF".replace(',', ' ')]
    ]
    dep_table = Table(depenses_data, colWidths=[3*inch, 2*inch])
    dep_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    story.append(dep_table)
    story.append(Spacer(1, 16))

    # Résumé global
    total_paiements = sum(d['paiements']['montant_total'] for d in donnees['ecoles'].values())
    total_depenses = donnees['depenses_globales']['montant_total']
    total_salaires = sum(d['salaires']['montant_total'] for d in donnees['ecoles'].values())
    
    story.append(Paragraph("RÉSUMÉ GLOBAL", styles['Heading2']))
    story.append(Spacer(1, 10))
    
    resume_data = [
        ['Total des paiements', f"{total_paiements:,} GNF".replace(',', ' ')],
        ['Total des dépenses', f"{total_depenses:,} GNF".replace(',', ' ')],
        ['Total des salaires', f"{total_salaires:,} GNF".replace(',', ' ')],
        ['Solde net', f"{total_paiements - total_depenses - total_salaires:,} GNF".replace(',', ' ')],
    ]
    
    resume_table = Table(resume_data, colWidths=[3*inch, 2*inch])
    resume_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.lightblue),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    story.append(resume_table)
    
    # Ajout entête + filigrane sur toutes les pages
    # Injecter un wrapper pour passer ecole et un titre
    def _header_wrapper(canvas, doc_):
        _draw_header_and_watermark(canvas, doc_, ecole=ecole, titre_override=f"Rapport {type_periode.title()}")
    doc.build(story, onFirstPage=_header_wrapper, onLaterPages=_header_wrapper)
    buffer.seek(0)
    return buffer
