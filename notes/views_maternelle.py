"""
Vues pour l'évaluation et les bulletins de la maternelle
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db import transaction
from django.utils import timezone
from datetime import datetime
import json

from .models import (
    ClasseNote, MatiereNote, EvaluationMaternelle, NoteMaternelle,
    AnalyseTravailMaternelle, RecommandationMaternelle, AppreciationMaternelle
)
from eleves.models import Eleve, Classe
from eleves.utils_annee import get_annee_active
from .analyse_maternelle_intelligente import AnalyseMaternelleIntelligente


def get_annee_scolaire_courante():
    """Retourne l'année scolaire courante au format 2024-2025"""
    today = datetime.now()
    if today.month >= 9:
        return f"{today.year}-{today.year + 1}"
    else:
        return f"{today.year - 1}-{today.year}"


def obtenir_periode_maternelle(request, annee_scolaire):
    """Retourne uniquement une période autorisée pour l'année scolaire concernée."""
    choix = EvaluationMaternelle.get_choix_periodes(annee_scolaire)
    codes_autorises = {code for code, _ in choix}
    periode = request.GET.get('trimestre', EvaluationMaternelle.get_periode_par_defaut(annee_scolaire))
    if periode not in codes_autorises:
        periode = EvaluationMaternelle.get_periode_par_defaut(annee_scolaire)
    return periode, choix


@login_required
def saisie_evaluation_maternelle(request):
    """Vue principale pour la saisie des évaluations maternelle"""
    user = request.user
    
    # Filtrer les classes maternelles (par année active)
    ecole = user.profil.ecole if hasattr(user, 'profil') else None
    annee_active = get_annee_active(request, ecole) if ecole else None

    if user.is_superuser:
        qs = ClasseNote.objects.filter(niveau__in=['GARDERIE', 'MATERNELLE'], actif=True)
    else:
        qs = ClasseNote.objects.filter(ecole=ecole, niveau__in=['GARDERIE', 'MATERNELLE'], actif=True)

    if annee_active:
        classes = qs.filter(annee_scolaire=annee_active).order_by('nom')
    else:
        classes = qs.order_by('nom')

    annee_scolaire = annee_active or get_annee_scolaire_courante()
    
    # Récupérer les paramètres de filtrage
    classe_id = request.GET.get('classe')
    trimestre, choix_periodes = obtenir_periode_maternelle(request, annee_scolaire)
    
    eleves = []
    matieres = []
    classe_selectionnee = None
    evaluations_existantes = {}
    
    if classe_id:
        classe_selectionnee = get_object_or_404(ClasseNote, id=classe_id)
        annee_scolaire = classe_selectionnee.annee_scolaire or annee_scolaire
        trimestre, choix_periodes = obtenir_periode_maternelle(request, annee_scolaire)
        
        # Récupérer les élèves de cette classe depuis le module eleves
        # Utiliser l'année scolaire de la ClasseNote
        try:
            classe_eleves = Classe.objects.filter(
                nom=classe_selectionnee.nom,
                annee_scolaire=classe_selectionnee.annee_scolaire
            ).first()
            if classe_eleves:
                eleves = Eleve.objects.filter(
                    classe=classe_eleves,
                    statut='ACTIF'
                ).order_by('nom', 'prenom')
            else:
                eleves = []
        except Classe.DoesNotExist:
            eleves = []
        
        # Récupérer les matières de la classe
        matieres = MatiereNote.objects.filter(
            classe=classe_selectionnee,
            actif=True
        ).order_by('nom')
        
        # Récupérer les évaluations existantes
        for eleve in eleves:
            eval_existante = EvaluationMaternelle.objects.filter(
                eleve=eleve,
                classe=classe_selectionnee,
                trimestre=trimestre,
                annee_scolaire=annee_scolaire
            ).first()
            if eval_existante:
                evaluations_existantes[eleve.id] = eval_existante
    
    context = {
        'classes': classes,
        'classe_selectionnee': classe_selectionnee,
        'eleves': eleves,
        'matieres': matieres,
        'trimestre': trimestre,
        'trimestres': choix_periodes,
        'annee_scolaire': annee_scolaire,
        'evaluations_existantes': evaluations_existantes,
        'lettres_choices': EvaluationMaternelle.LETTRE_CHOICES,
    }
    
    return render(request, 'notes/maternelle/saisie_evaluation.html', context)


@login_required
def saisie_eleve_maternelle(request, eleve_id):
    """Vue de saisie détaillée pour un élève"""
    eleve = get_object_or_404(Eleve, id=eleve_id)
    
    classe_id = request.GET.get('classe')
    classe_note = get_object_or_404(ClasseNote, id=classe_id)
    annee_scolaire = classe_note.annee_scolaire or get_annee_scolaire_courante()
    trimestre, _ = obtenir_periode_maternelle(request, annee_scolaire)
    matieres = MatiereNote.objects.filter(classe=classe_note, actif=True).order_by('nom')
    
    # Récupérer ou créer l'évaluation
    evaluation, created = EvaluationMaternelle.objects.get_or_create(
        eleve=eleve,
        classe=classe_note,
        trimestre=trimestre,
        annee_scolaire=annee_scolaire,
        defaults={'cree_par': request.user}
    )
    
    # Récupérer ou créer l'analyse et les recommandations
    analyse, _ = AnalyseTravailMaternelle.objects.get_or_create(evaluation=evaluation)
    recommandations, _ = RecommandationMaternelle.objects.get_or_create(evaluation=evaluation)
    
    # Récupérer les notes existantes
    notes_existantes = {n.matiere_id: n for n in evaluation.notes_matieres.all()}
    
    if request.method == 'POST':
        return sauvegarder_evaluation_maternelle(request, evaluation, matieres, analyse, recommandations)
    
    context = {
        'eleve': eleve,
        'classe_note': classe_note,
        'trimestre': trimestre,
        'trimestre_display': dict(EvaluationMaternelle.TRIMESTRE_CHOICES).get(trimestre),
        'annee_scolaire': annee_scolaire,
        'matieres': matieres,
        'evaluation': evaluation,
        'notes_existantes': notes_existantes,
        'analyse': analyse,
        'recommandations': recommandations,
        'lettres_choices': EvaluationMaternelle.LETTRE_CHOICES,
    }
    
    return render(request, 'notes/maternelle/saisie_eleve.html', context)


@login_required
@transaction.atomic
def sauvegarder_evaluation_maternelle(request, evaluation, matieres, analyse, recommandations):
    """Sauvegarde l'évaluation maternelle complète"""
    try:
        # Sauvegarder les notes par matière
        for matiere in matieres:
            note_key = f'note_{matiere.id}'
            if note_key not in request.POST:
                continue
            note_value = request.POST.get(note_key)
            commentaire = request.POST.get(f'commentaire_{matiere.id}', '')
            
            if note_value and note_value.strip():
                try:
                    note_decimal = float(note_value.replace(',', '.'))
                    if note_decimal < 0 or note_decimal > 10:
                        messages.warning(request, f"Note ignorée pour {matiere.nom}: elle doit être entre 0 et 10.")
                        continue
                    NoteMaternelle.objects.update_or_create(
                        evaluation=evaluation,
                        matiere=matiere,
                        defaults={
                            'note': note_decimal,
                            'commentaire': commentaire
                        }
                    )
                    AppreciationMaternelle.objects.update_or_create(
                        eleve=evaluation.eleve,
                        matiere=matiere,
                        trimestre=evaluation.trimestre,
                        annee_scolaire=evaluation.annee_scolaire,
                        defaults={
                            'appreciation': EvaluationMaternelle.note_vers_lettre(note_decimal),
                            'commentaire': commentaire or None,
                            'absent': False,
                            'cree_par': request.user,
                        }
                    )
                except ValueError:
                    pass
            else:
                # Un champ vidé signifie que la note doit réellement être retirée
                # de la période, ainsi que l'appréciation calculée correspondante.
                NoteMaternelle.objects.filter(
                    evaluation=evaluation,
                    matiere=matiere,
                ).delete()
                AppreciationMaternelle.objects.filter(
                    eleve=evaluation.eleve,
                    matiere=matiere,
                    trimestre=evaluation.trimestre,
                    annee_scolaire=evaluation.annee_scolaire,
                ).delete()
        
        # Sauvegarder l'analyse du travail
        analyse.comprend_demandes = request.POST.get('comprend_demandes') == 'on'
        analyse.ne_comprend_pas = request.POST.get('ne_comprend_pas') == 'on'
        analyse.trop_jeune = request.POST.get('trop_jeune') == 'on'
        analyse.fixe_attention = request.POST.get('fixe_attention') == 'on'
        analyse.pas_probleme_monitrice = request.POST.get('pas_probleme_monitrice') == 'on'
        analyse.pas_probleme_camarades = request.POST.get('pas_probleme_camarades') == 'on'
        analyse.pas_probleme_famille = request.POST.get('pas_probleme_famille') == 'on'
        analyse.est_doue = request.POST.get('est_doue') == 'on'
        analyse.est_paresseux = request.POST.get('est_paresseux') == 'on'
        analyse.commentaire = request.POST.get('analyse_commentaire', '')
        analyse.save()
        
        # Sauvegarder les recommandations
        recommandations.encourager_feliciter = request.POST.get('encourager_feliciter') == 'on'
        recommandations.suivre_domicile = request.POST.get('suivre_domicile') == 'on'
        recommandations.gouter_dans_sac = request.POST.get('gouter_dans_sac') == 'on'
        recommandations.aide_encouragement_parents = request.POST.get('aide_encouragement_parents') == 'on'
        recommandations.amour_parental = request.POST.get('amour_parental') == 'on'
        recommandations.besoin_epanouissement = request.POST.get('besoin_epanouissement') == 'on'
        recommandations.sorties_educatives = request.POST.get('sorties_educatives') == 'on'
        recommandations.aide_intellectuelle = request.POST.get('aide_intellectuelle') == 'on'
        recommandations.douceur_patience = request.POST.get('douceur_patience') == 'on'
        recommandations.besoin_fermete = request.POST.get('besoin_fermete') == 'on'
        recommandations.esprit_inferiorite = request.POST.get('esprit_inferiorite') == 'on'
        recommandations.attention_particuliere = request.POST.get('attention_particuliere') == 'on'
        recommandations.commentaire = request.POST.get('recommandation_commentaire', '')
        recommandations.save()
        
        # Analyse automatique des appréciations si un commentaire est fourni
        appreciation_text = request.POST.get('appreciation_automatique', '').strip()
        if appreciation_text:
            try:
                AnalyseMaternelleIntelligente.appliquer_analyse_automatique(evaluation, appreciation_text)
                messages.info(request, "Analyse automatique des appréciations effectuée")
            except Exception as e:
                messages.warning(request, f"L'analyse automatique a échoué: {str(e)}")
        
        messages.success(request, f"Évaluation de {evaluation.eleve} sauvegardée avec succès!")
        
        # Rediriger vers la liste ou le bulletin
        if 'voir_bulletin' in request.POST:
            return redirect('notes:bulletin_maternelle_pdf', evaluation_id=evaluation.id)
        
        return redirect(f'/notes/maternelle/saisie/?classe={evaluation.classe.id}&trimestre={evaluation.trimestre}')
        
    except Exception as e:
        messages.error(request, f"Erreur lors de la sauvegarde: {str(e)}")
        return redirect(request.path)


@login_required
def bulletin_maternelle(request, evaluation_id):
    """Affiche le bulletin maternelle en HTML"""
    evaluation = get_object_or_404(EvaluationMaternelle, id=evaluation_id)
    
    # Récupérer les données associées
    notes = evaluation.notes_matieres.select_related('matiere').order_by('matiere__nom')
    
    try:
        analyse = evaluation.analyse_travail
    except AnalyseTravailMaternelle.DoesNotExist:
        analyse = None
    
    try:
        recommandations = evaluation.recommandations
    except RecommandationMaternelle.DoesNotExist:
        recommandations = None
    
    # Calculer la moyenne générale
    moyenne = evaluation.get_moyenne_generale()
    lettre_generale = evaluation.get_lettre_generale()
    mention_generale = EvaluationMaternelle.lettre_vers_mention(lettre_generale) if lettre_generale else ''
    bilan_annuel = EvaluationMaternelle.calculer_bilan_annuel(
        evaluation.eleve, evaluation.classe, evaluation.annee_scolaire
    )
    
    # Récupérer l'école
    ecole = evaluation.classe.ecole
    
    context = {
        'evaluation': evaluation,
        'eleve': evaluation.eleve,
        'classe': evaluation.classe,
        'ecole': ecole,
        'notes': notes,
        'analyse': analyse,
        'recommandations': recommandations,
        'moyenne': moyenne,
        'lettre_generale': lettre_generale,
        'mention_generale': mention_generale,
        'bilan_annuel': bilan_annuel,
        'analyses_selectionnees': analyse.get_analyses_selectionnees() if analyse else [],
        'recommandations_selectionnees': recommandations.get_recommandations_selectionnees() if recommandations else [],
    }
    
    return render(request, 'notes/maternelle/bulletin.html', context)


@login_required
def bulletin_maternelle_pdf(request, evaluation_id):
    """Génère le bulletin maternelle en PDF"""
    from weasyprint import HTML, CSS
    from django.template.loader import render_to_string
    import base64
    import os
    
    evaluation = get_object_or_404(EvaluationMaternelle, id=evaluation_id)
    
    # Récupérer les données
    notes = evaluation.notes_matieres.select_related('matiere').order_by('matiere__nom')
    
    try:
        analyse = evaluation.analyse_travail
    except AnalyseTravailMaternelle.DoesNotExist:
        analyse = None
    
    try:
        recommandations = evaluation.recommandations
    except RecommandationMaternelle.DoesNotExist:
        recommandations = None
    
    # Calculer les résultats
    moyenne = evaluation.get_moyenne_generale()
    lettre_generale = evaluation.get_lettre_generale()
    mention_generale = EvaluationMaternelle.lettre_vers_mention(lettre_generale) if lettre_generale else ''
    bilan_annuel = EvaluationMaternelle.calculer_bilan_annuel(
        evaluation.eleve, evaluation.classe, evaluation.annee_scolaire
    )
    
    # Récupérer l'école et encoder le logo
    ecole = evaluation.classe.ecole
    logo_base64 = ''
    if ecole.logo:
        try:
            logo_path = ecole.logo.path
            if os.path.exists(logo_path):
                with open(logo_path, 'rb') as f:
                    logo_base64 = base64.b64encode(f.read()).decode('utf-8')
        except Exception:
            pass
    
    # Photo de l'élève
    photo_base64 = ''
    eleve = evaluation.eleve
    if hasattr(eleve, 'photo') and eleve.photo:
        try:
            photo_path = eleve.photo.path
            if os.path.exists(photo_path):
                with open(photo_path, 'rb') as f:
                    photo_base64 = base64.b64encode(f.read()).decode('utf-8')
        except Exception:
            pass
    
    context = {
        'evaluation': evaluation,
        'eleve': eleve,
        'classe': evaluation.classe,
        'ecole': ecole,
        'notes': notes,
        'analyse': analyse,
        'recommandations': recommandations,
        'moyenne': moyenne,
        'lettre_generale': lettre_generale,
        'mention_generale': mention_generale,
        'bilan_annuel': bilan_annuel,
        'analyses_selectionnees': analyse.get_analyses_selectionnees() if analyse else [],
        'recommandations_selectionnees': recommandations.get_recommandations_selectionnees() if recommandations else [],
        'logo_base64': logo_base64,
        'photo_base64': photo_base64,
        'date_impression': timezone.now(),
    }
    
    # Générer le HTML
    html_content = render_to_string('notes/maternelle/bulletin_pdf.html', context)
    
    # Générer le PDF
    pdf_file = HTML(string=html_content).write_pdf()
    
    # Créer la réponse
    response = HttpResponse(pdf_file, content_type='application/pdf')
    filename = f"bulletin_maternelle_{eleve.nom}_{eleve.prenom}_{evaluation.trimestre}.pdf"
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    
    return response


@login_required
def bulletins_classe_maternelle_pdf(request):
    """Génère tous les bulletins d'une classe maternelle en un seul PDF"""
    from weasyprint import HTML, CSS
    from django.template.loader import render_to_string
    import base64
    import os
    
    classe_id = request.GET.get('classe')
    
    if not classe_id:
        messages.error(request, "Veuillez sélectionner une classe")
        return redirect('notes:saisie_evaluation_maternelle')
    
    classe_note = get_object_or_404(ClasseNote, id=classe_id)
    annee_scolaire = classe_note.annee_scolaire or get_annee_scolaire_courante()
    trimestre, _ = obtenir_periode_maternelle(request, annee_scolaire)
    
    # Récupérer toutes les évaluations de la classe
    evaluations = EvaluationMaternelle.objects.filter(
        classe=classe_note,
        trimestre=trimestre,
        annee_scolaire=annee_scolaire
    ).select_related('eleve').prefetch_related(
        'notes_matieres__matiere',
        'analyse_travail',
        'recommandations'
    ).order_by('eleve__nom', 'eleve__prenom')
    
    if not evaluations.exists():
        messages.warning(request, "Aucune évaluation trouvée pour cette classe et cette période")
        return redirect('notes:saisie_evaluation_maternelle')
    
    # Encoder le logo
    ecole = classe_note.ecole
    logo_base64 = ''
    if ecole.logo:
        try:
            logo_path = ecole.logo.path
            if os.path.exists(logo_path):
                with open(logo_path, 'rb') as f:
                    logo_base64 = base64.b64encode(f.read()).decode('utf-8')
        except Exception:
            pass
    
    # Préparer les données pour chaque élève
    bulletins_data = []
    for evaluation in evaluations:
        notes = evaluation.notes_matieres.select_related('matiere').order_by('matiere__nom')
        
        try:
            analyse = evaluation.analyse_travail
        except AnalyseTravailMaternelle.DoesNotExist:
            analyse = None
        
        try:
            recommandations = evaluation.recommandations
        except RecommandationMaternelle.DoesNotExist:
            recommandations = None
        
        moyenne = evaluation.get_moyenne_generale()
        lettre_generale = evaluation.get_lettre_generale()
        mention_generale = EvaluationMaternelle.lettre_vers_mention(lettre_generale) if lettre_generale else ''
        bilan_annuel = EvaluationMaternelle.calculer_bilan_annuel(
            evaluation.eleve, evaluation.classe, evaluation.annee_scolaire
        )
        
        # Photo de l'élève
        photo_base64 = ''
        if hasattr(evaluation.eleve, 'photo') and evaluation.eleve.photo:
            try:
                photo_path = evaluation.eleve.photo.path
                if os.path.exists(photo_path):
                    with open(photo_path, 'rb') as f:
                        photo_base64 = base64.b64encode(f.read()).decode('utf-8')
            except Exception:
                pass
        
        bulletins_data.append({
            'evaluation': evaluation,
            'eleve': evaluation.eleve,
            'notes': notes,
            'analyse': analyse,
            'recommandations': recommandations,
            'moyenne': moyenne,
            'lettre_generale': lettre_generale,
            'mention_generale': mention_generale,
            'bilan_annuel': bilan_annuel,
            'analyses_selectionnees': analyse.get_analyses_selectionnees() if analyse else [],
            'recommandations_selectionnees': recommandations.get_recommandations_selectionnees() if recommandations else [],
            'photo_base64': photo_base64,
        })
    
    context = {
        'bulletins': bulletins_data,
        'classe': classe_note,
        'ecole': ecole,
        'trimestre': trimestre,
        'trimestre_display': dict(EvaluationMaternelle.TRIMESTRE_CHOICES).get(trimestre),
        'annee_scolaire': annee_scolaire,
        'logo_base64': logo_base64,
        'date_impression': timezone.now(),
    }
    
    # Générer le HTML
    html_content = render_to_string('notes/maternelle/bulletins_classe_pdf.html', context)
    
    # Générer le PDF
    pdf_file = HTML(string=html_content).write_pdf()
    
    # Créer la réponse
    response = HttpResponse(pdf_file, content_type='application/pdf')
    filename = f"bulletins_maternelle_{classe_note.nom}_{trimestre}.pdf"
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    
    return response


@login_required
def analyse_appreciations_auto(request):
    """Vue pour l'analyse automatique des appréciations"""
    if request.method == 'POST':
        appreciation_text = request.POST.get('appreciation_text', '').strip()
        evaluation_id = request.POST.get('evaluation_id')
        
        if not appreciation_text:
            return JsonResponse({'success': False, 'error': 'Veuillez fournir une appréciation'})
        
        if evaluation_id:
            try:
                evaluation = EvaluationMaternelle.objects.get(id=evaluation_id)
                analyse, recommandations = AnalyseMaternelleIntelligente.appliquer_analyse_automatique(
                    evaluation, appreciation_text
                )
                
                return JsonResponse({
                    'success': True,
                    'message': 'Analyse effectuée avec succès',
                    'analyses': {
                        'selectionnees': analyse.get_analyses_selectionnees(),
                        'comprend_demandes': analyse.comprend_demandes,
                        'ne_comprend_pas': analyse.ne_comprend_pas,
                        'trop_jeune': analyse.trop_jeune,
                        'fixe_attention': analyse.fixe_attention,
                        'pas_probleme_monitrice': analyse.pas_probleme_monitrice,
                        'pas_probleme_camarades': analyse.pas_probleme_camarades,
                        'pas_probleme_famille': analyse.pas_probleme_famille,
                        'est_doue': analyse.est_doue,
                        'est_paresseux': analyse.est_paresseux
                    },
                    'recommandations': {
                        'selectionnees': recommandations.get_recommandations_selectionnees(),
                        'encourager_feliciter': recommandations.encourager_feliciter,
                        'suivre_domicile': recommandations.suivre_domicile,
                        'gouter_dans_sac': recommandations.gouter_dans_sac,
                        'aide_encouragement_parents': recommandations.aide_encouragement_parents,
                        'amour_parental': recommandations.amour_parental,
                        'besoin_epanouissement': recommandations.besoin_epanouissement,
                        'sorties_educatives': recommandations.sorties_educatives,
                        'aide_intellectuelle': recommandations.aide_intellectuelle,
                        'douceur_patience': recommandations.douceur_patience,
                        'besoin_fermete': recommandations.besoin_fermete,
                        'esprit_inferiorite': recommandations.esprit_inferiorite,
                        'attention_particuliere': recommandations.attention_particuliere
                    }
                })
            except EvaluationMaternelle.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Évaluation non trouvée'})
        
        # Analyse simple sans sauvegarde
        analyses_dict, recommandations_dict = AnalyseMaternelleIntelligente.analyser_appreciation(appreciation_text)
        
        return JsonResponse({
            'success': True,
            'analyses': analyses_dict,
            'recommandations': recommandations_dict
        })
    
    return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})


@login_required
def api_get_eleves_classe(request):
    """API pour récupérer les élèves d'une classe"""
    classe_id = request.GET.get('classe_id')
    annee_scolaire = get_annee_scolaire_courante()
    
    if not classe_id:
        return JsonResponse({'error': 'Classe non spécifiée'}, status=400)
    
    try:
        classe_note = ClasseNote.objects.get(id=classe_id)
        classe_eleves = Classe.objects.filter(
            nom=classe_note.nom,
            annee_scolaire=classe_note.annee_scolaire
        ).first()
        if classe_eleves:
            eleves = Eleve.objects.filter(
                classe=classe_eleves,
                statut='ACTIF'
            ).order_by('nom', 'prenom').values('id', 'nom', 'prenom', 'matricule')
        else:
            eleves = []
        
        return JsonResponse({'eleves': list(eleves)})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
