#!/usr/bin/env python
"""
Test détaillé du caractère problème
"""

# Test 1: Caractère dans le test original
test1 = "1\xa0874"
print("Test 1 (original):")
print(f"  Chaîne: {repr(test1)}")
for i, char in enumerate(test1):
    print(f"  Position {i}: '{char}' (U+{ord(char):04X})")

# Test 2: Caractère Unicode explicite  
test2 = "1\u00A0874"
print("\nTest 2 (Unicode explicite):")
print(f"  Chaîne: {repr(test2)}")
for i, char in enumerate(test2):
    print(f"  Position {i}: '{char}' (U+{ord(char):04X})")

# Test 3: URL décodée
import urllib.parse
test3 = urllib.parse.unquote("1%C2%A0874")
print("\nTest 3 (URL décodée):")
print(f"  Chaîne: {repr(test3)}")
for i, char in enumerate(test3):
    print(f"  Position {i}: '{char}' (U+{ord(char):04X})")

# Test avec notre fonction
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

print("\n🧪 TESTS AVEC NOTRE FONCTION:")
for i, (nom, test) in enumerate([("Test 1", test1), ("Test 2", test2), ("Test 3", test3)], 1):
    resultat = nettoyer_parametre_numerique(test)
    print(f"  {i}. {nom}: {test} → {resultat}")

# Test manuel
print("\n🔧 TEST MANUEL:")
param = test3
print(f"Original: {repr(param)}")
etape1 = re.sub(r'[\s\u00A0\u2000-\u200F\u2028-\u202F\u205F\u3000]', '', param)
print(f"Après regex: {repr(etape1)}")
etape2 = ''.join(c for c in etape1 if c.isdigit() or c == '-')
print(f"Après filtrage: {repr(etape2)}")
print(f"Final: {int(etape2) if etape2 else 'None'}")
