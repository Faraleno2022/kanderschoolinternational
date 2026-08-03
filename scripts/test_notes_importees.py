"""
Script de test pour diagnostiquer les problèmes de notes importées
"""
import os
import sys
import django

# Configuration Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ecole_moderne.settings')
django.setup()

from django.db import connection
from notes.models import NoteMensuelle, CompositionNote, MatiereNote, ClasseNote
from eleves.models import Eleve, Classe

def test_notes_importees():
    """Test complet des notes importées"""
    print("=" * 60)
    print("DIAGNOSTIC DES NOTES IMPORTÉES")
    print("=" * 60)
    
    # 1. Vérifier les tables
    print("\n1. VÉRIFICATION DES TABLES")
    print("-" * 40)
    
    try:
        nb_notes_mensuelles = NoteMensuelle.objects.count()
        print(f"   ✓ NoteMensuelle: {nb_notes_mensuelles} enregistrements")
    except Exception as e:
        print(f"   ✗ NoteMensuelle: ERREUR - {e}")
        nb_notes_mensuelles = 0
    
    try:
        nb_compositions = CompositionNote.objects.count()
        print(f"   ✓ CompositionNote: {nb_compositions} enregistrements")
    except Exception as e:
        print(f"   ✗ CompositionNote: ERREUR - {e}")
        nb_compositions = 0
    
    # 2. Afficher quelques notes mensuelles
    print("\n2. EXEMPLES DE NOTES MENSUELLES")
    print("-" * 40)
    
    if nb_notes_mensuelles > 0:
        notes = NoteMensuelle.objects.select_related('eleve', 'matiere')[:5]
        for n in notes:
            print(f"   - Élève ID={n.eleve_id}, Matière ID={n.matiere_id}, Mois={n.mois}, Note={n.note}, Année={n.annee_scolaire}")
    else:
        print("   Aucune note mensuelle trouvée")
    
    # 3. Afficher quelques compositions
    print("\n3. EXEMPLES DE COMPOSITIONS")
    print("-" * 40)
    
    if nb_compositions > 0:
        compos = CompositionNote.objects.select_related('eleve', 'matiere')[:5]
        for c in compos:
            print(f"   - Élève ID={c.eleve_id}, Matière ID={c.matiere_id}, Période={c.periode}, Note={c.note}, Année={c.annee_scolaire}")
    else:
        print("   Aucune composition trouvée")
    
    # 4. Vérifier les classes et matières
    print("\n4. CLASSES ET MATIÈRES")
    print("-" * 40)
    
    classes_note = ClasseNote.objects.all()[:5]
    for c in classes_note:
        nb_matieres = MatiereNote.objects.filter(classe=c).count()
        print(f"   - ClasseNote ID={c.id}, Nom='{c.nom}', Année={c.annee_scolaire}, Matières={nb_matieres}")
    
    # 5. Vérifier les élèves
    print("\n5. ÉLÈVES")
    print("-" * 40)
    
    classes_eleve = Classe.objects.all()[:5]
    for c in classes_eleve:
        nb_eleves = Eleve.objects.filter(classe=c, statut='ACTIF').count()
        print(f"   - Classe ID={c.id}, Nom='{c.nom}', Année={c.annee_scolaire}, Élèves actifs={nb_eleves}")
    
    # 6. Test de récupération pour saisir_notes
    print("\n6. TEST RÉCUPÉRATION POUR SAISIR_NOTES")
    print("-" * 40)
    
    if nb_notes_mensuelles > 0:
        # Prendre une note existante pour tester
        note_test = NoteMensuelle.objects.select_related('eleve', 'matiere').first()
        eleve = note_test.eleve
        matiere = note_test.matiere
        mois = note_test.mois
        annee = note_test.annee_scolaire
        
        print(f"   Test avec: Élève={eleve.prenom} {eleve.nom} (ID={eleve.id})")
        print(f"              Matière={matiere.nom} (ID={matiere.id})")
        print(f"              Mois={mois}, Année={annee}")
        
        # Simuler la requête de saisir_notes
        classe_eleve = eleve.classe
        if classe_eleve:
            eleves_classe = Eleve.objects.filter(classe=classe_eleve, statut='ACTIF')
            eleves_ids = list(eleves_classe.values_list('id', flat=True))
            print(f"   Classe élève: {classe_eleve.nom} (ID={classe_eleve.id})")
            print(f"   Élèves dans la classe: {len(eleves_ids)}")
            print(f"   IDs élèves: {eleves_ids[:10]}...")
            
            # Vérifier si l'élève est dans la liste
            if eleve.id in eleves_ids:
                print(f"   ✓ L'élève {eleve.id} EST dans la liste des élèves de la classe")
            else:
                print(f"   ✗ L'élève {eleve.id} N'EST PAS dans la liste des élèves de la classe!")
            
            # Tester la requête de notes
            notes_query = NoteMensuelle.objects.filter(
                matiere=matiere,
                mois=mois,
                eleve_id__in=eleves_ids
            )
            print(f"   Notes trouvées avec filtre eleve_id__in: {notes_query.count()}")
            
            # Sans filtre année scolaire
            notes_query2 = NoteMensuelle.objects.filter(
                matiere=matiere,
                mois=mois,
                annee_scolaire=annee,
                eleve_id__in=eleves_ids
            )
            print(f"   Notes trouvées avec filtre année scolaire: {notes_query2.count()}")
        else:
            print(f"   ✗ L'élève n'a pas de classe assignée!")
    
    # 7. Vérifier la correspondance ClasseNote <-> Classe
    print("\n7. CORRESPONDANCE CLASSENOTE <-> CLASSE")
    print("-" * 40)
    
    if classes_note.exists():
        for cn in classes_note[:3]:
            # Chercher la classe d'élèves correspondante
            classe_eleve = Classe.objects.filter(nom__iexact=cn.nom).first()
            if classe_eleve:
                print(f"   ✓ ClasseNote '{cn.nom}' -> Classe '{classe_eleve.nom}' (ID={classe_eleve.id})")
            else:
                # Essayer avec correspondance partielle
                classe_eleve = Classe.objects.filter(nom__icontains=cn.nom.split()[0]).first()
                if classe_eleve:
                    print(f"   ~ ClasseNote '{cn.nom}' -> Classe '{classe_eleve.nom}' (partiel)")
                else:
                    print(f"   ✗ ClasseNote '{cn.nom}' -> Aucune correspondance!")
    
    # 8. Test du calcul de bulletin
    print("\n8. TEST CALCUL BULLETIN")
    print("-" * 40)
    
    if nb_notes_mensuelles > 0:
        from notes.calculs_moyennes import calculer_moyenne_matiere
        
        note_test = NoteMensuelle.objects.select_related('eleve', 'matiere').first()
        eleve = note_test.eleve
        matiere = note_test.matiere
        mois = note_test.mois
        
        print(f"   Test calculer_moyenne_matiere pour:")
        print(f"   - Élève: {eleve.prenom} {eleve.nom}")
        print(f"   - Matière: {matiere.nom}")
        print(f"   - Période: {mois}")
        
        result = calculer_moyenne_matiere(eleve, matiere, mois, 'mensuel')
        print(f"   Résultat: {result}")
    
    print("\n" + "=" * 60)
    print("FIN DU DIAGNOSTIC")
    print("=" * 60)


if __name__ == '__main__':
    test_notes_importees()
