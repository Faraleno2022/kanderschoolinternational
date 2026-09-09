"""
Système d'analyse automatique des appréciations pour la maternelle
Permet d'analyser les appréciations textuelles et de générer automatiquement
les cases à cocher d'analyse et les recommandations
"""

import re
from typing import Dict, List, Tuple, Optional
from django.db import transaction
from django.http import JsonResponse
from .models import EvaluationMaternelle, AnalyseTravailMaternelle, RecommandationMaternelle


class AnalyseMaternelleIntelligente:
    """Système intelligent d'analyse des appréciations maternelles"""
    
    # Mots-clés pour l'analyse du travail
    MOTS_CLES_ANALYSE = {
        'comprend_demandes': [
            'comprend', 'comprend bien', 'comprend très bien', 'saisit', 'assimile',
            'capte', 'dégage', 'intelligent', 'brillant', 'vif', 'réfléchi'
        ],
        'ne_comprend_pas': [
            'ne comprend pas', 'difficile à comprendre', 'comprend mal', 
            'confus', 'perdu', 'ne saisit pas', 'n assimile pas'
        ],
        'trop_jeune': [
            'trop jeune', 'pas prêt', 'pas mûr', 'immature', 'tôt',
            'pas au niveau', 'en difficulté', 'suivi difficile'
        ],
        'fixe_attention': [
            'attention', 'concentre', 'écoute', 'attentif', 'appliqué',
            'sérieux', 'travaille bien', 'motivé', 'intéressé'
        ],
        'pas_probleme_monitrice': [
            'monitrice', 'maîtresse', 'professeur', 'enseignant', 's\'adapte',
            'bon élève', 'discipliné', 'obéissant', 'respectueux'
        ],
        'pas_probleme_camarades': [
            'camarades', 'amis', 'sociable', 'aime jouer', 'partage',
            'aide les autres', 'gentil', 'amical', 'intégré'
        ],
        'pas_probleme_famille': [
            'famille', 'parents', 'maman', 'papa', 'maison', 'vie familiale',
            'bonne relation', 'entente', 'stable'
        ],
        'est_doue': [
            'doué', 'talentueux', 'brillant', 'exceptionnel', 'très intelligent',
            'génie', 'précoce', 'avancé', 'supérieur'
        ],
        'est_paresseux': [
            'paresseux', 'fainéant', 'nonchalant', 'désintéressé', 'passif',
            'ne fait rien', 'démotivé', 'peu travailleur'
        ]
    }
    
    # Mots-clés pour les recommandations
    MOTS_CLES_RECOMMANDATIONS = {
        'encourager_feliciter': [
            'excellent', 'très bon', 'bravo', 'félicitations', 'continue',
            'super', 'génial', 'remarquable', 'exceptionnel'
        ],
        'suivre_domicile': [
            'suivre', 'accompagner', 'aider à la maison', 'surveiller',
            'travailler avec', 'réviser', 'soutenir'
        ],
        'gouter_dans_sac': [
            'goûter', 'nourriture', 'manger', 'repas', 'faim', 'nutrition',
            'alimentation', 'sac', 'cantine'
        ],
        'aide_encouragement_parents': [
            'aide', 'encouragement', 'soutien', 'accompagnement',
            'parents doivent', 'familial', 'soutien parental'
        ],
        'amour_parental': [
            'amour', 'affectif', 'tendresse', 'câlin', 'réconfort',
            'maternel', 'paternel', 'affectueux'
        ],
        'besoin_epanouissement': [
            'épanouissement', 'développement', 'évolution', 'progression',
            's\'épanouir', 'grandir', 'mûrir'
        ],
        'sorties_educatives': [
            'sorties', 'visites', 'excursions', 'découverte', 'extérieur',
            'parc', 'musée', 'activités', 'loisirs'
        ],
        'aide_intellectuelle': [
            'aide intellectuelle', 'développer', 'facultés', 'intelligence',
            'apprentissage', 'connaissances', 'capacités'
        ],
        'douceur_patience': [
            'douceur', 'patience', 'tendresse', 'calme', 'doux',
            'patient', 'compréhensif', 'tolérant'
        ],
        'besoin_fermete': [
            'fermeté', 'discipline', 'règles', 'cadre', 'autorité',
            'sévère', 'strict', 'rigide'
        ],
        'esprit_inferiorite': [
            'infériorité', 'manque confiance', 'timide', 'peur', 'anxiété',
            'complexé', 'réservé', 'renfermé'
        ],
        'attention_particuliere': [
            'attention particulière', 'surveillance', 'suivi spécial',
            'soutien individualisé', 'personnalisé', 'adapté'
        ]
    }
    
    @classmethod
    def analyser_appreciation(cls, appreciation_text: str) -> Tuple[Dict[str, bool], Dict[str, bool]]:
        """
        Analyse une appréciation textuelle et retourne les analyses et recommandations
        
        Args:
            appreciation_text: Texte de l'appréciation à analyser
            
        Returns:
            Tuple contenant (analyses, recommandations) comme dictionnaires de booléens
        """
        if not appreciation_text:
            return {}, {}
        
        # Normalisation du texte
        texte = appreciation_text.lower().strip()
        
        # Analyse du travail
        analyses = {}
        for critere, mots_cles in cls.MOTS_CLES_ANALYSE.items():
            analyses[critere] = False
            for mot in mots_cles:
                if mot in texte:
                    analyses[critere] = True
                    break
        
        # Recommandations
        recommandations = {}
        for critere, mots_cles in cls.MOTS_CLES_RECOMMANDATIONS.items():
            recommandations[critere] = False
            for mot in mots_cles:
                if mot in texte:
                    recommandations[critere] = True
                    break
        
        # Logique spéciale pour les contradictions
        cls._appliquer_logique_speciale(analyses, recommandations, texte)
        
        return analyses, recommandations
    
    @classmethod
    def _appliquer_logique_speciale(cls, analyses: Dict[str, bool], recommandations: Dict[str, bool], texte: str):
        """Applique des règles logiques spéciales pour les contradictions et corrélations"""
        
        # Contradiction: comprend vs ne comprend pas
        if analyses['comprend_demandes'] and analyses['ne_comprend_pas']:
            # Priorité au positif si les deux sont présents
            if 'très bien' in texte or 'excellent' in texte or 'brillant' in texte:
                analyses['ne_comprend_pas'] = False
            else:
                analyses['comprend_demandes'] = False
        
        # Si l'enfant est doué, il ne peut être paresseux
        if analyses['est_doue'] and analyses['est_paresseux']:
            analyses['est_paresseux'] = False
        
        # Si l'enfant est trop jeune, il peut avoir besoin d'aide
        if analyses['trop_jeune']:
            recommandations['suivre_domicile'] = True
            recommandations['aide_encouragement_parents'] = True
        
        # Si l'enfant est paresseux, il a besoin de fermeté
        if analyses['est_paresseux']:
            recommandations['besoin_fermete'] = True
            recommandations['attention_particuliere'] = True
        
        # Si l'enfant est doué, il faut l'encourager
        if analyses['est_doue']:
            recommandations['encourager_feliciter'] = True
            recommandations['aide_intellectuelle'] = True
        
        # Si l'enfant ne comprend pas, il a besoin d'aide
        if analyses['ne_comprend_pas']:
            recommandations['aide_intellectuelle'] = True
            recommandations['suivre_domicile'] = True
            recommandations['attention_particuliere'] = True
        
        # Si l'enfant ne fixe pas son attention, il a besoin de suivi
        if not analyses['fixe_attention']:
            recommandations['attention_particuliere'] = True
            recommandations['douceur_patience'] = True
    
    @classmethod
    @transaction.atomic
    def appliquer_analyse_automatique(cls, evaluation: EvaluationMaternelle, appreciation_text: str):
        """
        Applique l'analyse automatique à une évaluation
        
        Args:
            evaluation: L'évaluation maternelle à mettre à jour
            appreciation_text: Le texte de l'appréciation à analyser
        """
        # Analyser l'appréciation
        analyses_dict, recommandations_dict = cls.analyser_appreciation(appreciation_text)
        
        # Récupérer ou créer l'analyse du travail
        analyse, _ = AnalyseTravailMaternelle.objects.get_or_create(evaluation=evaluation)
        
        # Mettre à jour les champs d'analyse
        for champ, valeur in analyses_dict.items():
            if hasattr(analyse, champ):
                setattr(analyse, champ, valeur)
        
        analyse.save()
        
        # Récupérer ou créer les recommandations
        recommandations, _ = RecommandationMaternelle.objects.get_or_create(evaluation=evaluation)
        
        # Mettre à jour les champs de recommandations
        for champ, valeur in recommandations_dict.items():
            if hasattr(recommandations, champ):
                setattr(recommandations, champ, valeur)
        
        recommandations.save()
        
        return analyse, recommandations
    
    @classmethod
    def generer_rapport_analyse(cls, evaluation: EvaluationMaternelle) -> Dict:
        """
        Génère un rapport détaillé de l'analyse effectuée
        
        Args:
            evaluation: L'évaluation à analyser
            
        Returns:
            Dictionnaire contenant le rapport d'analyse
        """
        try:
            analyse = evaluation.analyse_travail
            recommandations = evaluation.recommandations
        except:
            return {'erreur': 'Aucune analyse ou recommandation trouvée'}
        
        rapport = {
            'eleve': str(evaluation.eleve),
            'classe': str(evaluation.classe),
            'trimestre': evaluation.get_trimestre_display(),
            'analyses': {
                'selectionnees': analyse.get_analyses_selectionnees() if analyse else [],
                'total': len([f for f in analyse.get_analyses_selectionnees()]) if analyse else 0
            },
            'recommandations': {
                'selectionnees': recommandations.get_recommandations_selectionnees() if recommandations else [],
                'total': len([f for f in recommandations.get_recommandations_selectionnees()]) if recommandations else 0
            }
        }
        
        return rapport
    
    @classmethod
    def analyser_classe_complete(cls, classe_id: int, trimestre: str, annee_scolaire: str, appreciation_generale: str = ""):
        """
        Analyse automatiquement tous les élèves d'une classe avec une appréciation générale
        
        Args:
            classe_id: ID de la classe
            trimestre: Trimestre concerné
            annee_scolaire: Année scolaire
            appreciation_generale: Appréciation générale à appliquer à tous
        """
        evaluations = EvaluationMaternelle.objects.filter(
            classe_id=classe_id,
            trimestre=trimestre,
            annee_scolaire=annee_scolaire
        )
        
        resultats = []
        for evaluation in evaluations:
            analyse, recommandations = cls.appliquer_analyse_automatique(evaluation, appreciation_generale)
            rapport = cls.generer_rapport_analyse(evaluation)
            resultats.append(rapport)
        
        return resultats


def analyser_appreciations_maternelles(request):
    """
    Vue Django pour analyser les appréciations depuis une interface web
    """
    if request.method == 'POST':
        appreciation_text = request.POST.get('appreciation_text', '')
        evaluation_id = request.POST.get('evaluation_id')
        
        if evaluation_id:
            try:
                evaluation = EvaluationMaternelle.objects.get(id=evaluation_id)
                analyse, recommandations = AnalyseMaternelleIntelligente.appliquer_analyse_automatique(
                    evaluation, appreciation_text
                )
                
                return JsonResponse({
                    'success': True,
                    'message': 'Analyse effectuée avec succès',
                    'analyses': analyse.get_analyses_selectionnees(),
                    'recommandations': recommandations.get_recommandations_selectionnees()
                })
            except EvaluationMaternelle.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Évaluation non trouvée'})
        
        # Analyse simple sans sauvegarde
        analyses, recommandations = AnalyseMaternelleIntelligente.analyser_appreciation(appreciation_text)
        
        return JsonResponse({
            'success': True,
            'analyses': analyses,
            'recommandations': recommandations
        })
    
    return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})


# Fonctions utilitaires pour l'intégration
def get_mots_cles_analyse():
    """Retourne tous les mots-clés d'analyse pour l'interface"""
    return AnalyseMaternelleIntelligente.MOTS_CLES_ANALYSE


def get_mots_cles_recommandations():
    """Retourne tous les mots-clés de recommandations pour l'interface"""
    return AnalyseMaternelleIntelligente.MOTS_CLES_RECOMMANDATIONS
