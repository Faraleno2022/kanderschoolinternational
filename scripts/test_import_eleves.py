"""
Script de test pour vérifier le système d'importation des élèves
"""
import os
import sys
import django

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ecole_moderne.settings')
django.setup()

from eleves.models import Classe, Eleve, Responsable
from eleves.import_eleves import (
    generer_template_eleves, 
    lire_fichier_eleves,
    exporter_liste_eleves,
    ImportElevesValidator,
    ImportElevesProcessor
)
import pandas as pd

def test_generation_template():
    """Test la génération du template Excel"""
    print("\n" + "="*60)
    print("TEST 1: Génération du template Excel")
    print("="*60)
    
    try:
        df = generer_template_eleves()
        
        print(f"✅ Template généré avec {len(df)} lignes d'exemple")
        print(f"📋 Colonnes: {list(df.columns)}")
        
        # Vérifier les colonnes obligatoires
        colonnes_obligatoires = ['Prénom', 'Nom', 'Sexe', 'Date de Naissance', 
                                 'Lieu de Naissance', 'Nom du Père/Tuteur', 
                                 'Prénom du Père/Tuteur', 'Téléphone Principal', 'Adresse']
        
        manquantes = [c for c in colonnes_obligatoires if c not in df.columns]
        if manquantes:
            print(f"❌ Colonnes manquantes: {manquantes}")
        else:
            print("✅ Toutes les colonnes obligatoires sont présentes")
        
        return True
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return False

def test_classes_disponibles():
    """Test les classes disponibles pour l'importation"""
    print("\n" + "="*60)
    print("TEST 2: Classes disponibles")
    print("="*60)
    
    classes = Classe.objects.all().order_by('annee_scolaire', 'nom')[:10]
    
    print(f"📚 {classes.count()} classes trouvées")
    
    for classe in classes:
        eleves_count = Eleve.objects.filter(classe=classe, statut='ACTIF').count()
        print(f"   - {classe.nom} ({classe.annee_scolaire}): {eleves_count} élèves")
    
    return classes.exists()

def test_eleves_importes():
    """Vérifie les élèves existants dans la base"""
    print("\n" + "="*60)
    print("TEST 3: Élèves existants dans la base")
    print("="*60)
    
    total_eleves = Eleve.objects.count()
    eleves_actifs = Eleve.objects.filter(statut='ACTIF').count()
    
    print(f"📊 Total élèves: {total_eleves}")
    print(f"✅ Élèves actifs: {eleves_actifs}")
    
    # Afficher quelques élèves
    eleves = Eleve.objects.select_related('classe', 'responsable_principal')[:5]
    
    print(f"\n👥 Exemples d'élèves:")
    for eleve in eleves:
        resp = eleve.responsable_principal
        print(f"   - {eleve.matricule}: {eleve.prenom} {eleve.nom}")
        print(f"     Classe: {eleve.classe.nom if eleve.classe else 'N/A'}")
        print(f"     Responsable: {resp.prenom} {resp.nom} ({resp.telephone})" if resp else "     Responsable: N/A")
    
    return total_eleves > 0

def test_export_eleves():
    """Test l'export des élèves d'une classe"""
    print("\n" + "="*60)
    print("TEST 4: Export des élèves d'une classe")
    print("="*60)
    
    # Trouver une classe avec des élèves
    classe = Classe.objects.annotate(
        nb_eleves=django.db.models.Count('eleves', filter=django.db.models.Q(eleves__statut='ACTIF'))
    ).filter(nb_eleves__gt=0).first()
    
    if not classe:
        print("⚠️ Aucune classe avec des élèves trouvée")
        return False
    
    print(f"📚 Classe: {classe.nom}")
    
    try:
        df = exporter_liste_eleves(classe.id)
        
        print(f"✅ Export généré avec {len(df)} élèves")
        print(f"📋 Colonnes: {list(df.columns)}")
        
        if len(df) > 0:
            print(f"\n👤 Premier élève exporté:")
            print(f"   Matricule: {df.iloc[0]['Matricule']}")
            print(f"   Nom: {df.iloc[0]['Prénom']} {df.iloc[0]['Nom']}")
            print(f"   Téléphone: {df.iloc[0]['Téléphone Principal']}")
        
        return True
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return False

def test_affichage_liste_eleves():
    """Vérifie que les élèves sont bien affichés dans la liste"""
    print("\n" + "="*60)
    print("TEST 5: Affichage des élèves dans la liste")
    print("="*60)
    
    # Simuler ce que fait la vue liste_eleves
    eleves = Eleve.objects.select_related(
        'classe', 'responsable_principal', 'responsable_secondaire'
    ).filter(statut='ACTIF').order_by('classe__nom', 'nom', 'prenom')[:10]
    
    print(f"📋 {eleves.count()} élèves récupérés pour affichage")
    
    for eleve in eleves:
        print(f"\n👤 {eleve.matricule}: {eleve.prenom} {eleve.nom}")
        print(f"   Classe: {eleve.classe.nom if eleve.classe else 'N/A'}")
        print(f"   Sexe: {eleve.sexe}")
        print(f"   Date naissance: {eleve.date_naissance}")
        print(f"   Lieu naissance: {eleve.lieu_naissance}")
        
        if eleve.responsable_principal:
            resp = eleve.responsable_principal
            print(f"   Père/Tuteur: {resp.prenom} {resp.nom} - Tél: {resp.telephone}")
        
        if eleve.responsable_secondaire:
            resp2 = eleve.responsable_secondaire
            print(f"   Mère: {resp2.prenom} {resp2.nom}")
    
    return eleves.exists()

def test_responsables():
    """Vérifie les responsables dans la base"""
    print("\n" + "="*60)
    print("TEST 6: Responsables dans la base")
    print("="*60)
    
    total_resp = Responsable.objects.count()
    print(f"📊 Total responsables: {total_resp}")
    
    # Afficher quelques responsables
    responsables = Responsable.objects.all()[:5]
    
    for resp in responsables:
        eleves_count = Eleve.objects.filter(
            django.db.models.Q(responsable_principal=resp) | 
            django.db.models.Q(responsable_secondaire=resp)
        ).count()
        print(f"   - {resp.prenom} {resp.nom} ({resp.telephone}): {eleves_count} élève(s)")
    
    return total_resp > 0

def main():
    print("\n" + "🔍 "*20)
    print("VÉRIFICATION DU SYSTÈME D'IMPORTATION DES ÉLÈVES")
    print("🔍 "*20)
    
    import django.db.models
    
    # Tests
    test_generation_template()
    test_classes_disponibles()
    test_eleves_importes()
    test_export_eleves()
    test_affichage_liste_eleves()
    test_responsables()
    
    print("\n" + "="*60)
    print("RÉSUMÉ")
    print("="*60)
    
    total_eleves = Eleve.objects.filter(statut='ACTIF').count()
    total_classes = Classe.objects.count()
    total_resp = Responsable.objects.count()
    
    print(f"✅ {total_eleves} élèves actifs dans la base")
    print(f"✅ {total_classes} classes disponibles")
    print(f"✅ {total_resp} responsables enregistrés")
    
    print("\n📌 URLs disponibles:")
    print("   - /eleves/importer/ : Interface d'importation")
    print("   - /eleves/template-eleves/ : Téléchargement du template")
    print("   - /eleves/ : Liste des élèves")
    print("   - /eleves/classes/ : Gestion des classes")
    print("   - /eleves/exporter/classe/{id}/ : Export d'une classe")

if __name__ == '__main__':
    main()
