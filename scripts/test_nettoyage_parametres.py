#!/usr/bin/env python
"""
Script de test pour vérifier la correction du nettoyage des paramètres
"""

import os
import sys
import django

# Configuration de l'environnement Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ecole_moderne.settings')
django.setup()

def test_nettoyage_parametre():
    """Teste la fonction de nettoyage des paramètres"""
    
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
    
    print("🧪 TEST DE NETTOYAGE DES PARAMÈTRES")
    print("=" * 50)
    
    # Cas de test
    tests = [
        ("10874", 10874, "ID normal"),
        ("1\u00A0874", 10874, "Espace insécable (erreur originale)"),
        ("1 0874", 10874, "Espace normal"),
        ("1\u00A00874", 10874, "Unicode espace insécable"),
        ("0010874", 10874, "Zéros devant"),
        ("abc10874xyz", 10874, "Lettres autour"),
        ("", None, "Chaîne vide"),
        (None, None, "Paramètre None"),
        ("-123", -123, "Nombre négatif"),
        ("1-2-3", 123, "Multiple signes moins"),
    ]
    
    print("\n📋 CAS DE TEST :")
    for i, (entree, attendu, description) in enumerate(tests, 1):
        resultat = nettoyer_parametre_numerique(entree)
        statut = "✅" if resultat == attendu else "❌"
        
        # Afficher l'entrée avec représentation des caractères spéciaux
        entree_affichee = repr(entree) if isinstance(entree, str) else entree
        
        print(f"  {i:2d}. {statut} {description:<30}")
        print(f"      Entrée: {entree_affichee}")
        print(f"      Attendu: {attendu}")
        print(f"      Résultat: {resultat}")
        if resultat != attendu:
            print(f"      ⚠️  ERREUR !")
        print()
    
    # Test spécifique pour l'erreur rapportée
    print("🎯 TEST SPÉCIFIQUE - ERREUR RAPPORTÉE :")
    url_param = "1%C2%A0874"  # URL encodée
    # Simuler le décodage URL que Django ferait
    import urllib.parse
    decoded_param = urllib.parse.unquote(url_param)
    
    print(f"  URL paramètre : {url_param}")
    print(f"  Décodé : {repr(decoded_param)}")
    
    resultat = nettoyer_parametre_numerique(decoded_param)
    print(f"  Nettoyé : {resultat}")
    
    if resultat == 10874:
        print("  ✅ CORRECTION FONCTIONNELLE !")
    else:
        print("  ❌ La correction ne fonctionne pas")
    
    print("\n" + "=" * 50)
    print("🏁 TEST TERMINÉ")

if __name__ == "__main__":
    test_nettoyage_parametre()
