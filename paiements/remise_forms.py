from django import forms
from decimal import Decimal
from .models import RemiseReduction, PaiementRemise


class PaiementRemiseForm(forms.Form):
    """Formulaire pour appliquer des remises à un paiement"""
    
    remises = forms.ModelMultipleChoiceField(
        queryset=RemiseReduction.objects.filter(actif=True),
        widget=forms.CheckboxSelectMultiple(attrs={
            'class': 'form-check-input'
        }),
        required=False,
        label="Remises disponibles"
    )
    
    montant_original = forms.DecimalField(
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'readonly': True
        }),
        label="Montant original"
    )

    # Nouveau: pourcentage scolarité sélectionnable par l'utilisateur (1 à 10%)
    POURCENT_CHOICES = [("", "— Choisir —")] + [(str(i), f"{i}%") for i in range(1, 101)]
    pourcentage_scolarite = forms.ChoiceField(
        choices=POURCENT_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Remise scolarité (%)"
    )

    # Portée de la remise : la scolarité se découpe en trois tranches, et une
    # remise ne doit jamais toucher les frais d'inscription/réinscription.
    TRANCHE_CHOICES = [
        ('1', '1ère tranche'),
        ('2', '2ème tranche'),
        ('3', '3ème tranche'),
    ]
    tranches = forms.MultipleChoiceField(
        choices=TRANCHE_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        required=False,
        initial=['1'],
        label="Tranches concernées"
    )

    BASE_CHOICES = [
        ('TRANCHES', "Montant des tranches sélectionnées"),
        ('ECHEANCE', "Paiement à l'échéance"),
    ]
    base_calcul = forms.ChoiceField(
        choices=BASE_CHOICES,
        required=False,
        initial='TRANCHES',
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label="Base de calcul"
    )

    motif_remise = forms.ChoiceField(
        choices=[("", "— Choisir un motif —")] + PaiementRemise.MOTIF_APPLICATION_CHOICES,
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Motif de la remise",
        error_messages={'required': "Le motif de la remise est obligatoire."},
    )

    def __init__(self, *args, **kwargs):
        paiement = kwargs.pop('paiement', None)
        super().__init__(*args, **kwargs)

        if paiement:
            self.fields['montant_original'].initial = paiement.montant
            # Filtrer les remises valides à la date du paiement
            today = paiement.date_paiement
            self.fields['remises'].queryset = RemiseReduction.objects.filter(
                actif=True,
                date_debut__lte=today,
                date_fin__gte=today
            )

    def clean_base_calcul(self):
        return self.cleaned_data.get('base_calcul') or 'TRANCHES'

    def clean_tranches(self):
        tranches = self.cleaned_data.get('tranches') or []
        # Sans tranche cochée, la remise n'a aucune base de calcul : la
        # refuser vaut mieux que de retomber silencieusement sur T1.
        if not tranches:
            raise forms.ValidationError("Sélectionnez au moins une tranche concernée par la remise.")
        return sorted(tranches)

    def calculate_total_remise(self, montant_base):
        """Calcule le montant total des remises sélectionnées"""
        remises = self.cleaned_data.get('remises', [])
        total_remise = Decimal('0')
        
        for remise in remises:
            montant_remise = remise.calculer_remise(montant_base)
            total_remise += montant_remise
        
        return min(total_remise, montant_base)  # La remise ne peut pas dépasser le montant
    
    def get_remises_details(self, montant_base):
        """Retourne les détails de chaque remise appliquée"""
        remises = self.cleaned_data.get('remises', [])
        details = []
        
        for remise in remises:
            montant_remise = remise.calculer_remise(montant_base)
            details.append({
                'remise': remise,
                'montant': montant_remise,
                'description': f"{remise.nom} - {montant_remise:,.0f} GNF".replace(',', ' ')
            })
        
        return details


class CalculateurRemiseForm(forms.Form):
    """Formulaire pour calculer les remises en temps réel"""
    
    montant = forms.DecimalField(
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Montant en GNF',
            'min': '0',
            'step': '1000'
        }),
        label="Montant du paiement"
    )
    
    remise_id = forms.ModelChoiceField(
        queryset=RemiseReduction.objects.filter(actif=True),
        widget=forms.Select(attrs={
            'class': 'form-select'
        }),
        required=False,
        empty_label="Sélectionner une remise",
        label="Remise à appliquer"
    )
    
    def calculate_remise_preview(self):
        """Calcule un aperçu de la remise"""
        if not self.is_valid():
            return None
            
        montant = self.cleaned_data.get('montant')
        remise = self.cleaned_data.get('remise_id')
        
        if not montant or not remise:
            return None
            
        montant_remise = remise.calculer_remise(montant)
        montant_final = montant - montant_remise
        
        return {
            'montant_original': montant,
            'montant_remise': montant_remise,
            'montant_final': montant_final,
            'pourcentage_remise': (montant_remise / montant * 100) if montant > 0 else 0,
            'remise_nom': remise.nom,
            'remise_type': remise.get_type_remise_display()
        }
