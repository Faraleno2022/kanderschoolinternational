from django import forms
from django.core.validators import RegexValidator
from .models import Eleve, Responsable, Classe, Ecole
from utilisateurs.utils import user_is_admin, user_school
from datetime import date

class ResponsableForm(forms.ModelForm):
    """Formulaire pour créer/modifier un responsable"""
    
    def __init__(self, *args, **kwargs):
        # Permettre le passage de l'utilisateur courant pour filtrage par école
        # Compatibilité: accepter 'user' ou 'utilisateur'
        self._current_user = kwargs.pop('user', None) or kwargs.pop('utilisateur', None)
        super().__init__(*args, **kwargs)
        # Rendre tous les champs optionnels au niveau du formulaire
        # La validation sera gérée manuellement dans la vue
        for field_name in self.fields:
            self.fields[field_name].required = False
        # Pré-remplir téléphone en local (8-9 chiffres) lors de la modification
        try:
            instance = getattr(self, 'instance', None)
            if instance and getattr(instance, 'pk', None):
                tel = getattr(instance, 'telephone', '') or ''
                if tel.startswith('+224'):
                    local = tel.replace('+224', '')
                    # Nettoyer pour ne garder que 8-9 derniers chiffres
                    import re
                    digits = re.sub(r'\D+', '', local)
                    self.fields['telephone'].initial = digits[-9:] if len(digits) > 9 else digits
        except Exception:
            # Ne pas bloquer le rendu du formulaire en cas d'anomalie
            pass
    
    class Meta:
        model = Responsable
        fields = ['prenom', 'nom', 'relation', 'telephone', 'email', 'adresse', 'profession']
        widgets = {
            'prenom': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Prénom du responsable'
            }),
            'nom': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nom du responsable'
            }),
            'relation': forms.Select(attrs={
                'class': 'form-select'
            }),
            # Saisie locale uniquement (sans +224). Normalisation côté serveur.
            'telephone': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'tel',
                'inputmode': 'numeric',
                'placeholder': '8–9 chiffres ou +224XXXXXXXXX',
                # Autoriser soit un numéro local (8-9 chiffres), soit un numéro avec indicatif 224 (avec ou sans +)
                'pattern': r'^(?:\+?224)?\d{8,9}$',
                'title': 'Entrez 8 à 9 chiffres (local) ou un numéro avec indicatif (+224XXXXXXXXX).'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'email@exemple.com'
            }),
            'adresse': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Adresse complète'
            }),
            'profession': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Profession (optionnel)'
            })
        }

    def clean_nom(self):
        """Convertir le nom en majuscules"""
        nom = self.cleaned_data.get('nom', '')
        return nom.upper() if nom else ''
    
    def clean_prenom(self):
        """Convertir le prénom en majuscules"""
        prenom = self.cleaned_data.get('prenom', '')
        return prenom.upper() if prenom else ''
    
    def clean_adresse(self):
        """Convertir l'adresse en majuscules"""
        adresse = self.cleaned_data.get('adresse', '')
        return adresse.upper() if adresse else ''
    
    def clean_profession(self):
        """Convertir la profession en majuscules"""
        profession = self.cleaned_data.get('profession', '')
        return profession.upper() if profession else ''
    
    def clean_telephone(self):
        """Accepte une saisie locale (8-9 chiffres) et normalise en +224XXXXXXXXX.
        Si l'utilisateur fournit déjà un numéro avec indicatif, on l'accepte et on le
        normalise également.
        """
        tel = self.cleaned_data.get('telephone', '') or ''
        import re
        # Retirer tout sauf chiffres
        digits = re.sub(r'\D+', '', tel)
        if not digits:
            return ''
        # Si déjà au format international commençant par 224 et longueur 11-12
        if digits.startswith('224') and len(digits) in (11, 12):
            # Conserver les 8 ou 9 derniers chiffres comme local
            local = digits[-9:] if len(digits) == 12 else digits[-8:]
            return f'+224{local}'
        # Sinon, on attend un numéro local de 8 ou 9 chiffres
        if len(digits) not in (8, 9):
            raise forms.ValidationError("Numéro invalide. Entrez 8 à 9 chiffres sans indicatif.")
        return f'+224{digits}'

class EleveForm(forms.ModelForm):
    """Formulaire pour créer/modifier un élève"""
    
    # Champ pour saisie manuelle du matricule
    saisie_manuelle_matricule = forms.BooleanField(
        required=False,
        label="Saisir manuellement le matricule",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'saisie-manuelle-matricule'})
    )
    
    # Champs pour les responsables
    responsable_principal_nouveau = forms.BooleanField(
        required=False,
        label="Créer un nouveau responsable principal",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    responsable_secondaire_nouveau = forms.BooleanField(
        required=False,
        label="Créer un nouveau responsable secondaire",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    class Meta:
        model = Eleve
        fields = [
            'matricule', 'prenom', 'nom', 'sexe', 'date_naissance',
            'lieu_naissance', 'photo', 'classe', 'date_inscription',
            'statut', 'responsable_principal', 'responsable_secondaire',
            'groupe_sanguin', 'allergies', 'maladies_chroniques',
            'traitement_en_cours', 'observations_medicales',
        ]
        widgets = {
            'matricule': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Généré automatiquement (ex: PN3-001)',
                'id': 'matricule-input'
            }),
            'prenom': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Prénom de l\'élève',
                'required': True
            }),
            'nom': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nom de l\'élève',
                'required': True
            }),
            'sexe': forms.Select(attrs={
                'class': 'form-select',
                'required': True
            }),
            'date_naissance': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
                'required': False
            }, format='%Y-%m-%d'),
            'lieu_naissance': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Lieu de naissance (optionnel)'
            }),
            'photo': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'classe': forms.Select(attrs={
                'class': 'form-select',
                'required': True
            }),
            'date_inscription': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
                # Ne pas forcer "required" en HTML pour éviter les blocages côté navigateur
            }, format='%Y-%m-%d'),
            'statut': forms.Select(attrs={
                'class': 'form-select'
            }),
            'responsable_principal': forms.Select(attrs={
                'class': 'form-select'
            }),
            'responsable_secondaire': forms.Select(attrs={
                'class': 'form-select'
            }),
            'groupe_sanguin': forms.Select(attrs={
                'class': 'form-select'
            }),
            'allergies': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Ex: Arachides, pénicilline... (laisser vide si aucune)'
            }),
            'maladies_chroniques': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Ex: Asthme, épilepsie... (laisser vide si aucune)'
            }),
            'traitement_en_cours': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Médicaments et posologie (laisser vide si aucun)'
            }),
            'observations_medicales': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Régime alimentaire particulier, informations utiles pour l\'équipe...'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        # Permettre le passage de l'utilisateur courant pour filtrage par école
        # Compatibilité: accepter 'user' ou 'utilisateur'
        self._current_user = kwargs.pop('user', None) or kwargs.pop('utilisateur', None)
        super().__init__(*args, **kwargs)
        
        # Définir la date d'inscription par défaut à aujourd'hui (optionnel)
        if not self.instance.pk:
            # En création: proposer aujourd'hui par défaut mais ne pas rendre obligatoire
            self.fields['date_inscription'].initial = date.today()
            self.fields['date_inscription'].required = False
        else:
            # En modification: ne pas rendre obligatoire et garder la valeur existante
            self.fields['date_inscription'].required = False
            # Forcer la valeur initiale à celle de l'instance pour éviter les faux changements
            if self.instance.date_inscription:
                self.fields['date_inscription'].initial = self.instance.date_inscription
        
        # Rendre les champs facultatifs sauf: sexe, prenom, nom, classe
        # Ces 4 champs restent obligatoires
        champs_obligatoires = ['sexe', 'prenom', 'nom', 'classe']
        champs_facultatifs = ['date_naissance', 'lieu_naissance', 'photo', 'date_inscription', 'statut']
        for field_name in champs_facultatifs:
            if field_name in self.fields:
                self.fields[field_name].required = False
        
        # Filtrer les classes aux écoles validées par défaut
        try:
            self.fields['classe'].queryset = Classe.objects.filter(ecole__etat='VALIDE').order_by('ecole__nom', 'niveau', 'nom')
        except Exception:
            self.fields['classe'].queryset = Classe.objects.all().order_by('ecole__nom', 'niveau', 'nom')

        # Matricule: par défaut non requis et lecture seule (généré automatiquement au save())
        if 'matricule' in self.fields:
            self.fields['matricule'].required = False
            # Par défaut, le matricule est en lecture seule
            if not self.data.get('saisie_manuelle_matricule'):
                try:
                    self.fields['matricule'].widget.attrs['readonly'] = 'readonly'
                    self.fields['matricule'].widget.attrs['placeholder'] = 'Généré automatiquement (ex: PN3-001)'
                except Exception:
                    pass
            else:
                # Si saisie manuelle activée, rendre le champ éditable et requis
                self.fields['matricule'].required = True
                self.fields['matricule'].widget.attrs['placeholder'] = 'Saisir le matricule (ex: PN3-001)'
                self.fields['matricule'].widget.attrs.pop('readonly', None)

        # Rendre responsable_principal optionnel si on crée un nouveau responsable
        # La validation sera gérée dans la vue
        self.fields['responsable_principal'].required = False
        self.fields['responsable_secondaire'].required = False
        
        # Ordonner et filtrer les responsables par école pour les non-admins
        try:
            if self._current_user and not user_is_admin(self._current_user):
                ecole = user_school(self._current_user)
                if ecole:
                    from django.db.models import Q
                    # Utiliser Q objects au lieu de union() pour permettre order_by()
                    qs_filtre = Responsable.objects.filter(
                        Q(eleves_principal__classe__ecole=ecole) | 
                        Q(eleves_secondaire__classe__ecole=ecole)
                    ).distinct().order_by('nom', 'prenom')
                    self.fields['responsable_principal'].queryset = qs_filtre
                    self.fields['responsable_secondaire'].queryset = qs_filtre
                else:
                    # Si l'utilisateur n'a pas d'école associée, ne proposer aucun responsable existant
                    self.fields['responsable_principal'].queryset = Responsable.objects.none()
                    self.fields['responsable_secondaire'].queryset = Responsable.objects.none()
            else:
                # Admin: accès à tous
                self.fields['responsable_principal'].queryset = Responsable.objects.all().order_by('nom', 'prenom')
                self.fields['responsable_secondaire'].queryset = Responsable.objects.all().order_by('nom', 'prenom')
        except Exception:
            # Fallback de sécurité
            self.fields['responsable_principal'].queryset = Responsable.objects.all().order_by('nom', 'prenom')
            self.fields['responsable_secondaire'].queryset = Responsable.objects.all().order_by('nom', 'prenom')
        self.fields['responsable_secondaire'].required = False
    
    def clean_nom(self):
        """Convertir le nom en majuscules"""
        nom = self.cleaned_data.get('nom', '')
        return nom.upper() if nom else ''
    
    def clean_prenom(self):
        """Convertir le prénom en majuscules"""
        prenom = self.cleaned_data.get('prenom', '')
        return prenom.upper() if prenom else ''

    def clean_lieu_naissance(self):
        """Convertir le lieu de naissance en majuscules"""
        lieu_naissance = self.cleaned_data.get('lieu_naissance', '')
        return lieu_naissance.upper() if lieu_naissance else ''

    def clean_matricule(self):
        """Valider le matricule saisi manuellement"""
        matricule = self.cleaned_data.get('matricule', '')
        saisie_manuelle = self.data.get('saisie_manuelle_matricule')
        
        if saisie_manuelle and matricule:
            # Vérifier que le matricule n'existe pas déjà (sauf pour l'instance actuelle en modification)
            qs = Eleve.objects.filter(matricule=matricule)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(f"Le matricule '{matricule}' existe déjà pour un autre élève.")
        elif matricule and not saisie_manuelle:
            # Si un matricule existe mais pas de saisie manuelle, vérifier l'unicité quand même
            qs = Eleve.objects.filter(matricule=matricule)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("Ce matricule existe déjà.")
        
        # Autoriser vide: le modèle le générera au save()
        return matricule or ''
    
    def clean_date_naissance(self):
        date_naissance = self.cleaned_data.get('date_naissance')
        if date_naissance:
            # La validation détaillée d'âge dépend de la classe et est effectuée dans clean()
            # Ici, on retourne simplement la valeur.
            return date_naissance
        return date_naissance

    def clean_date_inscription(self):
        """Conserver la date d'inscription existante lors d'une modification si le champ est laissé vide."""
        valeur = self.cleaned_data.get('date_inscription')
        # En création, on retourne la valeur telle quelle (la validation de required est gérée plus haut)
        if not self.instance.pk:
            return valeur
        # En modification: si vide/non fournie, on garde l'ancienne valeur pour éviter NULL
        if not valeur:
            return self.instance.date_inscription
        return valeur

    def clean(self):
        """Validation croisée tenant compte de la classe pour l'âge minimal.
        - Garderie (niveau == 'GARDERIE'): autoriser 5 à 11 mois inclus.
        - Autres niveaux: 2 à 25 ans.
        """
        cleaned = super().clean()
        date_naissance = cleaned.get('date_naissance')
        classe = cleaned.get('classe')

        if not date_naissance:
            return cleaned

        # Calcul de l'âge en mois précis
        today = date.today()
        months = (today.year - date_naissance.year) * 12 + (today.month - date_naissance.month)
        if today.day < date_naissance.day:
            months -= 1

        # Si classe sélectionnée et c'est la Garderie, appliquer règle spéciale
        niveau = getattr(classe, 'niveau', None)
        if niveau == 'GARDERIE':
            # Autorisé: de 4 mois à 36 mois inclus (≤ 3 ans)
            if months < 4 or months > 36:
                self.add_error(
                    'date_naissance',
                    "Pour la Garderie, l'âge doit être compris entre 4 mois et 3 ans inclus."
                )
            return cleaned

        # Règles générales pour les autres niveaux: 2 à 25 ans
        age_ans = months // 12
        if age_ans < 2:
            self.add_error('date_naissance', "L'élève doit avoir au moins 2 ans pour ce niveau.")
        elif age_ans > 25:
            self.add_error('date_naissance', "L'âge de l'élève semble incorrect (supérieur à 25 ans).")

        return cleaned

class RechercheEleveForm(forms.Form):
    """Formulaire de recherche simple (zone unique multi-critères)."""
    recherche = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Rechercher un élève...'
        })
    )

class ClasseForm(forms.ModelForm):
    """Formulaire pour créer/modifier une classe"""
    
    class Meta:
        model = Classe
        fields = ['ecole', 'nom', 'niveau', 'annee_scolaire', 'capacite_max']
        widgets = {
            'ecole': forms.Select(attrs={
                'class': 'form-select'
            }),
            'nom': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nom de la classe (ex: 6ème A)'
            }),
            'niveau': forms.Select(attrs={
                'class': 'form-select'
            }),
            'annee_scolaire': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '2024-2025',
                'pattern': r'^\d{4}-\d{4}$'
            }),
            'capacite_max': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '50'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Limiter aux écoles validées uniquement
        try:
            self.fields['ecole'].queryset = Ecole.objects.filter(etat='VALIDE').order_by('nom')
        except Exception:
            pass
        # Définir l'année scolaire par défaut
        if not self.instance.pk:
            current_year = date.today().year
            if date.today().month >= 9:  # Année scolaire commence en septembre
                self.fields['annee_scolaire'].initial = f"{current_year}-{current_year + 1}"
            else:
                self.fields['annee_scolaire'].initial = f"{current_year - 1}-{current_year}"
    
    def clean_nom(self):
        """Convertir le nom de la classe en majuscules"""
        nom = self.cleaned_data.get('nom', '')
        return nom.upper() if nom else ''
    
    def clean_annee_scolaire(self):
        annee_scolaire = self.cleaned_data.get('annee_scolaire')
        if annee_scolaire:
            # Vérifier le format YYYY-YYYY
            import re
            if not re.match(r'^\d{4}-\d{4}$', annee_scolaire):
                raise forms.ValidationError("Format attendu: YYYY-YYYY (ex: 2024-2025)")
            
            # Vérifier que la deuxième année suit la première
            annees = annee_scolaire.split('-')
            if int(annees[1]) != int(annees[0]) + 1:
                raise forms.ValidationError("La deuxième année doit suivre la première (ex: 2024-2025)")
        
        return annee_scolaire


class EcoleForm(forms.ModelForm):
    """Formulaire public (hors admin) pour créer une école avec upload du logo.
    Utilisé par la vue creer_ecole.
    """
    class Meta:
        model = Ecole
        fields = ['nom', 'adresse', 'telephone', 'email', 'directeur', 'ire', 'dpe', 'desee', 'logo']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Nom de l'école"}),
            'adresse': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Adresse complète'}),
            'telephone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+224XXXXXXXXX'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@exemple.com'}),
            'directeur': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom du directeur'}),
            'ire': forms.TextInput(attrs={'class': 'form-control', 'placeholder': "IRE (ex: Conakry)"}),
            'dpe': forms.TextInput(attrs={'class': 'form-control', 'placeholder': "DPE (ex: Dixinn)"}),
            'desee': forms.TextInput(attrs={'class': 'form-control', 'placeholder': "DESEE (ex: Commune)"}),
            'logo': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Rendre l'email optionnel côté formulaire (le modèle l'autorise déjà)
        self.fields['email'].required = False
    
    def clean_nom(self):
        """Convertir le nom de l'école en majuscules"""
        nom = self.cleaned_data.get('nom', '')
        return nom.upper() if nom else ''
    
    def clean_adresse(self):
        """Convertir l'adresse en majuscules"""
        adresse = self.cleaned_data.get('adresse', '')
        return adresse.upper() if adresse else ''
    
    def clean_directeur(self):
        """Convertir le nom du directeur en majuscules"""
        directeur = self.cleaned_data.get('directeur', '')
        return directeur.upper() if directeur else ''
    
    def clean_ire(self):
        """Convertir l'IRE en majuscules"""
        ire = self.cleaned_data.get('ire', '')
        return ire.upper() if ire else ''
    
    def clean_dpe(self):
        """Convertir le DPE en majuscules"""
        dpe = self.cleaned_data.get('dpe', '')
        return dpe.upper() if dpe else ''
    
    def clean_desee(self):
        """Convertir le DESEE en majuscules"""
        desee = self.cleaned_data.get('desee', '')
        return desee.upper() if desee else ''
