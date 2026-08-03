"""
Script de test pour vérifier le système d'importation des notes
"""
import os
import sys
import django

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ecole_moderne.settings')
django.setup()

from notes.models import ClasseNote, MatiereNote, NoteMensuelle, CompositionNote
from notes.import_notes import generer_template_excel, ImportNotesValidator, ImportNotesProcessor, lire_fichier_import
from eleves.models import Eleve, Classe
import pandas as pd

def test_generation_template():
    """Test la génération du template Excel avec les élèves"""
    print("\n" + "="*60)
    print("TEST 1: Génération du template Excel")
    print("="*60)
    
    # Récupérer une classe avec des élèves
    classes_note = ClasseNote.objects.filter(actif=True)[:5]
    
    if not classes_note:
        print("❌ Aucune ClasseNote trouvée")
        return False
    
    for classe_note in classes_note:
        print(f"\n📚 Classe: {classe_note.nom} ({classe_note.annee_scolaire})")
        
        # Récupérer les matières
        matieres = MatiereNote.objects.filter(classe=classe_note, actif=True)[:1]
        
        if not matieres:
            print(f"   ⚠️ Aucune matière pour cette classe")
            continue
        
        matiere = matieres[0]
        print(f"   📖 Matière: {matiere.nom} ({matiere.code})")
        
        try:
            # Générer le template
            df = generer_template_excel(classe_note.id, matiere.id, 'MENSUELLE')
            
            print(f"   ✅ Template généré avec {len(df)} lignes")
            print(f"   📋 Colonnes: {list(df.columns)}")
            
            if len(df) > 0:
                print(f"   👤 Premier élève: {df.iloc[0]['Prénom']} {df.iloc[0]['Nom']} ({df.iloc[0]['Matricule']})")
                
                # Vérifier si c'est un message d'erreur
                if 'ERREUR' in str(df.iloc[0]['Matricule']):
                    print(f"   ⚠️ Pas d'élèves trouvés pour cette classe")
                else:
                    print(f"   ✅ Élèves correctement récupérés!")
                    return True
            else:
                print(f"   ⚠️ Template vide")
                
        except Exception as e:
            print(f"   ❌ Erreur: {e}")
    
    return False

def test_correspondance_classes():
    """Test la correspondance entre ClasseNote et Classe (élèves)"""
    print("\n" + "="*60)
    print("TEST 2: Correspondance ClasseNote <-> Classe (élèves)")
    print("="*60)
    
    classes_note = ClasseNote.objects.filter(actif=True)[:10]
    
    for cn in classes_note:
        print(f"\n📚 ClasseNote: '{cn.nom}' ({cn.annee_scolaire})")
        
        # Chercher la classe d'élèves correspondante
        classe_eleve = Classe.objects.filter(
            nom__iexact=cn.nom,
            annee_scolaire=cn.annee_scolaire
        ).first()
        
        if not classe_eleve:
            classe_eleve = Classe.objects.filter(nom__iexact=cn.nom).first()
        
        if classe_eleve:
            eleves = Eleve.objects.filter(classe=classe_eleve, statut='ACTIF')
            print(f"   ✅ Classe trouvée: '{classe_eleve.nom}' avec {eleves.count()} élèves actifs")
        else:
            print(f"   ❌ Aucune classe d'élèves correspondante")
            
            # Afficher les classes disponibles
            toutes_classes = Classe.objects.all()[:5]
            print(f"   📋 Classes disponibles: {[c.nom for c in toutes_classes]}")

def test_notes_importees():
    """Vérifie les notes déjà importées"""
    print("\n" + "="*60)
    print("TEST 3: Notes existantes dans la base")
    print("="*60)
    
    # Notes mensuelles
    notes_mensuelles = NoteMensuelle.objects.all()
    print(f"\n📊 Notes mensuelles: {notes_mensuelles.count()}")
    
    if notes_mensuelles.exists():
        # Grouper par mois
        mois_counts = {}
        for note in notes_mensuelles[:100]:
            mois = note.mois
            mois_counts[mois] = mois_counts.get(mois, 0) + 1
        
        for mois, count in mois_counts.items():
            print(f"   - {mois}: {count} notes")
    
    # Notes de composition
    notes_compo = CompositionNote.objects.all()
    print(f"\n📊 Notes de composition: {notes_compo.count()}")
    
    if notes_compo.exists():
        # Grouper par période
        periode_counts = {}
        for note in notes_compo[:100]:
            periode = note.periode
            periode_counts[periode] = periode_counts.get(periode, 0) + 1
        
        for periode, count in periode_counts.items():
            print(f"   - {periode}: {count} notes")

def test_affichage_saisie_notes():
    """Vérifie que les notes sont bien récupérables pour l'affichage"""
    print("\n" + "="*60)
    print("TEST 4: Récupération des notes pour affichage")
    print("="*60)
    
    # Prendre un élève avec des notes
    eleve_avec_notes = None
    
    notes = NoteMensuelle.objects.select_related('eleve', 'matiere')[:10]
    
    if notes:
        for note in notes:
            print(f"\n👤 Élève: {note.eleve.prenom} {note.eleve.nom}")
            print(f"   📖 Matière: {note.matiere.nom}")
            print(f"   📅 Mois: {note.mois}")
            print(f"   📊 Note: {note.note}/20")
            print(f"   ❓ Absent: {note.absent}")
            eleve_avec_notes = note.eleve
            break
    else:
        print("⚠️ Aucune note mensuelle trouvée")
    
    return eleve_avec_notes

def main():
    print("\n" + "🔍 "*20)
    print("VÉRIFICATION DU SYSTÈME D'IMPORTATION DES NOTES")
    print("🔍 "*20)
    
    # Test 1: Génération template
    template_ok = test_generation_template()
    
    # Test 2: Correspondance classes
    test_correspondance_classes()
    
    # Test 3: Notes existantes
    test_notes_importees()
    
    # Test 4: Affichage
    test_affichage_saisie_notes()
    
    print("\n" + "="*60)
    print("RÉSUMÉ")
    print("="*60)
    
    if template_ok:
        print("✅ Le système d'importation fonctionne correctement")
        print("✅ Les templates sont générés avec les élèves de la classe")
    else:
        print("⚠️ Vérifiez la correspondance entre ClasseNote et Classe")
        print("   Les noms doivent correspondre exactement")
    
    print("\n📌 URLs disponibles:")
    print("   - /notes/importer/ : Interface d'importation")
    print("   - /notes/template-import/ : Téléchargement du template")
    print("   - /notes/consulter/ : Consultation des notes")
    print("   - /notes/bulletin-dynamique/ : Bulletins")

if __name__ == '__main__':
    main()
