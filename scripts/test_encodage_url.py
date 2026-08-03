#!/usr/bin/env python
"""
Analyse de l'encodage URL pour comprendre le problème
"""

import urllib.parse

# Différentes possibilités
tests = [
    ("1 0874", "Espace normal"),
    ("1\u00A0874", "Espace insécable direct"),
    ("1%C2%A0874", "URL encodée"),
    ("1%20A0874", "URL avec espace normal"),
]

print("🔍 ANALYSE D'ENCODAGE")
print("=" * 50)

for url, description in tests:
    print(f"\n{description}:")
    print(f"  Original: {repr(url)}")
    
    if url.startswith("1%"):
        decoded = urllib.parse.unquote(url)
        print(f"  Décodé: {repr(decoded)}")
        print(f"  Longueur: {len(decoded)}")
        for i, char in enumerate(decoded):
            print(f"    Position {i}: '{char}' (U+{ord(char):04X})")
    else:
        encoded = urllib.parse.quote(url)
        print(f"  Encodé: {encoded}")
        decoded = urllib.parse.unquote(encoded)
        print(f"  Re-décodé: {repr(decoded)}")

print("\n🎯 SCÉNARIO RÉEL:")
# Ce qui s'est probablement passé:
# 1. Quelqu'un a tapé "1 0874" dans un formulaire
# 2. Le navigateur a encodé l'espace en %C2%A0 (UTF-8 NBSP)
# 3. Django reçoit "1%C2%A0874" et le décode en "1\xa0874"

original_tape = "1 0874"
encoded_browser = urllib.parse.quote(original_tape, safe='')
print(f"  Tapé au clavier: {repr(original_tape)}")
print(f"  Encodé par navigateur: {encoded_browser}")
decoded = urllib.parse.unquote(encoded_browser)
print(f"  Reçu par Django: {repr(decoded)}")

# Test avec différents espaces
print("\n🧪 TESTS AVEC DIFFÉRENTS ESPACES:")
espaces = [" ", "\t", "\n", "\r", "\u00A0", "\u2000", "\u2001"]
for space in espaces:
    test_str = f"1{space}0874"
    encoded = urllib.parse.quote(test_str, safe='')
    decoded = urllib.parse.unquote(encoded)
    print(f"  {repr(space):<8}: {encoded:<15} → {repr(decoded)}")
