#!/usr/bin/env python
"""
Test complet de la solution de nettoyage et correction des IDs
"""

import os
import sys
import django

# Configuration de l'environnement Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ecole_moderne.settings')
django.setup()

from notes.models import ClasseNote
from eleves.models import Eleve

def test_solution_complete():
    """Test la solution complète de nettoyage et correction"""
    
    def nettoyer_parametre_numerique(param):
        """Nettoie un paramètre numérique en supprimant les espaces et caractères invalides"""
        if not param:
            return None
        
        # Convertir en string si nécessaire
        if not isinstance(param, str):
            param = str(param)
        
        # Remplacer tous les types d'espaces (y compris les espaces insécables) par rien
        import re
        param_nettoye = re.sub(r'[\s\u00A0\u2000-\u200F\u2028-\u202F\u205F\u3000]', '', param)
        
        # Supprimer les caractères non numériques sauf le signe moins
        param_nettoye = ''.join(c for c in param_nettoye if c.isdigit() or c == '-')
        
        try:
            return int(param_nettoye) if param_nettoye else None
        except ValueError:
            return None
    
    def valider_et_corriger_eleve_id(eleve_id, classe_id):
        """Valide et corrige l'ID de l'élève si nécessaire"""
        if not eleve_id or not isinstance(eleve_id, int):
            return None
        
        # Essayer de trouver l'élève avec l'ID donné
        try:
            return Eleve.objects.get(pk=eleve_id)
        except Eleve.DoesNotExist:
            # Si l'élève n'existe pas, essayer des variations
            # Cas spécial : si l'ID ressemble à 1xxx mais qu'on a 1 xxx (espace)
            if eleve_id > 1000 and eleve_id < 20000:
                # Essayer avec un zéro supplémentaire au milieu
                str_id = str(eleve_id)
                if len(str_id) >= 4:  # Au moins 4 chiffres
                    with_zero = int(f"{str_id[0]}0{str_id[1:]}")
                    try:
                        return Eleve.objects.get(pk=with_zero)
                    except Eleve.DoesNotExist:
                        pass
            
            # Essayer avec des zéros devant
            padded_id = int(f"{eleve_id:05d}")  # Au moins 5 chiffres
            try:
                return Eleve.objects.get(pk=padded_id)
            except Eleve.DoesNotExist:
                pass
            
            return None
    
    print("🧪 TEST COMPLET DE LA SOLUTION")
    print("=" * 60)
    
    # Récupérer quelques élèves réels pour tester
    eleves_reels = Eleve.objects.all()[:5]
    print(f"📋 ÉLÈVES RÉELS POUR TEST :")
    for eleve in eleves_reels:
        print(f"  • ID: {eleve.pk}, Nom: {eleve.prenom} {eleve.nom}")
    
    print("\n🎯 TESTS DE NETTOYAGE :")
    tests_nettoyage = [
        ("10874", 10874, "ID normal"),
        ("1\u00A0874", 1874, "Espace insécable (erreur originale)"),
        ("10\u00A0874", 10874, "Espace insécable avec 0"),
        ("1 0874", 10874, "Espace normal"),
        ("0010874", 10874, "Zéros devant"),
    ]
    
    for entree, attendu, description in tests_nettoyage:
        resultat = nettoyer_parametre_numerique(entree)
        statut = "✅" if resultat == attendu else "❌"
        print(f"  {statut} {description:<30} {repr(entree)} → {resultat}")
    
    print("\n🔧 TESTS DE CORRECTION :")
    if eleves_reels:
        eleve_test = eleves_reels[0]
        vrai_id = eleve_test.pk
        
        # Simuler l'erreur : 10874 → 1 0874
        id_avec_espace = f"{str(vrai_id)[0]}\u00A0{str(vrai_id)[2:]}" if len(str(vrai_id)) >= 3 else str(vrai_id)
        id_nettoye = nettoyer_parametre_numerique(id_avec_espace)
        
        print(f"  Élève test : {eleve_test.prenom} {eleve_test.nom} (ID réel: {vrai_id})")
        print(f"  ID avec espace : {repr(id_avec_espace)}")
        print(f"  ID nettoyé : {id_nettoye}")
        
        eleve_trouve = valider_et_corriger_eleve_id(id_nettoye, None)
        if eleve_trouve:
            print(f"  ✅ Élève trouvé : ID {eleve_trouve.pk}")
            if eleve_trouve.pk == vrai_id:
                print(f"  ✅ Correction réussie !")
            else:
                print(f"  ⚠️  Mauvais élève trouvé")
        else:
            print(f"  ❌ Élève non trouvé")
    
    print("\n🎯 TEST SPÉCIFIQUE - ERREUR RAPPORTÉE :")
    import urllib.parse
    url_erreur = "1%C2%A0874"
    decoded_erreur = urllib.parse.unquote(url_erreur)
    id_nettoye = nettoyer_parametre_numerique(decoded_erreur)
    
    print(f"  URL erreur : {url_erreur}")
    print(f"  Décodé : {repr(decoded_erreur)}")
    print(f"  Nettoyé : {id_nettoye}")
    
    # Tester avec un ID réel qui pourrait correspondre
    eleve_possible = valider_et_corriger_eleve_id(id_nettoye, None)
    if eleve_possible:
        print(f"  ✅ Élève possible trouvé : ID {eleve_possible.pk} ({eleve_possible.prenom} {eleve_possible.nom})")
    else:
        print(f"  ❌ Aucun élève trouvé pour cet ID")
    
    print("\n" + "=" * 60)
    print("🏁 TEST TERMINÉ")

if __name__ == "__main__":
    test_solution_complete()
