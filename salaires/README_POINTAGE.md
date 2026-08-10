# 📋 Module de Pointage des Enseignants

## Vue d'ensemble

Le module de pointage permet de suivre la présence quotidienne des enseignants avec un suivi détaillé des heures de travail, des absences et des retards.

---

## 🎯 Fonctionnalités

### Pointage Quotidien
- ✅ Pointage multiple d'enseignants en une seule action
- ✅ 6 statuts disponibles : PRÉSENT, ABSENT, RETARD, CONGÉ, MALADIE, PERMISSION
- ✅ Enregistrement des heures d'arrivée et de départ
- ✅ Calcul automatique des heures travaillées
- ✅ Gestion des justificatifs et observations

### Statistiques et Rapports
- 📊 Statistiques en temps réel (présents, absents, retards)
- 📈 Rapport détaillé par enseignant et période
- 💾 Export CSV pour analyse externe
- 🔍 Filtres avancés (date, enseignant, statut)

### Sécurité
- 🔒 Accès réservé aux utilisateurs connectés
- 🏫 Filtrage automatique par école
- 👤 Traçabilité complète (qui a pointé, quand)
- ⏰ Horodatage automatique

---

## 📁 Structure des Fichiers

```
salaires/
├── models.py                    # Modèle PresenceEnseignant
├── views_presences.py           # Vues du pointage
├── forms.py                     # Formulaire PresenceForm
├── urls.py                      # URLs du pointage
├── admin.py                     # Interface admin Django
└── migrations/
    └── 0003_presenceenseignant.py

templates/salaires/presences/
├── liste.html                   # Liste des présences
├── pointer.html                 # Interface de pointage
├── modifier.html                # Modification d'un pointage
├── supprimer.html               # Confirmation de suppression
└── rapport.html                 # Rapport détaillé
```

---

## 🔗 URLs Disponibles

| URL | Vue | Description |
|-----|-----|-------------|
| `/salaires/presences/` | `liste_presences` | Liste avec filtres et stats |
| `/salaires/presences/pointer/` | `pointer_presence` | Interface de pointage |
| `/salaires/presences/<id>/modifier/` | `modifier_presence` | Modification |
| `/salaires/presences/<id>/supprimer/` | `supprimer_presence` | Suppression |
| `/salaires/presences/rapport/` | `rapport_presences` | Rapport détaillé |
| `/salaires/presences/export/csv/` | `export_presences_csv` | Export CSV |

---

## 💾 Modèle de Données

### PresenceEnseignant

```python
class PresenceEnseignant(models.Model):
    enseignant = ForeignKey(Enseignant)
    date = DateField()
    statut = CharField(choices=STATUT_CHOICES)
    
    # Heures
    heure_arrivee = TimeField(null=True, blank=True)
    heure_depart = TimeField(null=True, blank=True)
    heures_travaillees = DecimalField(null=True, blank=True)
    
    # Détails
    observations = TextField(blank=True)
    justifie = BooleanField(default=False)
    
    # Métadonnées
    date_creation = DateTimeField(auto_now_add=True)
    date_modification = DateTimeField(auto_now=True)
    pointe_par = ForeignKey(User, null=True)
    
    class Meta:
        unique_together = ['enseignant', 'date']
        ordering = ['-date', 'enseignant__nom']
```

**Contraintes** :
- Un seul pointage par enseignant et par jour
- Index optimisés sur `(enseignant, date)` et `(date, statut)`

---

## 🎨 Vues Principales

### 1. `liste_presences(request)`
Liste des présences avec filtres et statistiques.

**Filtres** :
- Date début / Date fin
- Enseignant
- Statut

**Statistiques** :
- Total pointages
- Présents, Absents, Retards
- Total heures travaillées

### 2. `pointer_presence(request)`
Interface de pointage multiple.

**Fonctionnalités** :
- Sélection de la date
- Checkbox pour sélectionner les enseignants
- Formulaire pour chaque enseignant
- Enregistrement en masse

### 3. `rapport_presences(request)`
Rapport détaillé par enseignant.

**Données** :
- Nombre de présences par type
- Total heures travaillées
- Absences injustifiées
- Totaux globaux

### 4. `export_presences_csv(request)`
Export CSV des présences.

**Format** :
```csv
Date,Enseignant,Statut,Heure arrivée,Heure départ,Heures travaillées,Justifié,Observations
10/10/2025,LENO FARA,Présent,08:00,16:00,8.00,Non,
```

---

## 📝 Formulaire

### PresenceForm

```python
class PresenceForm(forms.ModelForm):
    class Meta:
        model = PresenceEnseignant
        fields = [
            'enseignant', 'date', 'statut',
            'heure_arrivee', 'heure_depart', 'heures_travaillees',
            'observations', 'justifie'
        ]
```

**Validation** :
- Date obligatoire
- Statut obligatoire
- Heures optionnelles mais recommandées pour les présents
- Calcul automatique des heures si arrivée/départ fournis

---

## 🔧 Utilisation

### Pointer la Présence

```python
# Dans la vue pointer_presence
if request.method == 'POST':
    date_pointage = request.POST.get('date')
    enseignants_ids = request.POST.getlist('enseignants')
    
    for ens_id in enseignants_ids:
        statut = request.POST.get(f'statut_{ens_id}')
        # ... autres champs
        
        PresenceEnseignant.objects.update_or_create(
            enseignant_id=ens_id,
            date=date_pointage,
            defaults={
                'statut': statut,
                'pointe_par': request.user,
                # ... autres champs
            }
        )
```

### Générer un Rapport

```python
# Récupérer les présences
presences = PresenceEnseignant.objects.filter(
    enseignant__ecole=user_school_obj,
    date__gte=date_debut,
    date__lte=date_fin
)

# Statistiques par enseignant
from collections import defaultdict
rapport = defaultdict(lambda: {
    'presents': 0,
    'absents': 0,
    'retards': 0,
    'total_heures': Decimal('0'),
})

for presence in presences:
    ens = presence.enseignant
    if presence.statut == 'PRESENT':
        rapport[ens]['presents'] += 1
    # ... autres statuts
```

---

## 🧪 Tests

### Script de Test des URLs

```bash
python test_pointage_urls.py
```

Vérifie :
- Configuration des URLs
- Accessibilité du modèle
- Présence des enseignants
- Statistiques des présences

### Script de Création de Données de Test

```bash
python creer_donnees_test_pointage.py
```

Crée :
- 7 jours de pointages
- Données variées (présents, absents, retards, congés)
- Heures de travail réalistes

---

## 🎓 Interface Admin Django

**URL** : `/admin/salaires/presenceenseignant/`

**Fonctionnalités** :
- Liste avec tous les champs
- Filtres : statut, date, justification, école
- Recherche par nom d'enseignant
- Hiérarchie par date
- Édition en masse
- Métadonnées automatiques

---

## 📊 Exemples de Requêtes

### Présences du jour

```python
from datetime import date
from salaires.models import PresenceEnseignant

presences_aujourd_hui = PresenceEnseignant.objects.filter(
    date=date.today()
)
```

### Absences injustifiées

```python
absences_injustifiees = PresenceEnseignant.objects.filter(
    statut='ABSENT',
    justifie=False
)
```

### Total heures par enseignant

```python
from django.db.models import Sum

heures_par_enseignant = PresenceEnseignant.objects.values(
    'enseignant__nom', 'enseignant__prenoms'
).annotate(
    total_heures=Sum('heures_travaillees')
)
```

### Rapport mensuel

```python
from datetime import date
from django.db.models import Count, Q

debut_mois = date.today().replace(day=1)
fin_mois = date.today()

rapport = PresenceEnseignant.objects.filter(
    date__gte=debut_mois,
    date__lte=fin_mois
).aggregate(
    total=Count('id'),
    presents=Count('id', filter=Q(statut='PRESENT')),
    absents=Count('id', filter=Q(statut='ABSENT')),
    retards=Count('id', filter=Q(statut='RETARD')),
)
```

---

## 🚀 Déploiement

### Migration

```bash
python manage.py makemigrations salaires
python manage.py migrate salaires
```

### Collecte des Fichiers Statiques

```bash
python manage.py collectstatic
```

### Vérification

```bash
python manage.py check
python test_pointage_urls.py
```

---

## 📖 Documentation

- **Guide utilisateur** : `GUIDE_POINTAGE_ENSEIGNANTS.md`
- **Ce README** : Documentation technique
- **Code source** : Commentaires dans les fichiers

---

## 🔄 Évolutions Futures

### Fonctionnalités Potentielles

- [ ] Notifications automatiques pour absences répétées
- [x] Intégration avec le calcul des salaires au taux horaire
- [ ] Pointage biométrique ou par badge
- [ ] Application mobile pour pointage
- [ ] Graphiques de présence
- [ ] Export PDF des rapports
- [ ] Alertes pour retards fréquents
- [ ] Validation hiérarchique des pointages

### Améliorations Techniques

- [ ] Cache des statistiques
- [ ] Optimisation des requêtes avec select_related
- [ ] API REST pour intégration externe
- [ ] Tests unitaires complets
- [ ] Documentation API

---

## 📞 Support

Pour toute question :
1. Consultez `GUIDE_POINTAGE_ENSEIGNANTS.md`
2. Vérifiez les logs Django
3. Utilisez les scripts de test
4. Contactez l'administrateur système

---

## ✅ Checklist de Déploiement

- [x] Modèle créé et migré
- [x] Vues implémentées
- [x] URLs configurées
- [x] Templates créés
- [x] Formulaire validé
- [x] Admin Django configuré
- [x] Tests créés
- [x] Documentation rédigée
- [x] Déployé sur GitHub

---

**Système de pointage opérationnel et prêt à l'emploi !** 🎉
