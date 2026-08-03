#!/usr/bin/env python
"""
Script de test pour vérifier la configuration des matières de maternelle
"""

import os
import sys
import django

# Configuration de l'environnement Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ecole_moderne.settings')
django.setup()

from notes.models import ClasseNote, MatiereNote
from notes.matieres_defaut import MATIERES_MATERNELLE


def test_matieres_maternelle():
    """Teste la configuration des matières de maternelle"""
    
    print("🎨 TEST DES MATIÈRES MATERNELLE")
    print("=" * 60)
    
    # Afficher les matières configurées dans le fichier
    print("\n📋 MATIÈRES CONFIGURÉES DANS matieres_defaut.py :")
    for i, matiere in enumerate(MATIERES_MATERNELLE, 1):
        print(f"  {i:2d}. {matiere['nom']:<30} (Code: {matiere['code']})")
    
    # Vérifier les classes de maternelle existantes
    classes_maternelle = ClasseNote.objects.filter(niveau='MATERNELLE')
    
    print(f"\n🏫 CLASSES MATERNELLE TROUVÉES : {classes_maternelle.count()}")
    
    if not classes_maternelle.exists():
        print("  ⚠️  Aucune classe de maternelle trouvée dans la base de données")
        return
    
    total_matieres = 0
    total_classes_avec_matieres = 0
    
    for classe in classes_maternelle:
        matieres = MatiereNote.objects.filter(classe=classe)
        total_matieres += matieres.count()
        
        if matieres.exists():
            total_classes_avec_matieres += 1
            print(f"\n📚 {classe.nom} ({matieres.count()} matières) :")
            
            for matiere in matieres.order_by('nom'):
                print(f"  • {matiere.nom:<30} (Code: {matiere.code})")
        else:
            print(f"\n📚 {classe.nom} (0 matière) :")
            print("  ⚠️  Aucune matière configurée")
    
    # Résumé
    print("\n" + "=" * 60)
    print("📊 RÉSUMÉ :")
    print(f"  • Classes maternelle : {classes_maternelle.count()}")
    print(f"  • Classes avec matières : {total_classes_avec_matieres}")
    print(f"  • Total matières créées : {total_matieres}")
    print(f"  • Moyenne matières/classe : {total_matieres / classes_maternelle.count():.1f}" if classes_maternelle.count() > 0 else "  • Moyenne matières/classe : N/A")
    
    # Vérifier si toutes les matières attendues sont présentes
    if classes_maternelle.exists():
        codes_attendus = {m['code'] for m in MATIERES_MATERNELLE}
        
        for classe in classes_maternelle:
            matieres = MatiereNote.objects.filter(classe=classe)
            codes_existants = {m.code for m in matieres}
            
            manquants = codes_attendus - codes_existants
            en_trop = codes_existants - codes_attendus
            
            if manquants or en_trop:
                print(f"\n⚠️  {classe.nom} :")
                if manquants:
                    print(f"  Manquants : {', '.join(sorted(manquants))}")
                if en_trop:
                    print(f"  En trop : {', '.join(sorted(en_trop))}")
            else:
                print(f"\n✅ {classe.nom} : Configuration parfaite !")


if __name__ == "__main__":
    test_matieres_maternelle()
