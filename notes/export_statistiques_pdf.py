"""
Module d'export PDF des statistiques d'évolution du niveau des élèves
Inclut graphiques, analyses, élèves en difficulté et recommandations
"""
import io
from datetime import datetime
from decimal import Decimal
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY

from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from utilisateurs.permissions import can_manage_notes

# Pour les graphiques
try:
    import matplotlib
    matplotlib.use('Agg')  # Backend non-interactif
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    import numpy as np
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

from .models import ClasseNote, MatiereNote, Evaluation, NoteEleve, NoteMensuelle, CompositionNote
from eleves.models import Eleve, Classe as ClasseEleve


def _get_ecole(request):
    """Récupère l'école de l'utilisateur"""
    from eleves.models import Ecole
    user_profil = getattr(request.user, 'profil', None)
    return user_profil.ecole if user_profil else Ecole.objects.first()


def _calculer_statistiques_classe(classe_note, periode):
    """Calcule les statistiques détaillées d'une classe pour une période"""
    from .calculs_moyennes import detecter_niveau_scolaire
    
    # Récupérer la classe élève correspondante
    classe_eleve = ClasseEleve.objects.filter(
        nom__iexact=classe_note.nom,
        annee_scolaire=classe_note.annee_scolaire,
        ecole=classe_note.ecole
    ).first()
    
    if not classe_eleve:
        # Essayer avec correspondance partielle
        classe_eleve = ClasseEleve.objects.filter(
            nom__icontains=classe_note.nom.split()[0] if classe_note.nom else '',
            annee_scolaire=classe_note.annee_scolaire,
            ecole=classe_note.ecole
        ).first()
    
    if not classe_eleve:
        return None
    
    eleves = Eleve.objects.filter(classe=classe_eleve, statut='ACTIF').order_by('nom', 'prenom')
    matieres = MatiereNote.objects.filter(classe=classe_note, actif=True)
    
    if not eleves.exists() or not matieres.exists():
        return None
    
    # Détecter le niveau scolaire
    niveau = detecter_niveau_scolaire(classe_note.nom)
    est_primaire = (niveau == 'PRIMAIRE')
    note_max = 10 if est_primaire else 20
    seuil_reussite = 5 if est_primaire else 10
    
    # Calculer les moyennes pour chaque élève
    eleves_data = []
    stats_matieres = {}
    
    for matiere in matieres:
        stats_matieres[matiere.id] = {
            'nom': matiere.nom,
            'notes': [],
            'coefficient': 1 if est_primaire else (matiere.coefficient or 1)
        }
    
    for eleve in eleves:
        total_points = Decimal('0')
        total_coefficients = Decimal('0')
        has_any_notes = False  # L'élève a-t-il au moins une note dans une matière?
        notes_par_matiere = {}
        matieres_sans_notes = []  # Pour le suivi des matières sans notes
        
        for matiere in matieres:
            coef = Decimal('1') if est_primaire else (matiere.coefficient or Decimal('1'))
            
            # Périodes mensuelles et mapping trimestres/semestres
            mois_periodes = ['OCTOBRE', 'NOVEMBRE', 'DECEMBRE', 'JANVIER', 'FEVRIER', 'MARS', 'AVRIL', 'MAI', 'JUIN']
            trimestre_mois = {
                'TRIMESTRE_1': ['OCTOBRE', 'NOVEMBRE', 'DECEMBRE'],
                'TRIMESTRE_2': ['JANVIER', 'FEVRIER', 'MARS'],
                'TRIMESTRE_3': ['AVRIL', 'MAI', 'JUIN'],
                'SEMESTRE_1': ['OCTOBRE', 'NOVEMBRE', 'DECEMBRE', 'JANVIER'],
                'SEMESTRE_2': ['FEVRIER', 'MARS', 'AVRIL', 'MAI', 'JUIN'],
            }
            
            notes_matiere = []
            if periode in mois_periodes:
                # Utiliser NoteMensuelle pour les périodes mensuelles
                note_mensuelle = NoteMensuelle.objects.filter(
                    eleve=eleve,
                    matiere=matiere,
                    mois=periode,
                    annee_scolaire=classe_note.annee_scolaire
                ).first()
                if note_mensuelle and note_mensuelle.note is not None and not note_mensuelle.absent:
                    notes_matiere.append(float(note_mensuelle.note))
            elif periode in trimestre_mois:
                # Système guinéen: NoteMensuelle (moyenne continue) + CompositionNote
                mois_list = trimestre_mois[periode]
                notes_mois = NoteMensuelle.objects.filter(
                    eleve=eleve,
                    matiere=matiere,
                    mois__in=mois_list,
                    annee_scolaire=classe_note.annee_scolaire,
                    absent=False,
                    note__isnull=False
                )
                
                moyenne_continue = None
                if notes_mois.exists():
                    total_mois = sum(float(n.note) for n in notes_mois)
                    moyenne_continue = total_mois / notes_mois.count()
                
                note_composition = None
                compo = CompositionNote.objects.filter(
                    eleve=eleve,
                    matiere=matiere,
                    periode=periode,
                    annee_scolaire=classe_note.annee_scolaire,
                    absent=False,
                    note__isnull=False
                ).first()
                if compo:
                    note_composition = float(compo.note)
                
                # Calculer la moyenne de la matière
                moyenne_calc = None
                if moyenne_continue is not None and note_composition is not None:
                    moyenne_calc = (moyenne_continue + note_composition) / 2
                elif note_composition is not None:
                    moyenne_calc = note_composition
                elif moyenne_continue is not None:
                    moyenne_calc = moyenne_continue
                
                if moyenne_calc is not None:
                    notes_matiere.append(moyenne_calc)
            else:
                # Fallback: ancien système Evaluation+NoteEleve
                evaluations = Evaluation.objects.filter(matiere=matiere, periode=periode)
                for evaluation in evaluations:
                    try:
                        note_obj = NoteEleve.objects.get(eleve=eleve, evaluation=evaluation)
                        if note_obj.note is not None and not note_obj.absent:
                            notes_matiere.append(float(note_obj.note))
                    except NoteEleve.DoesNotExist:
                        pass
            
            # RÈGLE PÉDAGOGIQUE: Toutes les matières comptent
            # Si pas de notes dans une matière = 0 (l'élève ne doit pas être favorisé)
            if notes_matiere:
                moyenne_matiere = sum(notes_matiere) / len(notes_matiere)
                has_any_notes = True
                notes_par_matiere[matiere.id] = moyenne_matiere
                stats_matieres[matiere.id]['notes'].append(moyenne_matiere)
            else:
                # Matière sans notes = 0 pour ne pas favoriser l'élève
                moyenne_matiere = 0.0
                matieres_sans_notes.append(matiere.nom)
                notes_par_matiere[matiere.id] = 0.0  # Marquer comme 0
            
            # Toutes les matières comptent dans le calcul
            total_points += Decimal(str(moyenne_matiere)) * coef
            total_coefficients += coef
        
        # Inclure l'élève s'il a au moins une note OU si on veut inclure tous les élèves
        # Pour être équitable, on inclut tous les élèves avec des coefficients > 0
        if total_coefficients > 0:
            moyenne_generale = float(total_points / total_coefficients)
            
            # Classifier l'élève (seuils adaptés: /10 primaire, /20 secondaire)
            if est_primaire:
                if moyenne_generale >= 9:
                    categorie, mention = 'excellent', 'Excellent'
                elif moyenne_generale >= 8:
                    categorie, mention = 'tres_bien', 'Très Bien'
                elif moyenne_generale >= 7:
                    categorie, mention = 'bien', 'Bien'
                elif moyenne_generale >= 6:
                    categorie, mention = 'assez_bien', 'Assez Bien'
                elif moyenne_generale >= 5:
                    categorie, mention = 'passable', 'Passable'
                elif moyenne_generale >= 4:
                    categorie, mention = 'insuffisant', 'Insuffisant'
                elif moyenne_generale >= 3:
                    categorie, mention = 'faible', 'Faible'
                else:
                    categorie, mention = 'tres_faible', 'Très faible'
            else:
                if moyenne_generale >= 18:
                    categorie, mention = 'excellent', 'Excellent'
                elif moyenne_generale >= 16:
                    categorie, mention = 'tres_bien', 'Très Bien'
                elif moyenne_generale >= 14:
                    categorie, mention = 'bien', 'Bien'
                elif moyenne_generale >= 12:
                    categorie, mention = 'assez_bien', 'Assez Bien'
                elif moyenne_generale >= 10:
                    categorie, mention = 'passable', 'Passable'
                elif moyenne_generale >= 8:
                    categorie, mention = 'insuffisant', 'Insuffisant'
                elif moyenne_generale >= 6:
                    categorie, mention = 'faible', 'Faible'
                else:
                    categorie, mention = 'tres_faible', 'Très faible'
            
            eleves_data.append({
                'eleve': eleve,
                'moyenne': round(moyenne_generale, 2),
                'categorie': categorie,
                'mention': mention,
                'notes_matieres': notes_par_matiere,
                'matieres_sans_notes': matieres_sans_notes,  # Liste des matières sans notes
                'nb_matieres_sans_notes': len(matieres_sans_notes)
            })
    
    # Trier par moyenne décroissante
    eleves_data.sort(key=lambda x: x['moyenne'], reverse=True)
    
    # Attribuer les rangs
    for i, data in enumerate(eleves_data):
        data['rang'] = i + 1
    
    # Calculer les statistiques par matière
    stats_matieres_final = []
    for mat_id, stats in stats_matieres.items():
        if stats['notes']:
            stats_matieres_final.append({
                'nom': stats['nom'],
                'moyenne': round(sum(stats['notes']) / len(stats['notes']), 2),
                'max': round(max(stats['notes']), 2),
                'min': round(min(stats['notes']), 2),
                'nb_eleves': len(stats['notes']),
                'coefficient': stats['coefficient']
            })
    
    # Statistiques globales
    if eleves_data:
        moyennes = [e['moyenne'] for e in eleves_data]
        stats_globales = {
            'total_eleves': len(eleves_data),
            'moyenne_classe': round(sum(moyennes) / len(moyennes), 2),
            'moyenne_max': max(moyennes),
            'moyenne_min': min(moyennes),
            'nb_excellent': len([e for e in eleves_data if e['categorie'] == 'excellent']),
            'nb_tres_bien': len([e for e in eleves_data if e['categorie'] == 'tres_bien']),
            'nb_bien': len([e for e in eleves_data if e['categorie'] == 'bien']),
            'nb_assez_bien': len([e for e in eleves_data if e['categorie'] == 'assez_bien']),
            'nb_passable': len([e for e in eleves_data if e['categorie'] == 'passable']),
            'nb_insuffisant': len([e for e in eleves_data if e['categorie'] == 'insuffisant']),
            'nb_faible': len([e for e in eleves_data if e['categorie'] == 'faible']),
            'nb_tres_faible': len([e for e in eleves_data if e['categorie'] == 'tres_faible']),
        }
        nb_echec = stats_globales['nb_insuffisant'] + stats_globales['nb_faible'] + stats_globales['nb_tres_faible']
        stats_globales['taux_reussite'] = round(
            (stats_globales['total_eleves'] - nb_echec) / 
            stats_globales['total_eleves'] * 100, 1
        )
    else:
        stats_globales = None
    
    # Seuils adaptés au niveau
    seuil_suivre = seuil_reussite + (1 if est_primaire else 2)
    seuil_excellent = seuil_reussite + (2 if est_primaire else 4)
    
    return {
        'classe': classe_note,
        'periode': periode,
        'niveau': niveau,
        'est_primaire': est_primaire,
        'note_max': note_max,
        'seuil_reussite': seuil_reussite,
        'eleves_data': eleves_data,
        'stats_matieres': stats_matieres_final,
        'stats_globales': stats_globales,
        'eleves_en_difficulte': [e for e in eleves_data if e['moyenne'] < seuil_reussite],
        'eleves_a_suivre': [e for e in eleves_data if seuil_reussite <= e['moyenne'] < seuil_suivre],
        'eleves_excellents': [e for e in eleves_data if e['moyenne'] >= seuil_excellent],
    }


def _generer_graphique_repartition(stats):
    """Génère un graphique camembert de répartition des notes"""
    if not MATPLOTLIB_AVAILABLE or not stats or not stats.get('stats_globales'):
        return None
    
    fig, ax = plt.subplots(figsize=(6, 4))
    
    est_primaire = stats.get('est_primaire', False)
    if est_primaire:
        labels = ['Excellent\n(≥9)', 'Très Bien\n(≥8)', 'Bien\n(≥7)', 'Assez Bien\n(≥6)', 'Passable\n(≥5)', 'Insuffisant\n(≥4)', 'Faible\n(≥3)', 'Très faible\n(<3)']
    else:
        labels = ['Excellent\n(≥18)', 'Très Bien\n(≥16)', 'Bien\n(≥14)', 'Assez Bien\n(≥12)', 'Passable\n(≥10)', 'Insuffisant\n(≥8)', 'Faible\n(≥6)', 'Très faible\n(<6)']
    sg = stats['stats_globales']
    sizes = [
        sg.get('nb_excellent', 0),
        sg.get('nb_tres_bien', 0),
        sg.get('nb_bien', 0),
        sg.get('nb_assez_bien', 0),
        sg.get('nb_passable', 0),
        sg.get('nb_insuffisant', 0),
        sg.get('nb_faible', 0),
        sg.get('nb_tres_faible', 0)
    ]
    colors_pie = ['#146c43', '#28a745', '#17a2b8', '#ffc107', '#fd7e14', '#dc3545', '#e55353', '#8b0000']
    
    # Filtrer les valeurs nulles
    non_zero = [(l, s, c) for l, s, c in zip(labels, sizes, colors_pie) if s > 0]
    if not non_zero:
        plt.close(fig)
        return None
    
    labels, sizes, colors_pie = zip(*non_zero)
    
    ax.pie(sizes, labels=labels, colors=colors_pie, autopct='%1.1f%%', startangle=90)
    ax.set_title('Répartition des Moyennes', fontsize=12, fontweight='bold')
    
    # Sauvegarder en bytes
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf


def _generer_graphique_matieres(stats):
    """Génère un graphique barres des moyennes par matière"""
    if not MATPLOTLIB_AVAILABLE or not stats or not stats.get('stats_matieres'):
        return None
    
    fig, ax = plt.subplots(figsize=(8, 4))
    
    matieres = [m['nom'][:15] for m in stats['stats_matieres']]
    moyennes = [m['moyenne'] for m in stats['stats_matieres']]
    
    if not matieres:
        plt.close(fig)
        return None
    
    # Adapter au niveau (primaire /10, secondaire /20)
    est_primaire = stats.get('est_primaire', False)
    note_max = stats.get('note_max', 20)
    seuil = stats.get('seuil_reussite', 10)
    seuil_bien = 7 if est_primaire else 14
    
    # Couleurs selon la moyenne
    colors_bar = ['#28a745' if m >= seuil_bien else '#ffc107' if m >= seuil else '#dc3545' for m in moyennes]
    
    bars = ax.bar(matieres, moyennes, color=colors_bar)
    ax.set_ylabel(f'Moyenne /{note_max}')
    ax.set_title('Moyennes par Matière', fontsize=12, fontweight='bold')
    ax.set_ylim(0, note_max)
    ax.axhline(y=seuil, color='red', linestyle='--', alpha=0.5, label='Seuil de réussite')
    
    # Rotation des labels si nécessaire
    if len(matieres) > 5:
        plt.xticks(rotation=45, ha='right')
    
    plt.tight_layout()
    
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf


def _generer_recommandations(stats):
    """Génère des recommandations pédagogiques basées sur les statistiques"""
    note_max = stats.get('note_max', 20) if stats else 20
    seuil = stats.get('seuil_reussite', 10) if stats else 10
    recommandations = []
    
    if not stats or not stats.get('stats_globales'):
        return recommandations
    
    sg = stats['stats_globales']
    eleves_diff = stats.get('eleves_en_difficulte', [])
    eleves_suivre = stats.get('eleves_a_suivre', [])
    stats_matieres = stats.get('stats_matieres', [])
    
    # Analyse globale
    if sg['taux_reussite'] >= 80:
        recommandations.append({
            'type': 'SUCCESS',
            'titre': 'Excellent taux de réussite',
            'message': f"Le taux de réussite de {sg['taux_reussite']}% est très satisfaisant. "
                      f"Continuez à maintenir ce niveau d'excellence.",
            'actions': [
                "Valoriser les efforts des élèves par des encouragements",
                "Proposer des défis supplémentaires aux meilleurs élèves",
                "Maintenir les méthodes pédagogiques actuelles"
            ]
        })
    elif sg['taux_reussite'] >= 60:
        recommandations.append({
            'type': 'WARNING',
            'titre': 'Taux de réussite à améliorer',
            'message': f"Le taux de réussite de {sg['taux_reussite']}% nécessite une attention particulière.",
            'actions': [
                "Identifier les lacunes communes aux élèves en difficulté",
                "Mettre en place des séances de révision ciblées",
                "Renforcer le suivi individuel des élèves fragiles"
            ]
        })
    else:
        recommandations.append({
            'type': 'DANGER',
            'titre': 'Situation préoccupante',
            'message': f"Le taux de réussite de {sg['taux_reussite']}% est alarmant et nécessite des mesures urgentes.",
            'actions': [
                "Organiser une réunion pédagogique d'urgence",
                "Revoir les méthodes d'enseignement",
                "Mettre en place un programme de soutien scolaire intensif",
                "Impliquer les parents dans le suivi des élèves"
            ]
        })
    
    # Recommandations pour les élèves en difficulté
    if eleves_diff:
        recommandations.append({
            'type': 'DANGER',
            'titre': f'{len(eleves_diff)} élève(s) en grande difficulté',
            'message': f"Ces élèves ont une moyenne inférieure à {seuil}/{note_max} et nécessitent une intervention immédiate.",
            'actions': [
                "Organiser des cours de rattrapage hebdomadaires",
                "Mettre en place un tutorat par les pairs",
                "Convoquer les parents pour un suivi personnalisé",
                "Identifier les matières les plus problématiques",
                "Adapter les exercices au niveau de l'élève"
            ]
        })
    
    # Recommandations pour les élèves à suivre
    if eleves_suivre:
        recommandations.append({
            'type': 'WARNING',
            'titre': f'{len(eleves_suivre)} élève(s) à surveiller',
            'message': f"Ces élèves ont une moyenne entre {seuil} et {seuil + 2}/{note_max}. Ils risquent de basculer en difficulté.",
            'actions': [
                "Renforcer l'accompagnement dans les matières faibles",
                "Encourager la participation en classe",
                "Proposer des exercices supplémentaires",
                "Vérifier régulièrement les devoirs"
            ]
        })
    
    # Analyse par matière
    matieres_faibles = [m for m in stats_matieres if m['moyenne'] < seuil]
    if matieres_faibles:
        noms_matieres = ', '.join([m['nom'] for m in matieres_faibles])
        recommandations.append({
            'type': 'DANGER',
            'titre': 'Matières en difficulté',
            'message': f"Les matières suivantes ont une moyenne de classe inférieure à {seuil}/{note_max} : {noms_matieres}",
            'actions': [
                "Revoir la méthodologie d'enseignement de ces matières",
                "Organiser des séances de remédiation",
                "Varier les supports pédagogiques",
                "Évaluer si le programme est adapté au niveau des élèves"
            ]
        })
    
    return recommandations


def _generer_astuces_rehaussement():
    """Génère des astuces générales pour rehausser le niveau des élèves"""
    return [
        {
            'categorie': 'Organisation du travail',
            'astuces': [
                "Établir un emploi du temps de révision régulier",
                "Créer un espace de travail calme et organisé",
                "Utiliser des fiches de révision synthétiques",
                "Réviser régulièrement plutôt que la veille des contrôles"
            ]
        },
        {
            'categorie': 'Méthodes d\'apprentissage',
            'astuces': [
                "Reformuler les leçons avec ses propres mots",
                "Faire des exercices pratiques régulièrement",
                "Utiliser des moyens mnémotechniques",
                "Expliquer les leçons à un camarade (méthode du pair)"
            ]
        },
        {
            'categorie': 'Participation en classe',
            'astuces': [
                "Poser des questions quand on ne comprend pas",
                "Participer activement aux discussions",
                "Prendre des notes structurées",
                "Relire ses notes le soir même"
            ]
        },
        {
            'categorie': 'Soutien scolaire',
            'astuces': [
                "Mettre en place des groupes d'entraide entre élèves",
                "Organiser des séances de tutorat",
                "Proposer des cours de soutien après les heures de classe",
                "Utiliser des ressources pédagogiques en ligne"
            ]
        },
        {
            'categorie': 'Motivation et confiance',
            'astuces': [
                "Fixer des objectifs réalistes et progressifs",
                "Célébrer les petites victoires et progrès",
                "Encourager plutôt que critiquer",
                "Valoriser l'effort autant que le résultat"
            ]
        }
    ]


@login_required
@can_manage_notes
def exporter_statistiques_pdf(request):
    """Exporte les statistiques en PDF avec graphiques et recommandations"""
    from reportlab.lib.utils import ImageReader

    classe_id = request.GET.get('classe_id')
    periode = request.GET.get('periode', 'TRIMESTRE_1')

    if not classe_id:
        return HttpResponse("Veuillez sélectionner une classe", status=400)

    ecole = _get_ecole(request)

    # Sécurité : filtrer par école de l'utilisateur
    if ecole:
        classe_note = get_object_or_404(ClasseNote, pk=classe_id, ecole=ecole)
    else:
        classe_note = get_object_or_404(ClasseNote, pk=classe_id)
    
    # Calculer les statistiques
    stats = _calculer_statistiques_classe(classe_note, periode)
    
    if not stats or not stats.get('stats_globales'):
        return HttpResponse("Aucune donnée disponible pour cette classe et cette période", status=404)
    
    note_max = stats.get('note_max', 20)
    seuil_reussite = stats.get('seuil_reussite', 10)
    est_primaire = stats.get('est_primaire', False)
    
    # Créer le PDF
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 1.5*cm
    
    # Fonction pour dessiner l'en-tête
    def dessiner_entete(y_pos):
        # Logo et nom de l'école
        c.setFont("Helvetica-Bold", 14)
        if ecole:
            c.drawCentredString(width/2, y_pos, ecole.nom.upper())
            y_pos -= 0.5*cm
            c.setFont("Helvetica", 10)
            if ecole.adresse:
                c.drawCentredString(width/2, y_pos, ecole.adresse)
                y_pos -= 0.4*cm
            if ecole.telephone:
                c.drawCentredString(width/2, y_pos, f"Tél: {ecole.tous_telephones}")
                y_pos -= 0.6*cm
        
        # Titre du rapport
        c.setFont("Helvetica-Bold", 16)
        c.setFillColor(colors.HexColor('#2C3E50'))
        c.drawCentredString(width/2, y_pos, "RAPPORT STATISTIQUE D'ÉVOLUTION DU NIVEAU")
        y_pos -= 0.6*cm
        
        # Sous-titre
        c.setFont("Helvetica-Bold", 12)
        c.setFillColor(colors.HexColor('#3498DB'))
        periode_libelle = periode.replace('_', ' ').title()
        c.drawCentredString(width/2, y_pos, f"Classe: {classe_note.nom} - Période: {periode_libelle}")
        y_pos -= 0.4*cm
        
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.gray)
        c.drawCentredString(width/2, y_pos, f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}")
        y_pos -= 0.8*cm
        
        # Ligne de séparation
        c.setStrokeColor(colors.HexColor('#3498DB'))
        c.setLineWidth(2)
        c.line(margin, y_pos, width - margin, y_pos)
        y_pos -= 0.5*cm
        
        c.setFillColor(colors.black)
        return y_pos
    
    y = height - margin
    y = dessiner_entete(y)
    
    # Section 1: Statistiques générales
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.HexColor('#2C3E50'))
    c.drawString(margin, y, "1. STATISTIQUES GÉNÉRALES")
    y -= 0.6*cm
    
    sg = stats['stats_globales']
    
    # Tableau des statistiques
    stats_data = [
        ['Indicateur', 'Valeur'],
        ['Nombre d\'élèves évalués', str(sg['total_eleves'])],
        ['Moyenne de classe', f"{sg['moyenne_classe']}/{note_max}"],
        ['Meilleure moyenne', f"{sg['moyenne_max']}/{note_max}"],
        ['Plus faible moyenne', f"{sg['moyenne_min']}/{note_max}"],
        ['Taux de réussite', f"{sg['taux_reussite']}%"],
        [f'Élèves en difficulté (<{seuil_reussite})', str(sg['nb_insuffisant'])],
        [f'Élèves excellents (≥{seuil_reussite + (2 if est_primaire else 4)})', str(sg['nb_excellent'] + sg['nb_tres_bien'])],
    ]
    
    table = Table(stats_data, colWidths=[8*cm, 4*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498DB')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#ECF0F1')),
        ('GRID', (0, 0), (-1, -1), 1, colors.white),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#ECF0F1')]),
    ]))
    
    table_width, table_height = table.wrap(0, 0)
    table.drawOn(c, margin, y - table_height)
    y -= table_height + 1*cm
    
    # Section 2: Graphique de répartition (si matplotlib disponible)
    if MATPLOTLIB_AVAILABLE:
        graph_repartition = _generer_graphique_repartition(stats)
        if graph_repartition:
            c.setFont("Helvetica-Bold", 12)
            c.setFillColor(colors.HexColor('#2C3E50'))
            c.drawString(margin, y, "2. RÉPARTITION DES MOYENNES")
            y -= 0.4*cm
            
            img = ImageReader(graph_repartition)
            img_width = 10*cm
            img_height = 6.5*cm
            c.drawImage(img, margin, y - img_height, width=img_width, height=img_height)
            y -= img_height + 0.8*cm
    
    # Nouvelle page pour les élèves en difficulté
    c.showPage()
    y = height - margin
    y = dessiner_entete(y)
    
    # Section 3: Élèves en difficulté
    eleves_diff = stats.get('eleves_en_difficulte', [])
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.HexColor('#E74C3C'))
    c.drawString(margin, y, f"3. ÉLÈVES EN DIFFICULTÉ ({len(eleves_diff)} élève(s) - Moyenne < {seuil_reussite}/{note_max})")
    y -= 0.6*cm
    
    if eleves_diff:
        eleves_data = [['Rang', 'Matricule', 'Nom & Prénom', 'Moyenne', 'Écart']]
        for e in eleves_diff:
            ecart = round(seuil_reussite - e['moyenne'], 2)
            eleves_data.append([
                str(e['rang']),
                e['eleve'].matricule or 'N/A',
                f"{e['eleve'].prenom} {e['eleve'].nom}",
                f"{e['moyenne']}/{note_max}",
                f"-{ecart} pts"
            ])
        
        table = Table(eleves_data, colWidths=[1.5*cm, 3*cm, 6*cm, 2.5*cm, 2*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E74C3C')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.gray),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#FADBD8')]),
        ]))
        
        table_width, table_height = table.wrap(0, 0)
        if y - table_height < 3*cm:
            c.showPage()
            y = height - margin
            y = dessiner_entete(y)
        table.drawOn(c, margin, y - table_height)
        y -= table_height + 0.8*cm
    else:
        c.setFont("Helvetica", 10)
        c.setFillColor(colors.HexColor('#27AE60'))
        c.drawString(margin, y, "✓ Aucun élève en difficulté pour cette période. Félicitations !")
        y -= 0.8*cm
    
    # Section 4: Élèves à surveiller
    eleves_suivre = stats.get('eleves_a_suivre', [])
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.HexColor('#F39C12'))
    c.drawString(margin, y, f"4. ÉLÈVES À SURVEILLER ({len(eleves_suivre)} élève(s) - Moyenne {seuil_reussite}-{seuil_reussite + 2}/{note_max})")
    y -= 0.6*cm
    
    if eleves_suivre:
        eleves_data = [['Rang', 'Matricule', 'Nom & Prénom', 'Moyenne']]
        for e in eleves_suivre[:10]:  # Limiter à 10
            eleves_data.append([
                str(e['rang']),
                e['eleve'].matricule or 'N/A',
                f"{e['eleve'].prenom} {e['eleve'].nom}",
                f"{e['moyenne']}/{note_max}"
            ])
        
        table = Table(eleves_data, colWidths=[1.5*cm, 3*cm, 7*cm, 2.5*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F39C12')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.gray),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#FCF3CF')]),
        ]))
        
        table_width, table_height = table.wrap(0, 0)
        if y - table_height < 3*cm:
            c.showPage()
            y = height - margin
            y = dessiner_entete(y)
        table.drawOn(c, margin, y - table_height)
        y -= table_height + 0.8*cm
    
    # Nouvelle page pour les recommandations
    c.showPage()
    y = height - margin
    y = dessiner_entete(y)
    
    # Section 5: Recommandations
    recommandations = _generer_recommandations(stats)
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.HexColor('#2C3E50'))
    c.drawString(margin, y, "5. RECOMMANDATIONS ET MESURES À PRENDRE")
    y -= 0.6*cm
    
    for reco in recommandations:
        if y < 4*cm:
            c.showPage()
            y = height - margin
            y = dessiner_entete(y)
        
        # Couleur selon le type
        if reco['type'] == 'DANGER':
            couleur = colors.HexColor('#E74C3C')
        elif reco['type'] == 'WARNING':
            couleur = colors.HexColor('#F39C12')
        else:
            couleur = colors.HexColor('#27AE60')
        
        # Titre de la recommandation
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(couleur)
        c.drawString(margin, y, f"• {reco['titre']}")
        y -= 0.4*cm
        
        # Message
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.black)
        
        # Découper le message si trop long
        message = reco['message']
        max_chars = 90
        while message:
            if len(message) <= max_chars:
                c.drawString(margin + 0.5*cm, y, message)
                message = ""
            else:
                # Trouver le dernier espace avant max_chars
                idx = message[:max_chars].rfind(' ')
                if idx == -1:
                    idx = max_chars
                c.drawString(margin + 0.5*cm, y, message[:idx])
                message = message[idx:].strip()
            y -= 0.35*cm
        
        # Actions
        c.setFont("Helvetica-Oblique", 8)
        c.setFillColor(colors.HexColor('#7F8C8D'))
        for action in reco.get('actions', [])[:4]:
            c.drawString(margin + 1*cm, y, f"→ {action}")
            y -= 0.3*cm
        
        y -= 0.4*cm
    
    # Section 6: Astuces de rehaussement
    if y < 6*cm:
        c.showPage()
        y = height - margin
        y = dessiner_entete(y)
    
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.HexColor('#9B59B6'))
    c.drawString(margin, y, "6. ASTUCES POUR REHAUSSER LE NIVEAU DES ÉLÈVES")
    y -= 0.6*cm
    
    astuces = _generer_astuces_rehaussement()
    for cat in astuces:
        if y < 3*cm:
            c.showPage()
            y = height - margin
            y = dessiner_entete(y)
        
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(colors.HexColor('#8E44AD'))
        c.drawString(margin, y, f"▸ {cat['categorie']}")
        y -= 0.35*cm
        
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.black)
        for astuce in cat['astuces']:
            c.drawString(margin + 0.5*cm, y, f"• {astuce}")
            y -= 0.3*cm
        y -= 0.2*cm
    
    # Pied de page final
    y -= 0.5*cm
    c.setStrokeColor(colors.HexColor('#BDC3C7'))
    c.setLineWidth(1)
    c.line(margin, y, width - margin, y)
    y -= 0.4*cm
    
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(colors.gray)
    c.drawCentredString(width/2, y, "Ce rapport a été généré automatiquement par le système de gestion scolaire.")
    y -= 0.3*cm
    c.drawCentredString(width/2, y, "Pour toute question, veuillez contacter l'administration de l'établissement.")
    
    c.save()
    
    # Retourner le PDF
    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    nom_classe = classe_note.nom.replace(' ', '_')
    filename = f"Rapport_Statistiques_{nom_classe}_{periode}_{datetime.now().strftime('%Y%m%d')}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response


def _generer_analyse_approfondie(stats):
    """Génère une analyse approfondie des résultats"""
    analyses = []
    sg = stats.get('stats_globales', {})
    eleves_diff = stats.get('eleves_en_difficulte', [])
    eleves_suivre = stats.get('eleves_a_suivre', [])
    note_max = stats.get('note_max', 20)
    
    taux = sg.get('taux_reussite', 0)
    moyenne = sg.get('moyenne_classe', 0)
    effectif = sg.get('total_eleves', sg.get('effectif', 0))
    
    # Analyse du taux de réussite
    if taux >= 80:
        analyses.append({
            'titre': 'Performance globale excellente',
            'diagnostic': f"Avec un taux de réussite de {taux:.1f}%, la classe affiche d'excellents résultats. "
                         f"La moyenne de classe de {moyenne:.2f}/{note_max} témoigne d'un bon niveau général.",
            'causes_probables': [
                "Bonne assimilation des cours par la majorité des élèves",
                "Méthodes pédagogiques adaptées au niveau de la classe",
                "Environnement d'apprentissage favorable"
            ],
            'type': 'SUCCESS'
        })
    elif taux >= 60:
        analyses.append({
            'titre': 'Performance globale satisfaisante avec marge de progression',
            'diagnostic': f"Le taux de réussite de {taux:.1f}% est acceptable mais perfectible. "
                         f"La moyenne de {moyenne:.2f}/{note_max} indique un niveau moyen qui peut être amélioré.",
            'causes_probables': [
                "Hétérogénéité du niveau des élèves",
                "Certaines notions mal assimilées par une partie de la classe",
                "Besoin de renforcement dans certaines matières"
            ],
            'type': 'WARNING'
        })
    else:
        analyses.append({
            'titre': 'Situation préoccupante nécessitant une intervention urgente',
            'diagnostic': f"Le taux de réussite de {taux:.1f}% est alarmant. "
                         f"Avec une moyenne de classe de {moyenne:.2f}/{note_max}, des mesures correctives s'imposent.",
            'causes_probables': [
                "Difficultés généralisées de compréhension",
                "Lacunes accumulées des années précédentes",
                "Méthodes de travail inadaptées",
                "Possible manque de motivation ou problèmes d'assiduité"
            ],
            'type': 'DANGER'
        })
    
    # Analyse des élèves en difficulté
    if len(eleves_diff) > effectif * 0.3 if effectif > 0 else False:
        analyses.append({
            'titre': 'Proportion élevée d\'élèves en difficulté',
            'diagnostic': f"{len(eleves_diff)} élèves ({len(eleves_diff)*100/effectif:.1f}% de la classe) sont en grande difficulté. "
                         "Cette proportion élevée suggère un problème systémique.",
            'causes_probables': [
                "Rythme d'enseignement possiblement trop rapide",
                "Prérequis non maîtrisés par une partie significative",
                "Nécessité de revoir les méthodes pédagogiques"
            ],
            'type': 'DANGER'
        })
    
    return analyses


def _generer_methodes_suivi():
    """Génère les méthodes de suivi détaillées"""
    return [
        {
            'titre': 'SUIVI QUOTIDIEN',
            'actions': [
                "Vérification systématique des cahiers de textes et devoirs",
                "Interrogations orales régulières pour évaluer la compréhension",
                "Observation du comportement et de la participation en classe",
                "Communication immédiate en cas d'absence non justifiée"
            ],
            'responsable': 'Enseignants',
            'frequence': 'Quotidien'
        },
        {
            'titre': 'SUIVI HEBDOMADAIRE',
            'actions': [
                "Bilan des notes et appréciations de la semaine",
                "Séance de soutien scolaire pour les élèves en difficulté",
                "Réunion de coordination entre enseignants (si nécessaire)",
                "Mise à jour du carnet de correspondance"
            ],
            'responsable': 'Professeur principal + Équipe pédagogique',
            'frequence': 'Hebdomadaire'
        },
        {
            'titre': 'SUIVI MENSUEL',
            'actions': [
                "Analyse des résultats et progression de chaque élève",
                "Convocation des parents des élèves en difficulté",
                "Ajustement du plan de soutien personnalisé",
                "Rapport au directeur des études"
            ],
            'responsable': 'Professeur principal + Direction',
            'frequence': 'Mensuel'
        },
        {
            'titre': 'SUIVI TRIMESTRIEL',
            'actions': [
                "Conseil de classe avec analyse approfondie",
                "Remise des bulletins avec entretien individuel si nécessaire",
                "Définition des objectifs pour le trimestre suivant",
                "Évaluation de l'efficacité des mesures de soutien"
            ],
            'responsable': 'Conseil de classe',
            'frequence': 'Trimestriel'
        }
    ]


def _detecter_niveau_classe(classe_nom):
    """Détecte le niveau scolaire à partir du nom de la classe pour les lettres"""
    from .calculs_moyennes import detecter_niveau_scolaire
    return detecter_niveau_scolaire(classe_nom)


def _get_titres_signataires(niveau):
    """Retourne les titres des signataires selon le niveau scolaire"""
    if niveau == 'MATERNELLE':
        return 'La Monitrice', 'La Coordinatrice'
    elif niveau == 'PRIMAIRE':
        return 'Le Maître de la classe', 'Le Directeur du Primaire'
    else:
        return 'Le Professeur Principal', 'Le Directeur'


def _generer_lettre_parent(eleve_data, classe_nom, periode, ecole_nom):
    """Génère le contenu d'une lettre aux parents avec analyse intelligente
    (genre de l'élève, niveau scolaire, titres adaptés)"""
    eleve = eleve_data['eleve']
    moyenne = eleve_data['moyenne']
    matieres_sans_notes = eleve_data.get('matieres_sans_notes', [])
    
    # Analyse intelligente du genre
    est_fille = getattr(eleve, 'sexe', 'M') == 'F'
    pronom_il = 'elle' if est_fille else 'il'
    pronom_le = 'la' if est_fille else 'le'
    pronom_son = 'sa' if est_fille else 'son'
    accord_e = 'e' if est_fille else ''
    mot_fils = 'votre fille' if est_fille else 'votre fils'
    
    # Analyse intelligente du niveau scolaire
    niveau = _detecter_niveau_classe(classe_nom)
    titre_enseignant, titre_direction = _get_titres_signataires(niveau)
    note_max = 10 if niveau == 'PRIMAIRE' else 20
    seuil_diff = 4 if niveau == 'PRIMAIRE' else 8
    
    # Adapter le vocabulaire au niveau
    if niveau == 'MATERNELLE':
        mot_eleve = 'votre enfant'
        mot_travail = 'les activités et apprentissages'
        mot_evaluation = 'les activités d\'évaluation'
    elif niveau == 'PRIMAIRE':
        mot_eleve = mot_fils
        mot_travail = 'les devoirs et leçons'
        mot_evaluation = 'les évaluations'
    else:
        mot_eleve = mot_fils
        mot_travail = 'les devoirs, leçons et révisions'
        mot_evaluation = 'les évaluations et compositions'
    
    # Déterminer le niveau de gravité (adapté au barème)
    seuil_critique = 3 if niveau == 'PRIMAIRE' else 6
    seuil_grave = 4 if niveau == 'PRIMAIRE' else 8
    if moyenne < seuil_critique:
        niveau_gravite = 'critique'
        urgence = 'URGENT'
    elif moyenne < seuil_grave:
        niveau_gravite = 'grave'
        urgence = 'IMPORTANT'
    else:
        niveau_gravite = 'preoccupant'
        urgence = 'À NOTER'
    
    # Construire le constat avec genre
    constat = f"À l'issue de la période {periode}, {eleve.prenom} a obtenu une moyenne générale de {moyenne:.2f}/{note_max}, "
    constat += f"ce qui {pronom_le} place en situation de {'grande difficulté' if moyenne < seuil_diff else 'difficulté'}."
    
    # Ajouter l'alerte sur les matières sans notes
    if matieres_sans_notes:
        constat += f"\n\nATTENTION: {eleve.prenom} n'a pas de notes dans {len(matieres_sans_notes)} matière(s): "
        constat += ", ".join(matieres_sans_notes[:5])
        if len(matieres_sans_notes) > 5:
            constat += f" et {len(matieres_sans_notes) - 5} autre(s)"
        constat += f". Ces matières sont comptées comme 0/{note_max} dans le calcul de la moyenne."
    
    consequences = [
        f"Risque de redoublement si la situation ne s'améliore pas",
        f"Accumulation de lacunes pouvant compromettre la suite de {pronom_son} parcours scolaire",
        f"Perte de confiance et de motivation possible chez {mot_eleve}"
    ]
    
    # Ajouter conséquence spécifique si matières sans notes
    if matieres_sans_notes:
        consequences.insert(0, f"Les {len(matieres_sans_notes)} matière(s) sans notes pénalisent fortement la moyenne")
    
    # Adapter les demandes au niveau
    demandes = [
        f"Vérifier quotidiennement {mot_travail}",
        f"Assurer un environnement calme et propice au travail à la maison",
    ]
    
    if niveau == 'MATERNELLE':
        demandes.extend([
            f"Accompagner {mot_eleve} dans ses activités d'éveil à la maison",
            f"Encourager {pronom_le} et valoriser ses progrès, même les plus petits",
            f"Vous présenter à l'école pour un entretien avec {titre_enseignant.lower()}"
        ])
    elif niveau == 'PRIMAIRE':
        demandes.extend([
            f"Limiter les distractions (télévision, jeux vidéo)",
            f"Encourager et valoriser les efforts de {mot_eleve}, même minimes",
            f"Vous présenter à l'école pour un entretien avec {titre_enseignant.lower()}"
        ])
    else:
        demandes.extend([
            f"Limiter les distractions (téléphone, télévision, jeux vidéo)",
            f"Encourager et valoriser les efforts de {mot_eleve}, même minimes",
            f"Vous présenter à l'école pour un entretien avec {titre_enseignant.lower()}"
        ])
    
    # Ajouter demande spécifique si matières sans notes
    if matieres_sans_notes:
        demandes.insert(0, f"S'assurer que {mot_eleve} participe à TOUTES {mot_evaluation}")
    
    lettre = {
        'objet': f"[{urgence}] Situation scolaire de {eleve.prenom} {eleve.nom}",
        'intro': f"Nous vous informons que {mot_eleve} {eleve.prenom} {eleve.nom}, "
                f"élève en classe de {classe_nom}, rencontre actuellement des difficultés scolaires importantes.",
        'constat': constat,
        'consequences': consequences,
        'demandes': demandes,
        'matieres_sans_notes': matieres_sans_notes,
        'conclusion': f"Nous restons à votre disposition pour tout entretien. "
                     f"Votre implication est essentielle pour aider {mot_eleve} à surmonter ces difficultés.",
        'titre_enseignant': titre_enseignant,
        'titre_direction': titre_direction,
        'niveau': niveau,
        'est_fille': est_fille,
    }
    
    return lettre


def _generer_lettre_eleve(eleve_data, classe_nom, periode):
    """Génère le contenu d'une lettre à l'élève avec analyse intelligente du genre et du niveau"""
    eleve = eleve_data['eleve']
    moyenne = eleve_data['moyenne']
    matieres_sans_notes = eleve_data.get('matieres_sans_notes', [])
    
    # Analyse intelligente du genre
    est_fille = getattr(eleve, 'sexe', 'M') == 'F'
    cher = 'Chère' if est_fille else 'Cher'
    accord_e = 'e' if est_fille else ''
    sur_e = 'sûre' if est_fille else 'sûr'
    convaincu = 'convaincus' if est_fille else 'convaincus'
    
    # Analyse intelligente du niveau scolaire
    niveau = _detecter_niveau_classe(classe_nom)
    note_max = 10 if niveau == 'PRIMAIRE' else 20
    
    # Construire le constat
    constat = f"Tes résultats de ce {periode} montrent que tu rencontres des difficultés. "
    constat += f"Ta moyenne de {moyenne:.2f}/{note_max} n'est pas à la hauteur de ce que tu peux accomplir."
    
    # Ajouter l'alerte sur les matières sans notes
    if matieres_sans_notes:
        constat += f"\n\nATTENTION: Tu n'as pas de notes dans {len(matieres_sans_notes)} matière(s): "
        constat += ", ".join(matieres_sans_notes[:3])
        if len(matieres_sans_notes) > 3:
            constat += f" et {len(matieres_sans_notes) - 3} autre(s)"
        constat += f". Ces matières comptent comme 0/{note_max} et font baisser ta moyenne!"
    
    # Adapter les conseils au niveau
    if niveau == 'MATERNELLE':
        conseils = [
            "Écoute bien ta monitrice pendant les activités",
            "Participe à toutes les activités en classe",
            "Demande de l'aide quand tu ne comprends pas",
            "Fais les petits exercices que ta monitrice te donne"
        ]
    elif niveau == 'PRIMAIRE':
        conseils = [
            "Écoute bien ton maître en classe",
            "Fais tes devoirs chaque soir sans attendre",
            "N'hésite pas à poser des questions quand tu ne comprends pas",
            "Revois tes leçons chaque soir, même 15-20 minutes",
            "Travaille avec tes camarades qui peuvent t'aider",
            f"Fixe-toi des petits objectifs atteignables chaque semaine"
        ]
    else:
        conseils = [
            "Organise ton temps de travail avec un planning régulier",
            "N'hésite pas à poser des questions en classe quand tu ne comprends pas",
            "Revois tes leçons chaque soir, même 15-20 minutes",
            "Travaille en groupe avec des camarades qui peuvent t'aider",
            "Participe aux séances de soutien scolaire proposées",
            f"Fixe-toi des petits objectifs atteignables chaque semaine"
        ]
    
    # Ajouter conseil spécifique si matières sans notes
    if matieres_sans_notes:
        conseils.insert(0, f"IMPORTANT: Participe à TOUTES les évaluations, même si tu n'es pas {sur_e} de toi")
        conseils.insert(1, f"Rattrape tes notes manquantes en: {', '.join(matieres_sans_notes[:3])}")
    
    lettre = {
        'titre': f"Message personnel pour {eleve.prenom}",
        'intro': f"{cher} {eleve.prenom},",
        'constat': constat,
        'encouragements': [
            "Chaque élève peut progresser avec de la volonté et du travail",
            "Tes difficultés actuelles ne définissent pas ton avenir",
            "Tes enseignants croient en toi et sont là pour t'aider"
        ],
        'conseils': conseils,
        'matieres_sans_notes': matieres_sans_notes,
        'conclusion': f"Nous sommes {convaincu} que tu peux t'améliorer. "
                     "L'important est de ne pas baisser les bras et de demander de l'aide quand tu en as besoin."
    }
    
    return lettre


@login_required
@can_manage_notes
def exporter_conseils_pdf(request):
    """
    Exporte les conseils et prises de décision en PDF
    Document complet avec analyses approfondies et lettres de recommandation
    """
    from reportlab.lib.utils import ImageReader

    classe_id = request.GET.get('classe_id')
    periode = request.GET.get('periode')

    if not classe_id or not periode:
        return HttpResponse("Paramètres manquants (classe_id et periode requis)", status=400)

    ecole = _get_ecole(request)

    # Sécurité : filtrer par école de l'utilisateur
    if ecole:
        classe_note = get_object_or_404(ClasseNote, pk=classe_id, ecole=ecole)
    else:
        classe_note = get_object_or_404(ClasseNote, pk=classe_id)
    ecole_nom = ecole.nom if ecole else "L'École"
    
    # Calculer les statistiques
    stats = _calculer_statistiques_classe(classe_note, periode)
    
    if not stats:
        return HttpResponse("Aucune donnée disponible pour cette classe et période", status=404)
    
    note_max = stats.get('note_max', 20)
    seuil_reussite = stats.get('seuil_reussite', 10)
    est_primaire = stats.get('est_primaire', False)
    
    # Créer le PDF
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 1.5*cm
    
    # Couleurs
    BLEU_FONCE = colors.HexColor('#1a5276')
    VERT = colors.HexColor('#27AE60')
    ORANGE = colors.HexColor('#F39C12')
    ROUGE = colors.HexColor('#E74C3C')
    VIOLET = colors.HexColor('#8E44AD')
    GRIS = colors.HexColor('#7F8C8D')
    
    def dessiner_filigrane():
        """Dessine le logo de l'école en filigrane au centre de la page"""
        if ecole and hasattr(ecole, 'logo') and ecole.logo:
            try:
                c.saveState()
                # Position centrale
                logo_width = 12*cm
                logo_height = 12*cm
                x_center = (width - logo_width) / 2
                y_center = (height - logo_height) / 2
                
                # Appliquer transparence (opacité faible pour filigrane)
                c.setFillAlpha(0.08)
                c.setStrokeAlpha(0.08)
                
                # Dessiner le logo en filigrane
                logo = ImageReader(ecole.logo.path)
                c.drawImage(logo, x_center, y_center, width=logo_width, height=logo_height, 
                           preserveAspectRatio=True, mask='auto')
                
                c.restoreState()
            except Exception:
                pass
    
    def dessiner_entete(y_pos, titre_page="CONSEILS ET PRISES DE DÉCISION"):
        """Dessine l'en-tête du document avec filigrane"""
        # D'abord dessiner le filigrane (en arrière-plan)
        dessiner_filigrane()
        
        # Logo en haut à gauche
        if ecole and hasattr(ecole, 'logo') and ecole.logo:
            try:
                logo = ImageReader(ecole.logo.path)
                c.drawImage(logo, margin, y_pos - 1.5*cm, width=1.5*cm, height=1.5*cm, preserveAspectRatio=True)
            except:
                pass
        
        c.setFont("Helvetica-Bold", 14)
        c.setFillColor(BLEU_FONCE)
        c.drawCentredString(width/2, y_pos - 0.5*cm, titre_page)
        
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(colors.HexColor('#2C3E50'))
        c.drawCentredString(width/2, y_pos - 1.0*cm, f"Classe: {classe_note.nom} - Période: {periode}")
        
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.gray)
        c.drawCentredString(width/2, y_pos - 1.4*cm, f"Document généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}")
        
        c.setStrokeColor(BLEU_FONCE)
        c.setLineWidth(2)
        c.line(margin, y_pos - 1.6*cm, width - margin, y_pos - 1.6*cm)
        
        return y_pos - 2.2*cm
    
    def nouvelle_page(titre="CONSEILS ET PRISES DE DÉCISION"):
        c.showPage()
        return dessiner_entete(height - margin, titre)
    
    def dessiner_texte_multiligne(texte, x, y_start, max_width, font="Helvetica", size=9):
        """Dessine du texte sur plusieurs lignes"""
        c.setFont(font, size)
        words = texte.split()
        lines = []
        current_line = ""
        
        for word in words:
            test_line = current_line + " " + word if current_line else word
            if c.stringWidth(test_line, font, size) < max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        
        y = y_start
        for line in lines:
            c.drawString(x, y, line)
            y -= size + 2
        
        return y
    
    y = height - margin
    y = dessiner_entete(y)
    
    sg = stats.get('stats_globales', {})
    
    # ===== SECTION 1: SYNTHÈSE GLOBALE =====
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(BLEU_FONCE)
    c.drawString(margin, y, "1. SYNTHÈSE DE LA CLASSE")
    y -= 0.8*cm
    
    sg = stats['stats_globales']
    
    # Encadré de synthèse
    c.setStrokeColor(colors.HexColor('#BDC3C7'))
    c.setFillColor(colors.HexColor('#F8F9FA'))
    c.rect(margin, y - 2.5*cm, width - 2*margin, 2.5*cm, fill=1, stroke=1)
    
    # Contenu de la synthèse - Utiliser les bonnes clés
    effectif = sg.get('total_eleves', sg.get('effectif', 0))
    moyenne_classe = sg.get('moyenne_classe', 0)
    taux_reussite = sg.get('taux_reussite', 0)
    nb_admis = sg.get('nb_admis', effectif - sg.get('nb_insuffisant', 0))
    nb_non_admis = sg.get('nb_non_admis', sg.get('nb_insuffisant', 0))
    meilleure_moy = sg.get('meilleure_moyenne', sg.get('moyenne_max', 0))
    plus_faible_moy = sg.get('plus_faible_moyenne', sg.get('moyenne_min', 0))
    ecart_type = sg.get('ecart_type', 0)
    
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(colors.black)
    c.drawString(margin + 0.3*cm, y - 0.5*cm, f"Effectif: {effectif} élèves")
    c.drawString(margin + 6*cm, y - 0.5*cm, f"Moyenne de classe: {moyenne_classe:.2f}/{note_max}")
    
    # Taux de réussite avec couleur
    taux = taux_reussite
    if taux >= 70:
        couleur_taux = VERT
    elif taux >= 50:
        couleur_taux = ORANGE
    else:
        couleur_taux = ROUGE
    
    c.setFillColor(couleur_taux)
    c.drawString(margin + 0.3*cm, y - 1.1*cm, f"Taux de réussite: {taux:.1f}%")
    
    c.setFillColor(colors.black)
    c.drawString(margin + 6*cm, y - 1.1*cm, f"Admis: {nb_admis} | Non admis: {nb_non_admis}")
    
    c.setFont("Helvetica", 10)
    c.drawString(margin + 0.3*cm, y - 1.7*cm, f"Meilleure moyenne: {meilleure_moy:.2f}/{note_max}")
    c.drawString(margin + 6*cm, y - 1.7*cm, f"Plus faible moyenne: {plus_faible_moy:.2f}/{note_max}")
    c.drawString(margin + 0.3*cm, y - 2.2*cm, f"Écart-type: {ecart_type:.2f}")
    
    y -= 3.2*cm
    
    # ===== SECTION 2: RECOMMANDATIONS =====
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(BLEU_FONCE)
    c.drawString(margin, y, "2. RECOMMANDATIONS PÉDAGOGIQUES")
    y -= 0.7*cm
    
    recommandations = _generer_recommandations(stats)
    
    for reco in recommandations:
        if y < 4*cm:
            c.showPage()
            y = height - margin
            y = dessiner_entete(y)
        
        # Couleur selon le type
        if reco['type'] == 'DANGER':
            couleur = ROUGE
            icone = "⚠"
        elif reco['type'] == 'WARNING':
            couleur = ORANGE
            icone = "⚡"
        else:
            couleur = VERT
            icone = "✓"
        
        # Titre de la recommandation
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(couleur)
        c.drawString(margin, y, f"{icone} {reco['titre']}")
        y -= 0.5*cm
        
        # Message
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.black)
        
        # Découper le message en lignes
        message = reco['message']
        max_chars = 90
        while message:
            if len(message) <= max_chars:
                c.drawString(margin + 0.5*cm, y, message)
                message = ""
            else:
                # Trouver le dernier espace avant max_chars
                idx = message[:max_chars].rfind(' ')
                if idx == -1:
                    idx = max_chars
                c.drawString(margin + 0.5*cm, y, message[:idx])
                message = message[idx:].strip()
            y -= 0.35*cm
        
        # Actions recommandées
        if 'actions' in reco and reco['actions']:
            c.setFont("Helvetica-Oblique", 9)
            c.setFillColor(colors.HexColor('#555555'))
            for action in reco['actions'][:3]:  # Max 3 actions
                c.drawString(margin + 0.8*cm, y, f"→ {action}")
                y -= 0.35*cm
        
        y -= 0.3*cm
    
    # ===== SECTION 3: ÉLÈVES NÉCESSITANT UNE ATTENTION PARTICULIÈRE =====
    if y < 5*cm:
        c.showPage()
        y = height - margin
        y = dessiner_entete(y)
    
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(BLEU_FONCE)
    c.drawString(margin, y, "3. ÉLÈVES NÉCESSITANT UNE ATTENTION PARTICULIÈRE")
    y -= 0.7*cm
    
    # Élèves en difficulté
    eleves_diff = stats.get('eleves_en_difficulte', [])
    if eleves_diff:
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(ROUGE)
        c.drawString(margin, y, f"⚠ Élèves en grande difficulté ({len(eleves_diff)} élève(s) - Moyenne < {seuil_reussite}/{note_max})")
        y -= 0.5*cm
        
        # Tableau des élèves en difficulté
        data = [['Nom & Prénom', 'Moyenne', 'Décision proposée']]
        for eleve_data in eleves_diff[:10]:  # Max 10 élèves
            eleve = eleve_data['eleve']
            moy = eleve_data['moyenne']
            seuil_urgent = 4 if est_primaire else 8
            decision = "Soutien scolaire urgent" if moy < seuil_urgent else "Accompagnement renforcé"
            data.append([f"{eleve.prenom} {eleve.nom}", f"{moy:.2f}/{note_max}", decision])
        
        table = Table(data, colWidths=[7*cm, 3*cm, 6*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ROUGE),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (1, 0), (1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.gray),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#FFEBEE')]),
        ]))
        
        table_w, table_h = table.wrap(width - 2*margin, height)
        if y - table_h < 2*cm:
            c.showPage()
            y = height - margin
            y = dessiner_entete(y)
        table.drawOn(c, margin, y - table_h)
        y -= table_h + 0.5*cm
    
    # Élèves à surveiller
    eleves_suivre = stats.get('eleves_a_suivre', [])
    if eleves_suivre:
        if y < 4*cm:
            c.showPage()
            y = height - margin
            y = dessiner_entete(y)
        
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(ORANGE)
        c.drawString(margin, y, f"⚡ Élèves à surveiller ({len(eleves_suivre)} élève(s) - Moyenne {seuil_reussite}-{seuil_reussite + 2}/{note_max})")
        y -= 0.5*cm
        
        # Liste des élèves à surveiller
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.black)
        for eleve_data in eleves_suivre[:8]:  # Max 8 élèves
            eleve = eleve_data['eleve']
            moy = eleve_data['moyenne']
            c.drawString(margin + 0.3*cm, y, f"• {eleve.prenom} {eleve.nom} ({moy:.2f}/{note_max}) - Accompagnement personnalisé recommandé")
            y -= 0.35*cm
        
        if len(eleves_suivre) > 8:
            c.setFont("Helvetica-Oblique", 8)
            c.setFillColor(colors.gray)
            c.drawString(margin + 0.3*cm, y, f"... et {len(eleves_suivre) - 8} autre(s) élève(s)")
            y -= 0.35*cm
        
        y -= 0.3*cm
    
    # ===== SECTION 4: ANALYSE APPROFONDIE =====
    y = nouvelle_page("ANALYSE APPROFONDIE")
    
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(BLEU_FONCE)
    c.drawString(margin, y, "4. ANALYSE APPROFONDIE DE LA SITUATION")
    y -= 0.7*cm
    
    analyses = _generer_analyse_approfondie(stats)
    
    for analyse in analyses:
        if y < 5*cm:
            y = nouvelle_page("ANALYSE APPROFONDIE")
        
        # Type d'analyse avec couleur
        if analyse['type'] == 'DANGER':
            couleur = ROUGE
        elif analyse['type'] == 'WARNING':
            couleur = ORANGE
        else:
            couleur = VERT
        
        # Titre
        c.setFillColor(couleur)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(margin, y, analyse['titre'].upper())
        y -= 0.5*cm
        
        # Diagnostic
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 9)
        y = dessiner_texte_multiligne(analyse['diagnostic'], margin + 0.3*cm, y, width - 2.5*margin)
        y -= 0.3*cm
        
        # Causes probables
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(GRIS)
        c.drawString(margin + 0.3*cm, y, "Causes probables identifiées:")
        y -= 0.4*cm
        
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.black)
        for cause in analyse.get('causes_probables', []):
            c.drawString(margin + 0.6*cm, y, f"• {cause}")
            y -= 0.3*cm
        y -= 0.4*cm
    
    # ===== SECTION 5: MÉTHODES DE SUIVI DÉTAILLÉES =====
    if y < 6*cm:
        y = nouvelle_page("MÉTHODES DE SUIVI")
    
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(BLEU_FONCE)
    c.drawString(margin, y, "5. PROTOCOLE DE SUIVI PÉDAGOGIQUE")
    y -= 0.7*cm
    
    methodes = _generer_methodes_suivi()
    
    for methode in methodes:
        if y < 4*cm:
            y = nouvelle_page("MÉTHODES DE SUIVI")
        
        # Encadré titre
        c.setFillColor(BLEU_FONCE)
        c.rect(margin, y - 0.5*cm, width - 2*margin, 0.6*cm, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margin + 0.2*cm, y - 0.35*cm, f"{methode['titre']} ({methode['frequence']})")
        y -= 0.8*cm
        
        # Responsable
        c.setFillColor(VIOLET)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(margin + 0.2*cm, y, f"Responsable: {methode['responsable']}")
        y -= 0.4*cm
        
        # Actions
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 8)
        for action in methode['actions']:
            c.drawString(margin + 0.4*cm, y, f"→ {action}")
            y -= 0.3*cm
        y -= 0.3*cm
    
    # ===== SECTION 6: ASTUCES POUR AMÉLIORER LES RÉSULTATS =====
    if y < 5*cm:
        y = nouvelle_page("ASTUCES PÉDAGOGIQUES")
    
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(BLEU_FONCE)
    c.drawString(margin, y, "6. ASTUCES POUR AMÉLIORER LES RÉSULTATS")
    y -= 0.7*cm
    
    astuces = _generer_astuces_rehaussement()
    
    for cat in astuces[:4]:
        if y < 3*cm:
            y = nouvelle_page("ASTUCES PÉDAGOGIQUES")
        
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(VIOLET)
        c.drawString(margin, y, f"▸ {cat['categorie']}")
        y -= 0.4*cm
        
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.black)
        for astuce in cat['astuces'][:3]:
            c.drawString(margin + 0.5*cm, y, f"• {astuce}")
            y -= 0.35*cm
        y -= 0.2*cm
    
    # ===== SECTION 7: LETTRES DE RECOMMANDATION AUX PARENTS =====
    eleves_diff = stats.get('eleves_en_difficulte', [])
    
    if eleves_diff:
        for eleve_data in eleves_diff[:5]:  # Max 5 lettres
            y = nouvelle_page("LETTRE AUX PARENTS")
            
            lettre = _generer_lettre_parent(eleve_data, classe_note.nom, periode, ecole_nom)
            eleve = eleve_data['eleve']
            
            # En-tête lettre
            c.setFont("Helvetica-Bold", 12)
            c.setFillColor(BLEU_FONCE)
            c.drawString(margin, y, f"LETTRE D'INFORMATION AUX PARENTS")
            y -= 0.6*cm
            
            c.setFont("Helvetica", 9)
            c.setFillColor(colors.black)
            c.drawString(margin, y, f"Concernant: {eleve.prenom} {eleve.nom}")
            c.drawRightString(width - margin, y, f"Date: {datetime.now().strftime('%d/%m/%Y')}")
            y -= 0.8*cm
            
            # Objet
            c.setFont("Helvetica-Bold", 10)
            c.setFillColor(ROUGE)
            c.drawString(margin, y, f"Objet: {lettre['objet']}")
            y -= 0.8*cm
            
            # Corps de la lettre
            c.setFillColor(colors.black)
            c.setFont("Helvetica", 9)
            c.drawString(margin, y, "Madame, Monsieur,")
            y -= 0.5*cm
            
            y = dessiner_texte_multiligne(lettre['intro'], margin, y, width - 2*margin)
            y -= 0.3*cm
            y = dessiner_texte_multiligne(lettre['constat'], margin, y, width - 2*margin)
            y -= 0.5*cm
            
            # Conséquences possibles
            c.setFont("Helvetica-Bold", 9)
            c.setFillColor(ROUGE)
            c.drawString(margin, y, "Conséquences possibles si la situation persiste:")
            y -= 0.4*cm
            
            c.setFont("Helvetica", 8)
            c.setFillColor(colors.black)
            for consequence in lettre['consequences']:
                c.drawString(margin + 0.3*cm, y, f"• {consequence}")
                y -= 0.3*cm
            y -= 0.3*cm
            
            # Ce que nous vous demandons
            c.setFont("Helvetica-Bold", 9)
            c.setFillColor(VERT)
            c.drawString(margin, y, "Ce que nous vous demandons:")
            y -= 0.4*cm
            
            c.setFont("Helvetica", 8)
            c.setFillColor(colors.black)
            for demande in lettre['demandes']:
                c.drawString(margin + 0.3*cm, y, f"✓ {demande}")
                y -= 0.3*cm
            y -= 0.4*cm
            
            # Conclusion
            c.setFont("Helvetica", 9)
            y = dessiner_texte_multiligne(lettre['conclusion'], margin, y, width - 2*margin)
            y -= 0.6*cm
            
            # Formule de politesse
            c.drawString(margin, y, "Veuillez agréer, Madame, Monsieur, l'expression de nos salutations distinguées.")
            y -= 1.2*cm
            
            # Signatures dynamiques selon le niveau
            c.setFont("Helvetica-Bold", 9)
            c.drawString(margin, y, lettre.get('titre_enseignant', 'Le Professeur Principal'))
            c.drawString(width/2, y, lettre.get('titre_direction', 'Le Directeur'))
            y -= 1.5*cm
            c.line(margin, y, margin + 5*cm, y)
            c.line(width/2, y, width/2 + 5*cm, y)
            y -= 0.5*cm
            
            # Coupon réponse
            c.setStrokeColor(colors.gray)
            c.setDash(3, 3)
            c.line(margin, y, width - margin, y)
            c.setDash()
            y -= 0.5*cm
            
            c.setFont("Helvetica-Bold", 9)
            c.setFillColor(BLEU_FONCE)
            c.drawString(margin, y, "COUPON-RÉPONSE À RETOURNER À L'ÉCOLE")
            y -= 0.5*cm
            
            titre_rdv = lettre.get('titre_enseignant', 'la Direction').lower()
            c.setFont("Helvetica", 8)
            c.setFillColor(colors.black)
            c.drawString(margin, y, f"Je soussigné(e) _________________________, parent de {eleve.prenom} {eleve.nom},")
            y -= 0.4*cm
            c.drawString(margin, y, "□ Ai pris connaissance de cette lettre et m'engage à suivre mon enfant de près.")
            y -= 0.4*cm
            c.drawString(margin, y, f"□ Souhaite un rendez-vous avec {titre_rdv} le ___/___/______ à ___h___.")
            y -= 0.4*cm
            c.drawString(margin, y, "□ Souhaite être contacté(e) par téléphone au: _______________________")
            y -= 0.6*cm
            c.drawString(margin, y, "Date: ___/___/______          Signature: _________________________")
    
    # ===== SECTION 8: LETTRES DE RECOMMANDATION AUX ÉLÈVES =====
    if eleves_diff:
        for eleve_data in eleves_diff[:5]:  # Max 5 lettres
            y = nouvelle_page("MESSAGE À L'ÉLÈVE")
            
            lettre = _generer_lettre_eleve(eleve_data, classe_note.nom, periode)
            eleve = eleve_data['eleve']
            
            # Encadré décoratif
            c.setStrokeColor(BLEU_FONCE)
            c.setLineWidth(2)
            c.rect(margin - 0.2*cm, y - 14*cm, width - 2*margin + 0.4*cm, 14.5*cm, fill=0, stroke=1)
            
            # Titre
            c.setFont("Helvetica-Bold", 14)
            c.setFillColor(BLEU_FONCE)
            c.drawCentredString(width/2, y, lettre['titre'])
            y -= 1*cm
            
            # Introduction
            c.setFont("Helvetica-Bold", 11)
            c.setFillColor(colors.black)
            c.drawString(margin + 0.3*cm, y, lettre['intro'])
            y -= 0.8*cm
            
            # Constat
            c.setFont("Helvetica", 10)
            y = dessiner_texte_multiligne(lettre['constat'], margin + 0.3*cm, y, width - 2.5*margin, size=10)
            y -= 0.6*cm
            
            # Encouragements
            c.setFont("Helvetica-Bold", 10)
            c.setFillColor(VERT)
            c.drawString(margin + 0.3*cm, y, "N'oublie jamais que:")
            y -= 0.5*cm
            
            c.setFont("Helvetica", 9)
            c.setFillColor(colors.black)
            for encouragement in lettre['encouragements']:
                c.drawString(margin + 0.6*cm, y, f"★ {encouragement}")
                y -= 0.4*cm
            y -= 0.3*cm
            
            # Conseils pratiques
            c.setFont("Helvetica-Bold", 10)
            c.setFillColor(VIOLET)
            c.drawString(margin + 0.3*cm, y, "Voici des conseils pour t'améliorer:")
            y -= 0.5*cm
            
            c.setFont("Helvetica", 9)
            c.setFillColor(colors.black)
            for i, conseil in enumerate(lettre['conseils'], 1):
                c.drawString(margin + 0.6*cm, y, f"{i}. {conseil}")
                y -= 0.4*cm
            y -= 0.4*cm
            
            # Conclusion
            c.setFont("Helvetica-Oblique", 10)
            c.setFillColor(BLEU_FONCE)
            y = dessiner_texte_multiligne(lettre['conclusion'], margin + 0.3*cm, y, width - 2.5*margin, font="Helvetica-Oblique", size=10)
            y -= 0.8*cm
            
            # Signature
            c.setFont("Helvetica-Bold", 10)
            c.setFillColor(colors.black)
            c.drawRightString(width - margin - 0.3*cm, y, "Tes enseignants qui croient en toi")
            y -= 1*cm
            
            # Espace engagement élève
            c.setStrokeColor(ORANGE)
            c.setFillColor(colors.HexColor('#FFF8E1'))
            c.rect(margin + 0.3*cm, y - 2.5*cm, width - 2*margin - 0.6*cm, 2.5*cm, fill=1, stroke=1)
            
            c.setFont("Helvetica-Bold", 9)
            c.setFillColor(ORANGE)
            c.drawString(margin + 0.6*cm, y - 0.4*cm, "MON ENGAGEMENT PERSONNEL:")
            
            c.setFont("Helvetica", 8)
            c.setFillColor(colors.black)
            c.drawString(margin + 0.6*cm, y - 0.9*cm, f"Moi, {eleve.prenom}, je m'engage à:")
            c.drawString(margin + 0.6*cm, y - 1.3*cm, "_______________________________________________________________")
            c.drawString(margin + 0.6*cm, y - 1.7*cm, "_______________________________________________________________")
            c.drawString(margin + 0.6*cm, y - 2.1*cm, f"Date: ___/___/______     Signature de l'élève: _______________")
    
    # ===== SECTION 9: ESPACE POUR DÉCISIONS DU CONSEIL =====
    y = nouvelle_page("DÉCISIONS DU CONSEIL")
    
    c.setFont("Helvetica-Bold", 14)
    c.setFillColor(BLEU_FONCE)
    c.drawString(margin, y, "9. DÉCISIONS DU CONSEIL DE CLASSE")
    y -= 0.7*cm
    
    # Encadré pour les notes manuscrites
    c.setStrokeColor(colors.HexColor('#BDC3C7'))
    c.setFillColor(colors.white)
    c.rect(margin, y - 6*cm, width - 2*margin, 6*cm, fill=1, stroke=1)
    
    # Lignes pour écrire
    c.setStrokeColor(colors.HexColor('#E0E0E0'))
    c.setLineWidth(0.5)
    for i in range(1, 12):
        c.line(margin + 0.3*cm, y - (0.5*cm * i), width - margin - 0.3*cm, y - (0.5*cm * i))
    
    y -= 6.5*cm
    
    # ===== SIGNATURES =====
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(colors.black)
    
    sig_width = (width - 2*margin) / 3
    
    # Professeur principal
    c.drawString(margin, y, "Le Professeur Principal")
    c.line(margin, y - 1.5*cm, margin + sig_width - 0.5*cm, y - 1.5*cm)
    
    # Directeur des études
    c.drawString(margin + sig_width, y, "Le Directeur des Études")
    c.line(margin + sig_width, y - 1.5*cm, margin + 2*sig_width - 0.5*cm, y - 1.5*cm)
    
    # Directeur
    c.drawString(margin + 2*sig_width, y, "Le Directeur")
    c.line(margin + 2*sig_width, y - 1.5*cm, width - margin, y - 1.5*cm)
    
    # Pied de page
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(colors.gray)
    c.drawCentredString(width/2, 1*cm, f"Document confidentiel - {ecole_nom} - Année scolaire {classe_note.annee_scolaire}")
    
    c.save()
    
    # Retourner le PDF
    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    nom_classe = classe_note.nom.replace(' ', '_')
    filename = f"Conseils_Decisions_{nom_classe}_{periode}_{datetime.now().strftime('%Y%m%d')}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response
