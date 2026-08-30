from django import forms
from django.core.exceptions import ValidationError
from .models import (
    AffectationClasse,
    AvanceSalaire,
    Enseignant,
    EtatSalaire,
    PeriodeSalaire,
    PresenceEnseignant,
    StatutEnseignant,
    TypeEnseignant,
)
from eleves.models import Ecole, Classe


class EnseignantForm(forms.ModelForm):
    """Formulaire pour créer/modifier un enseignant"""
    
    class Meta:
        model = Enseignant
        fields = [
            'nom', 'prenoms', 'telephone', 'adresse',
            'ecole', 'type_enseignant', 'statut', 
            'taux_horaire', 'salaire_fixe', 'heures_mensuelles', 'date_embauche'
        ]
        widgets = {
            'nom': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nom de famille'
            }),
            'prenoms': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Prénoms'
            }),
            'telephone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+224 XXX XX XX XX'
            }),
            'adresse': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Adresse complète'
            }),
            'ecole': forms.Select(attrs={
                'class': 'form-select'
            }),
            'type_enseignant': forms.Select(attrs={
                'class': 'form-select'
            }),
            'statut': forms.Select(attrs={
                'class': 'form-select'
            }),
            'taux_horaire': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Taux horaire en GNF',
                'step': '0.01'
            }),
            'salaire_fixe': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Salaire fixe en GNF',
                'step': '0.01'
            }),
            'heures_mensuelles': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Optionnel, ex. 120 heures',
                'step': '0.25',
                'min': '0'
            }),
            'date_embauche': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
        }
        labels = {
            'nom': 'Nom de famille *',
            'prenoms': 'Prénoms *',
            'telephone': 'Téléphone',
            'adresse': 'Adresse',
            'ecole': 'École *',
            'type_enseignant': 'Type d\'enseignant *',
            'statut': 'Statut',
            'taux_horaire': 'Taux horaire (GNF)',
            'salaire_fixe': 'Salaire fixe (GNF)',
            'heures_mensuelles': 'Heures mensuelles',
            'date_embauche': 'Date d\'embauche *',
        }
        help_texts = {
            'taux_horaire': 'Pour les enseignants du secondaire uniquement',
            'salaire_fixe': 'Pour garderie, maternelle, primaire, cadres et administrateurs',
            'heures_mensuelles': (
                "Optionnel : valeur proposée pour la saisie globale mensuelle. "
                "Les pointages arrivée/départ peuvent être utilisés à la place."
            ),
            'date_embauche': 'Date d\'entrée en fonction',
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Rendre certains champs obligatoires
        self.fields['nom'].required = True
        self.fields['prenoms'].required = True
        self.fields['ecole'].required = True
        self.fields['type_enseignant'].required = True
        self.fields['date_embauche'].required = True
        
        # Restreindre les écoles visibles selon l'utilisateur
        if self.user:
            from utilisateurs.utils import user_is_admin, user_school
            if not user_is_admin(self.user):
                ecole_user = user_school(self.user)
                if ecole_user:
                    self.fields['ecole'].queryset = Ecole.objects.filter(id=ecole_user.id)
                    self.fields['ecole'].initial = ecole_user
        
        # Définir le statut par défaut
        if not self.instance.pk:
            self.fields['statut'].initial = StatutEnseignant.ACTIF

    def clean(self):
        cleaned_data = super().clean()
        type_enseignant = cleaned_data.get('type_enseignant')
        taux_horaire = cleaned_data.get('taux_horaire')
        salaire_fixe = cleaned_data.get('salaire_fixe')
        heures_mensuelles = cleaned_data.get('heures_mensuelles')

        # Validation selon le type d'enseignant
        if type_enseignant == TypeEnseignant.SECONDAIRE:
            if not taux_horaire:
                raise ValidationError({
                    'taux_horaire': 'Le taux horaire est obligatoire pour les enseignants du secondaire.'
                })
            if salaire_fixe:
                cleaned_data['salaire_fixe'] = None  # Effacer le salaire fixe
        else:
            if not salaire_fixe:
                raise ValidationError({
                    'salaire_fixe': f'Le salaire fixe est obligatoire pour les enseignants de type {type_enseignant}.'
                })
            if taux_horaire:
                cleaned_data['taux_horaire'] = None  # Effacer le taux horaire
        
        # Validation des heures mensuelles
        if heures_mensuelles and heures_mensuelles <= 0:
            raise ValidationError({
                'heures_mensuelles': 'Le nombre d\'heures mensuelles doit être supérieur à 0.'
            })
        
        if heures_mensuelles and heures_mensuelles > 200:
            raise ValidationError({
                'heures_mensuelles': 'Le nombre d\'heures mensuelles ne peut pas dépasser 200 heures par mois.'
            })

        return cleaned_data

    def clean_telephone(self):
        telephone = self.cleaned_data.get('telephone')
        if telephone:
            # Validation basique du format téléphone guinéen
            telephone = telephone.replace(' ', '').replace('-', '')
            if not telephone.startswith('+224') and not telephone.startswith('224'):
                if len(telephone) == 9 and telephone.startswith(('6', '7')):
                    telephone = '+224' + telephone
                else:
                    raise ValidationError('Format de téléphone invalide. Utilisez le format guinéen.')
        return telephone


class AffectationClasseForm(forms.ModelForm):
    """Formulaire pour affecter un enseignant à une classe"""

    class Meta:
        model = AffectationClasse
        fields = [
            'classe', 'heures_par_semaine', 'matiere',
            'date_debut', 'date_fin', 'actif'
        ]
        widgets = {
            'classe': forms.Select(attrs={'class': 'form-select'}),
            'heures_par_semaine': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.25', 'min': '0'
            }),
            'matiere': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Mathématiques'}),
            'date_debut': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'date_fin': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'actif': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'classe': 'Classe *',
            'heures_par_semaine': 'Heures par semaine',
            'matiere': 'Matière',
            'date_debut': 'Date de début *',
            'date_fin': 'Date de fin',
            'actif': 'Active',
        }

    def __init__(self, *args, **kwargs):
        # Attendre un paramètre optionnel enseignant pour filtrer les classes
        self.enseignant = kwargs.pop('enseignant', None)
        super().__init__(*args, **kwargs)

        # IMPORTANT: fournir l'enseignant à l'instance dès l'init pour que
        # la validation du modèle (AffectationClasse.clean) puisse y accéder
        # pendant form.is_valid() sans déclencher RelatedObjectDoesNotExist.
        if self.enseignant is not None:
            try:
                self.instance.enseignant = self.enseignant
            except Exception:
                pass

        # Champs requis
        self.fields['classe'].required = True
        self.fields['date_debut'].required = True

        # Restreindre les classes à l'école de l'enseignant (année la plus récente)
        if self.enseignant and getattr(self.enseignant, 'ecole_id', None):
            qs = Classe.objects.filter(ecole_id=self.enseignant.ecole_id)
            annee_recente = (
                Classe.objects.filter(ecole_id=self.enseignant.ecole_id)
                .values_list('annee_scolaire', flat=True)
                .distinct().order_by('-annee_scolaire').first()
            )
            if annee_recente:
                qs = qs.filter(annee_scolaire=annee_recente)
            self.fields['classe'].queryset = qs
        else:
            self.fields['classe'].queryset = Classe.objects.none()

    def clean(self):
        cleaned_data = super().clean()
        if not self.enseignant:
            raise ValidationError('Enseignant requis pour créer une affectation.')

        # Validation spécifique aux enseignants du secondaire
        if self.enseignant.type_enseignant == TypeEnseignant.SECONDAIRE:
            if not cleaned_data.get('heures_par_semaine'):
                raise ValidationError({'heures_par_semaine': "Obligatoire pour les enseignants du secondaire."})

        # Vérifier cohérence des dates
        d_debut = cleaned_data.get('date_debut')
        d_fin = cleaned_data.get('date_fin')
        if d_debut and d_fin and d_fin < d_debut:
            raise ValidationError({'date_fin': 'La date de fin ne peut pas être antérieure à la date de début.'})

        return cleaned_data

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.enseignant:
            obj.enseignant = self.enseignant
        if commit:
            obj.save()
        return obj


class PresenceForm(forms.ModelForm):
    """Formulaire pour pointer/modifier une présence"""
    
    class Meta:
        model = PresenceEnseignant
        fields = [
            'enseignant', 'date', 'statut',
            'heure_arrivee', 'heure_depart', 'heures_travaillees',
            'observations', 'justifie'
        ]
        widgets = {
            'enseignant': forms.Select(attrs={'class': 'form-select'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'statut': forms.Select(attrs={'class': 'form-select'}),
            'heure_arrivee': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'heure_depart': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'heures_travaillees': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.25',
                'min': '0',
                'placeholder': 'Calculé automatiquement si vide'
            }),
            'observations': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Motif d\'absence, retard, etc.'
            }),
            'justifie': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'enseignant': 'Enseignant *',
            'date': 'Date *',
            'statut': 'Statut *',
            'heure_arrivee': 'Heure d\'arrivée',
            'heure_depart': 'Heure de départ',
            'heures_travaillees': 'Heures travaillées',
            'observations': 'Observations',
            'justifie': 'Absence/Retard justifié',
        }
    
    def __init__(self, *args, **kwargs):
        ecole = kwargs.pop('ecole', None)
        super().__init__(*args, **kwargs)
        
        # Filtrer les enseignants par école
        if ecole:
            self.fields['enseignant'].queryset = Enseignant.objects.filter(
                ecole=ecole,
                statut='ACTIF'
            ).order_by('nom', 'prenoms')
    
    def clean(self):
        cleaned_data = super().clean()
        heure_arrivee = cleaned_data.get('heure_arrivee')
        heure_depart = cleaned_data.get('heure_depart')
        heures_travaillees = cleaned_data.get('heures_travaillees')
        statut = cleaned_data.get('statut')

        if bool(heure_arrivee) != bool(heure_depart):
            raise ValidationError(
                "L'heure d'arrivée et l'heure de départ doivent être renseignées ensemble."
            )

        if statut in {'PRESENT', 'RETARD'}:
            if not (heure_arrivee and heure_depart) and not (
                heures_travaillees is not None and heures_travaillees > 0
            ):
                raise ValidationError(
                    "Renseignez les heures d'arrivée et de départ, ou le total travaillé."
                )

        if statut in {'ABSENT', 'CONGE', 'MALADIE'}:
            if heure_arrivee or heure_depart or (
                heures_travaillees is not None and heures_travaillees > 0
            ):
                raise ValidationError(
                    'Aucune heure travaillée ne peut être enregistrée pour ce statut.'
                )
        
        return cleaned_data


class EtatSalaireAjustementForm(forms.ModelForm):
    """Modification contrôlée des primes et retenues avant validation."""

    class Meta:
        model = EtatSalaire
        fields = ['primes', 'deductions', 'observations']
        widgets = {
            'primes': forms.NumberInput(attrs={
                'class': 'form-control', 'min': '0', 'step': '0.01'
            }),
            'deductions': forms.NumberInput(attrs={
                'class': 'form-control', 'min': '0', 'step': '0.01'
            }),
            'observations': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 4,
                'placeholder': 'Motif des primes ou retenues',
            }),
        }

    def clean(self):
        cleaned_data = super().clean()
        primes = cleaned_data.get('primes') or 0
        deductions = cleaned_data.get('deductions') or 0
        salaire_base = self.instance.salaire_base or 0
        montant_avances = self.instance.montant_avances or 0

        if deductions + montant_avances > salaire_base + primes:
            self.add_error(
                'deductions',
                'Le total des retenues et avances ne peut pas dépasser le salaire brut.',
            )

        return cleaned_data


class AvanceSalaireForm(forms.ModelForm):
    """Création et modification sécurisées d'une avance sur salaire."""

    approuver_immediatement = forms.BooleanField(
        required=False,
        initial=True,
        label='Approuver immédiatement cette avance',
        help_text='Si décoché, la demande restera en attente de validation.',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

    class Meta:
        model = AvanceSalaire
        fields = [
            'enseignant', 'periode', 'montant', 'date_avance',
            'mode_paiement', 'reference_paiement', 'motif', 'observations',
        ]
        widgets = {
            'enseignant': forms.Select(attrs={'class': 'form-select'}),
            'periode': forms.Select(attrs={'class': 'form-select'}),
            'montant': forms.NumberInput(attrs={
                'class': 'form-control', 'min': '1', 'step': '1',
                'placeholder': 'Montant en GNF',
            }),
            'date_avance': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'mode_paiement': forms.Select(attrs={'class': 'form-select'}),
            'reference_paiement': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'N° reçu ou référence externe',
            }),
            'motif': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': "Motif de l'avance",
            }),
            'observations': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        enseignants = Enseignant.objects.select_related('ecole').filter(
            statut=StatutEnseignant.ACTIF
        ).order_by('nom', 'prenoms')
        periodes = PeriodeSalaire.objects.select_related('ecole').filter(
            cloturee=False
        ).order_by('-annee', '-mois')
        if user is not None:
            from utilisateurs.utils import filter_by_user_school
            enseignants = filter_by_user_school(enseignants, user, 'ecole')
            periodes = filter_by_user_school(periodes, user, 'ecole')
        self.fields['enseignant'].queryset = enseignants
        self.fields['periode'].queryset = periodes
        if not self.instance.pk:
            from django.utils import timezone
            self.fields['date_avance'].initial = timezone.localdate()
        elif self.instance.statut in {
            AvanceSalaire.Statut.APPROUVEE,
            AvanceSalaire.Statut.DEDUITE,
        }:
            self.fields['approuver_immediatement'].initial = True

    def clean(self):
        cleaned_data = super().clean()
        enseignant = cleaned_data.get('enseignant')
        periode = cleaned_data.get('periode')
        montant = cleaned_data.get('montant') or 0
        if not enseignant or not periode:
            return cleaned_data
        if enseignant.ecole_id != periode.ecole_id:
            self.add_error('periode', "La période doit appartenir à l'école de l'employé.")
            return cleaned_data
        if periode.cloturee:
            self.add_error('periode', 'Une avance ne peut pas être affectée à une période clôturée.')
            return cleaned_data
        etat = EtatSalaire.objects.filter(enseignant=enseignant, periode=periode).first()
        if etat and etat.valide:
            self.add_error('periode', 'La paie de cette période est déjà validée.')
            return cleaned_data

        sera_approuvee = (
            cleaned_data.get('approuver_immediatement')
            or self.instance.statut == AvanceSalaire.Statut.APPROUVEE
        )
        if sera_approuvee:
            from .services import plafond_avance_disponible
            plafond = plafond_avance_disponible(
                enseignant,
                periode,
                exclure_avance=self.instance,
            )
            if montant > plafond:
                self.add_error(
                    'montant',
                    f"Le montant dépasse le salaire disponible ({plafond:,.0f} GNF).",
                )
        return cleaned_data
