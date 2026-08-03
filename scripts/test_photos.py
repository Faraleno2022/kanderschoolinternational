#!/usr/bin/env python
import os
import sys
import django

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from load_env import *
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ecole_moderne.settings')
django.setup()

from eleves.models import Eleve

# Chercher un élève avec photo
eleves = Eleve.objects.all()[:5]
print(f"Total élèves trouvés: {len(eleves)}")
print()

for eleve in eleves:
    print(f"Élève: {eleve.nom} {eleve.prenom}")
    print(f"  - ID: {eleve.id}")
    if hasattr(eleve, 'photo') and eleve.photo:
        print(f"  - Photo existe: {eleve.photo}")
        try:
            photo_path = eleve.photo.path
            print(f"  - Chemin complet: {photo_path}")
            print(f"  - Fichier existe: {os.path.exists(photo_path)}")
        except Exception as e:
            print(f"  - Erreur accès photo: {e}")
    else:
        print(f"  - Pas de photo")
    print()
