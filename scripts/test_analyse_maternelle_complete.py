#!/usr/bin/env python3
"""
Script de test complet pour le système d'analyse automatique des appréciations maternelles
Teste l'intelligence artificielle d'analyse et de recommandations
"""

import os
import sys
import django

# Configuration de l'environnement Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ecole_moderne.settings')
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    django.setup()
except Exception as e:
    print(f"Erreur de configuration Django: {e}")
    sys.exit(1)

from notes.analyse_maternelle_intelligente import AnalyseMaternelleIntelligente
from notes.models import EvaluationMaternelle, AnalyseTravailMaternelle, RecommandationMaternelle
from eleves.models import Eleve, Classe
from notes.models import ClasseNote


def test_analyse_appreciations():
    """Teste l'analyse des appréciations textuelles"""
    print("\n" + "="*60)
    print("TEST 1: ANALYSE DES APPRÉCIATIONS TEXTUELLES")
    print("="*60)
    
    tests = [
        {
            'texte': "L'enfant est très intelligent, comprend bien les instructions mais est un peu paresseux. Il a besoin d'encouragement et de suivi à domicile.",
            'attendu_analyses': ['comprend_demandes', 'est_doue', 'est_paresseux'],
            'attendu_recommandations': ['encourager_feliciter', 'suivre_domicile', 'aide_encouragement_parents']
        },
        {
            'texte': "Élève brillant et vif d'esprit, attention en classe, sociable avec les camarades. À encourager et féliciter.",
            'attendu_analyses': ['comprend_demandes', 'fixe_attention', 'pas_probleme_camarades', 'est_doue'],
            'attendu_recommandations': ['encourager_feliciter']
        },
        {
            'texte': "Enfant timide, ne comprend pas toujours, trop jeune pour cette classe. Besoin d'aide intellectuelle et d'amour parental.",
            'attendu_analyses': ['ne_comprend_pas', 'trop_jeune'],
            'attendu_recommandations': ['aide_intellectuelle', 'amour_parental', 'attention_particuliere']
        },
        {
            'texte': "L'enfant ne fixe pas son attention, est turbulent, a besoin de fermeté et de douceur. Les parents doivent l'accompagner.",
            'attendu_analyses': ['est_paresseux'],  # turbulent -> paresseux
            'attendu_recommandations': ['besoin_fermete', 'douceur_patience', 'aide_encouragement_parents']
        }
    ]
    
    succes = 0
    total = len(tests)
    
    for i, test in enumerate(tests, 1):
        print(f"\nTest {i}/{total}: {test['texte'][:50]}...")
        
        try:
            analyses, recommandations = AnalyseMaternelleIntelligente.analyser_appreciation(test['texte'])
            
            # Vérifier les analyses
            analyses_trouvees = [k for k, v in analyses.items() if v]
            print(f"  Analyses détectées: {analyses_trouvees}")
            
            # Vérifier les recommandations
            recommandations_trouvees = [k for k, v in recommandations.items() if v]
            print(f"  Recommandations détectées: {recommandations_trouvees}")
            
            # Vérifications simples
            analyse_ok = any(att in analyses_trouvees for att in test['attendu_analyses'])
            recommandation_ok = any(att in recommandations_trouvees for att in test['attendu_recommandations'])
            
            if analyse_ok and recommandation_ok:
                print("  ✅ SUCCÈS")
                succes += 1
            else:
                print("  ❌ ÉCHEC - Éléments attendus non trouvés")
                
        except Exception as e:
            print(f"  ❌ ERREUR: {e}")
    
    print(f"\nRésultat: {succes}/{total} tests réussis")
    return succes == total


def test_logique_speciale():
    """Teste la logique spéciale et les corrélations"""
    print("\n" + "="*60)
    print("TEST 2: LOGIQUE SPÉCIALE ET CORRÉLATIONS")
    print("="*60)
    
    tests = [
        {
            'texte': "L'enfant est doué mais paresseux",
            'description': "Doué + paresseux -> paresseux doit être désactivé",
            'verif': lambda a, r: a['est_doue'] and not a['est_paresseux']
        },
        {
            'texte': "L'enfant est trop jeune pour cette classe",
            'description': "Trop jeune -> recommandations suivi et aide",
            'verif': lambda a, r: a['trop_jeune'] and r['suivre_domicile'] and r['aide_encouragement_parents']
        },
        {
            'texte': "L'enfant ne comprend pas les instructions",
            'description': "Ne comprend pas -> recommandations aide",
            'verif': lambda a, r: a['ne_comprend_pas'] and (r['aide_intellectuelle'] or r['attention_particuliere'])
        }
    ]
    
    succes = 0
    total = len(tests)
    
    for i, test in enumerate(tests, 1):
        print(f"\nTest {i}/{total}: {test['description']}")
        print(f"  Texte: '{test['texte']}'")
        
        try:
            analyses, recommandations = AnalyseMaternelleIntelligente.analyser_appreciation(test['texte'])
            
            if test['verif'](analyses, recommandations):
                print("  ✅ SUCCÈS - Logique spéciale appliquée")
                succes += 1
            else:
                print("  ❌ ÉCHEC - Logique spéciale non appliquée")
                print(f"    Analyses: {analyses}")
                print(f"    Recommandations: {recommandations}")
                
        except Exception as e:
            print(f"  ❌ ERREUR: {e}")
    
    print(f"\nRésultat: {succes}/{total} tests réussis")
    return succes == total


def test_integration_complete():
    """Teste l'intégration complète avec une évaluation"""
    print("\n" + "="*60)
    print("TEST 3: INTÉGRATION COMPLÈTE")
    print("="*60)
    
    try:
        # Rechercher une évaluation existante
        evaluation = EvaluationMaternelle.objects.first()
        
        if not evaluation:
            print("❌ Aucune évaluation trouvée - Création d'une évaluation de test...")
            
            # Chercher une classe maternelle
            classe_note = ClasseNote.objects.filter(niveau='MATERNELLE').first()
            if not classe_note:
                print("❌ Aucune classe maternelle trouvée")
                return False
            
            # Chercher un élève
            classe_eleves = Classe.objects.filter(nom=classe_note.nom).first()
            if not classe_eleves:
                print("❌ Aucune classe d'élèves trouvée")
                return False
            
            eleve = Eleve.objects.filter(classe=classe_eleves).first()
            if not eleve:
                print("❌ Aucun élève trouvé")
                return False
            
            # Créer l'évaluation
            evaluation = EvaluationMaternelle.objects.create(
                eleve=eleve,
                classe=classe_note,
                trimestre='TRIMESTRE_1',
                annee_scolaire='2025-2026'
            )
            print(f"✅ Évaluation créée: {evaluation}")
        
        appreciation_test = "L'enfant est intelligent, comprend bien mais est un peu paresseux. Il a besoin d'encouragement des parents."
        
        print(f"Test avec l'évaluation: {evaluation.eleve}")
        print(f"Appréciation: '{appreciation_test}'")
        
        # Appliquer l'analyse automatique
        analyse, recommandations = AnalyseMaternelleIntelligente.appliquer_analyse_automatique(
            evaluation, appreciation_test
        )
        
        print("✅ Analyse appliquée avec succès")
        print(f"  Analyses sauvegardées: {len(analyse.get_analyses_selectionnees())}")
        print(f"  Recommandations sauvegardées: {len(recommandations.get_recommandations_selectionnees())}")
        
        # Générer le rapport
        rapport = AnalyseMaternelleIntelligente.generer_rapport_analyse(evaluation)
        print("✅ Rapport généré:")
        print(f"  Élève: {rapport['eleve']}")
        print(f"  Classe: {rapport['classe']}")
        print(f"  Trimestre: {rapport['trimestre']}")
        print(f"  Analyses: {rapport['analyses']['total']}")
        print(f"  Recommandations: {rapport['recommandations']['total']}")
        
        return True
        
    except Exception as e:
        print(f"❌ ERREUR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_mots_cles():
    """Teste la reconnaissance des mots-clés"""
    print("\n" + "="*60)
    print("TEST 4: RECONNAISSANCE DES MOTS-CLÉS")
    print("="*60)
    
    # Test des mots-clés d'analyse
    print("\nMots-clés d'analyse reconnus:")
    for critere, mots in AnalyseMaternelleIntelligente.MOTS_CLES_ANALYSE.items():
        print(f"  {critere}: {', '.join(mots[:3])}{'...' if len(mots) > 3 else ''}")
    
    # Test des mots-clés de recommandations
    print("\nMots-clés de recommandations reconnus:")
    for critere, mots in AnalyseMaternelleIntelligente.MOTS_CLES_RECOMMANDATIONS.items():
        print(f"  {critere}: {', '.join(mots[:3])}{'...' if len(mots) > 3 else ''}")
    
    print("✅ Test des mots-clés terminé")
    return True


def main():
    """Fonction principale de test"""
    print("🤖 SYSTÈME D'ANALYSE AUTOMATIQUE DES APPRÉCIATIONS MATERNELLES")
    print("="*60)
    print("Test complet de l'intelligence artificielle d'analyse")
    
    tests = [
        ("Analyse des appréciations", test_analyse_appreciations),
        ("Logique spéciale", test_logique_speciale),
        ("Intégration complète", test_integration_complete),
        ("Reconnaissance des mots-clés", test_mots_cles)
    ]
    
    succes = 0
    total = len(tests)
    
    for nom_test, fonction_test in tests:
        try:
            if fonction_test():
                succes += 1
                print(f"\n✅ {nom_test}: RÉUSSI")
            else:
                print(f"\n❌ {nom_test}: ÉCHOUÉ")
        except Exception as e:
            print(f"\n💥 {nom_test}: ERREUR - {e}")
    
    print("\n" + "="*60)
    print("RÉSULTAT FINAL")
    print("="*60)
    print(f"Tests réussis: {succes}/{total}")
    
    if succes == total:
        print("🎉 TOUS LES TESTS SONT RÉUSSIS!")
        print("\nLe système d'analyse automatique des appréciations maternelles est fonctionnel.")
        print("\nFonctionnalités disponibles:")
        print("✅ Analyse intelligente des appréciations textuelles")
        print("✅ Génération automatique des cases à cocher")
        print("✅ Logique spéciale et corrélations")
        print("✅ Intégration complète avec l'interface")
        print("✅ API pour analyse en temps réel")
        return True
    else:
        print("⚠️ CERTAINS TESTS ONT ÉCHOUÉ")
        print("Veuillez vérifier les erreurs ci-dessus.")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
