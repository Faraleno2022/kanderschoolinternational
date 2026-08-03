#!/usr/bin/env python
"""
Test de l'hypothèse du 0 manquant
"""

import urllib.parse
import re

def nettoyer_parametre_numerique(param):
    if not param:
        return None
    
    if not isinstance(param, str):
        param = str(param)
    
    param_nettoye = re.sub(r'[\s\u00A0\u2000-\u200F\u2028-\u202F\u205F\u3000]', '', param)
    param_nettoye = ''.join(c for c in param_nettoye if c.isdigit() or c == '-')
    
    try:
        return int(param_nettoye) if param_nettoye else None
    except ValueError:
        return None

print("🎯 TEST HYPOTHÈSE DU 0 MANQUANT")
print("=" * 50)

# Test avec 10 0874 (ce qui devrait être le cas)
original_correct = "10\u00A0874"  # "10 0874" avec espace insécable
encoded_correct = urllib.parse.quote(original_correct)
decoded_correct = urllib.parse.unquote(encoded_correct)

print(f"Original correct: {repr(original_correct)}")
print(f"Encodé: {encoded_correct}")
print(f"Décodé: {repr(decoded_correct)}")

resultat = nettoyer_parametre_numerique(decoded_correct)
print(f"Nettoyé: {resultat}")

# Test avec 1 0874 (ce qu'on a)
original_actuel = "1\u00A0874"
encoded_actuel = urllib.parse.quote(original_actuel)
decoded_actuel = urllib.parse.unquote(encoded_actuel)

print(f"\nOriginal actuel: {repr(original_actuel)}")
print(f"Encodé: {encoded_actuel}")
print(f"Décodé: {repr(decoded_actuel)}")

resultat_actuel = nettoyer_parametre_numerique(decoded_actuel)
print(f"Nettoyé: {resultat_actuel}")

print("\n🔍 ANALYSE:")
print("L'URL reçue est 1%C2%A0874 qui donne 1\xa0874")
print("Mais l'ID correct est probablement 10874")
print("Donc l'original devait être 10 0874 (avec espace)")

# Test de l'erreur exacte
print("\n❌ ERREUR EXACTE RAPPORTÉE:")
url_erreur = "1%C2%A0874"
decoded_erreur = urllib.parse.unquote(url_erreur)
print(f"URL: {url_erreur}")
print(f"Décodé: {repr(decoded_erreur)}")
resultat_erreur = nettoyer_parametre_numerique(decoded_erreur)
print(f"Nettoyé: {resultat_erreur}")
print(f"Attendu: 10874")
print(f"Correct: {resultat_erreur == 10874}")
