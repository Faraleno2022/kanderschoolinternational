"""Formulaires du module Recouvrement."""

from django import forms
from django.utils import timezone

from .models_recouvrement import (
    AbonnementInformatique, DepenseCuisine, DepenseDocument, Versement,
)


class _OperationForm(forms.ModelForm):
    """Base des formulaires simples : la date est pré-remplie au jour courant."""

    class Meta:
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'montant': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'step': 1}),
            'observation': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk and not self.initial.get('date'):
            self.initial['date'] = timezone.localdate()

    def clean_montant(self):
        montant = self.cleaned_data.get('montant')
        if montant is not None and montant < 0:
            raise forms.ValidationError("Le montant ne peut pas être négatif.")
        return montant


class DepenseCuisineForm(_OperationForm):
    class Meta(_OperationForm.Meta):
        model = DepenseCuisine
        fields = ['date', 'designation', 'montant', 'observation']
        widgets = dict(
            _OperationForm.Meta.widgets,
            designation=forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Riz, huile, gaz…',
            }),
        )


class DepenseDocumentForm(_OperationForm):
    class Meta(_OperationForm.Meta):
        model = DepenseDocument
        fields = ['date', 'designation', 'montant', 'observation']
        widgets = dict(
            _OperationForm.Meta.widgets,
            designation=forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Impression bulletins, ramettes…',
            }),
        )


class VersementForm(_OperationForm):
    class Meta(_OperationForm.Meta):
        model = Versement
        fields = ['date', 'montant', 'lieu_versement', 'observation']
        widgets = dict(
            _OperationForm.Meta.widgets,
            lieu_versement=forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Ecobank agence Matam, coffre direction…',
            }),
        )


class AbonnementInformatiqueForm(forms.ModelForm):
    """Abonnement informatique d'un élève (recherche par matricule côté vue)."""

    class Meta:
        model = AbonnementInformatique
        fields = [
            'eleve', 'date', 'montant', 'date_debut', 'date_fin',
            'alerte_avant_jours', 'observation',
        ]
        widgets = {
            'eleve': forms.Select(attrs={'class': 'form-select'}),
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'montant': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'step': 1}),
            'date_debut': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'date_fin': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'alerte_avant_jours': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'observation': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            today = timezone.localdate()
            self.initial.setdefault('date', today)
            self.initial.setdefault('date_debut', today)

    def clean_montant(self):
        montant = self.cleaned_data.get('montant')
        if montant is not None and montant < 0:
            raise forms.ValidationError("Le montant ne peut pas être négatif.")
        return montant

    def clean(self):
        cleaned = super().clean()
        debut = cleaned.get('date_debut')
        fin = cleaned.get('date_fin')
        # Une fin antérieure au début rendrait l'abonnement expiré dès sa
        # création et fausserait toutes les alertes.
        if debut and fin and fin < debut:
            self.add_error('date_fin', "La date de fin doit suivre la date de début.")
        return cleaned
