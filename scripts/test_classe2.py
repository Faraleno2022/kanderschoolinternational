import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ecole_moderne.settings')
import django
django.setup()

from notes.models import NoteMensuelle, MatiereNote, ClasseNote
from eleves.models import Classe, Eleve

print("=== TEST CLASSE 2 ET MATIERE 11 ===")

# Classe ID=2
classe = Classe.objects.filter(id=2).first()
print(f"Classe ID=2: {classe}")

# Matiere ID=11
matiere = MatiereNote.objects.filter(id=11).first()
print(f"Matiere ID=11: {matiere}")

if classe:
    eleves = Eleve.objects.filter(classe=classe, statut='ACTIF')
    print(f"Eleves actifs: {eleves.count()}")
    ids = list(eleves.values_list('id', flat=True))
    print(f"IDs élèves: {ids[:10]}")
    
    # Notes pour ces élèves
    notes_all = NoteMensuelle.objects.filter(eleve_id__in=ids)
    print(f"Notes totales pour ces élèves: {notes_all.count()}")
    
    # Notes NOVEMBRE
    notes_nov = NoteMensuelle.objects.filter(eleve_id__in=ids, mois='NOVEMBRE')
    print(f"Notes NOVEMBRE: {notes_nov.count()}")
    
    # Afficher les mois distincts pour ces élèves
    mois_distincts = NoteMensuelle.objects.filter(eleve_id__in=ids).values_list('mois', flat=True).distinct()
    print(f"Mois distincts: {list(mois_distincts)}")
    
    # Afficher quelques notes
    for n in notes_all[:5]:
        print(f"  - Eleve={n.eleve_id}, Matiere={n.matiere_id}, Mois='{n.mois}', Note={n.note}")

print("\n=== TOUTES LES CLASSES ===")
for c in Classe.objects.all()[:10]:
    nb = Eleve.objects.filter(classe=c, statut='ACTIF').count()
    print(f"  ID={c.id}, Nom='{c.nom}', Eleves={nb}")

print("\n=== TOUTES LES MATIERES ===")
for m in MatiereNote.objects.all()[:10]:
    print(f"  ID={m.id}, Nom='{m.nom}', Classe={m.classe.nom if m.classe else 'N/A'}")
