from django import forms
from .models import AbonnementBus, AbonnementCantine

class AbonnementBusForm(forms.ModelForm):
    class Meta:
        model = AbonnementBus
        fields = [
            'eleve', 'montant', 'reference_paiement', 'periodicite', 'date_debut', 'date_expiration', 'statut',
            'alerte_avant_jours', 'zone', 'itineraire', 'point_arret', 'contact_parent', 'observations'
        ]
        widgets = {
            'date_debut': forms.DateInput(attrs={'type': 'date'}),
            'date_expiration': forms.DateInput(attrs={'type': 'date'}),
            'reference_paiement': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex. REC-2026-001 ou référence Mobile Money',
            }),
        }


class AbonnementCantineForm(forms.ModelForm):
    class Meta:
        model = AbonnementCantine
        fields = [
            'eleve', 'montant', 'reference_paiement', 'periodicite', 'type_repas', 'date_debut', 'date_expiration',
            'statut', 'alerte_avant_jours', 'regime_alimentaire', 'allergies', 
            'contact_parent', 'observations'
        ]
        widgets = {
            'date_debut': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'date_expiration': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'eleve': forms.Select(attrs={'class': 'form-control'}),
            'montant': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Montant en GNF'}),
            'reference_paiement': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex. REC-2026-001 ou référence Mobile Money',
            }),
            'periodicite': forms.Select(attrs={'class': 'form-control'}),
            'type_repas': forms.Select(attrs={'class': 'form-control'}),
            'statut': forms.Select(attrs={'class': 'form-control'}),
            'alerte_avant_jours': forms.NumberInput(attrs={'class': 'form-control', 'value': 7}),
            'regime_alimentaire': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Végétarien, Halal, etc.'}),
            'allergies': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Indiquez les allergies alimentaires'}),
            'contact_parent': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+224XXXXXXXXX'}),
            'observations': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
