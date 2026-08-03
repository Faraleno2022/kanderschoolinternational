"""
Test de la récupération des notes pour saisir_notes avec les données locales
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ecole_moderne.settings')
import django
django.setup()

from notes.models import NoteMensuelle, MatiereNote, ClasseNote
from eleves.models import Classe, Eleve

print("=" * 60)
print("TEST SAISIR_NOTES AVEC DONNÉES LOCALES")
print("=" * 60)

# Trouver une classe avec des élèves
classe = Classe.objects.filter(eleves__statut='ACTIF').distinct().first()
if not classe:
    print("Aucune classe avec des élèves actifs!")
    exit()

print(f"\nClasse: {classe.nom} (ID={classe.id})")

# Trouver les élèves
eleves = Eleve.objects.filter(classe=classe, statut='ACTIF')
eleves_ids = list(eleves.values_list('id', flat=True))
print(f"Élèves actifs: {eleves.count()}")
print(f"IDs: {eleves_ids[:5]}...")

# Trouver une matière pour cette classe
classe_note = ClasseNote.objects.filter(nom__iexact=classe.nom).first()
if not classe_note:
    classe_note = ClasseNote.objects.filter(nom__icontains=classe.nom.split()[0]).first()

if classe_note:
    print(f"\nClasseNote correspondante: {classe_note.nom} (ID={classe_note.id})")
    matiere = MatiereNote.objects.filter(classe=classe_note).first()
    if matiere:
        print(f"Matière: {matiere.nom} (ID={matiere.id})")
    else:
        print("Aucune matière trouvée!")
        matiere = None
else:
    print("Aucune ClasseNote correspondante!")
    matiere = None

# Vérifier les notes existantes
print("\n--- Notes existantes pour ces élèves ---")
notes_all = NoteMensuelle.objects.filter(eleve_id__in=eleves_ids)
print(f"Total notes: {notes_all.count()}")

# Par mois
mois_list = ['OCTOBRE', 'NOVEMBRE', 'DECEMBRE', 'JANVIER', 'FEVRIER', 'MARS']
for mois in mois_list:
    count = NoteMensuelle.objects.filter(eleve_id__in=eleves_ids, mois=mois).count()
    if count > 0:
        print(f"  {mois}: {count} notes")

# Simuler la requête de saisir_notes
print("\n--- Simulation requête saisir_notes ---")
periode = 'NOVEMBRE'
annee_scolaire = classe.annee_scolaire if hasattr(classe, 'annee_scolaire') else ''

if matiere:
    # Requête comme dans saisir_notes
    notes_mensuelles_qs = NoteMensuelle.objects.filter(
        matiere=matiere,
        mois=periode,
        eleve_id__in=eleves_ids
    )
    print(f"Notes pour matière={matiere.nom}, mois={periode}: {notes_mensuelles_qs.count()}")
    
    # Avec année scolaire
    if annee_scolaire:
        notes_mensuelles_qs2 = notes_mensuelles_qs.filter(annee_scolaire=annee_scolaire)
        print(f"Avec filtre année scolaire ({annee_scolaire}): {notes_mensuelles_qs2.count()}")
    
    # Construire le notes_map comme dans la vue
    notes_map = {}
    for n in notes_mensuelles_qs:
        notes_map[n.eleve_id] = {
            'note': float(n.note) if n.note is not None else None,
            'absent': bool(n.absent),
        }
    
    print(f"\nNotes map généré: {len(notes_map)} entrées")
    for eleve_id, data in list(notes_map.items())[:3]:
        print(f"  Élève {eleve_id}: note={data['note']}, absent={data['absent']}")

# Test du calcul de bulletin
print("\n--- Test calcul bulletin ---")
if matiere and eleves.exists():
    from notes.calculs_moyennes import calculer_moyenne_matiere
    
    eleve = eleves.first()
    print(f"Test pour élève: {eleve.prenom} {eleve.nom}")
    
    # Test mensuel
    result = calculer_moyenne_matiere(eleve, matiere, 'NOVEMBRE', 'mensuel')
    print(f"Résultat mensuel NOVEMBRE: {result}")
    
    # Test avec OCTOBRE
    result2 = calculer_moyenne_matiere(eleve, matiere, 'OCTOBRE', 'mensuel')
    print(f"Résultat mensuel OCTOBRE: {result2}")

print("\n" + "=" * 60)
print("FIN DU TEST")
print("=" * 60)
