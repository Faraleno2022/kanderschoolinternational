from django import forms

from eleves.models import Ecole

from .models_fournitures import ProduitFourniture, VenteFourniture


class ProduitFournitureForm(forms.ModelForm):
    class Meta:
        model = ProduitFourniture
        fields = [
            'ecole', 'nom', 'description', 'unite', 'quantite_stock',
            'prix_achat_unitaire', 'prix_vente_unitaire', 'seuil_alerte', 'actif',
        ]
        widgets = {
            'ecole': forms.Select(attrs={'class': 'form-select'}),
            'nom': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex. Cahier 100 pages',
            }),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'unite': forms.Select(attrs={'class': 'form-select'}),
            'quantite_stock': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 0,
            }),
            'prix_achat_unitaire': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 0, 'step': 1,
            }),
            'prix_vente_unitaire': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 0, 'step': 1,
            }),
            'seuil_alerte': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 0,
            }),
            'actif': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, ecole=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['ecole'].queryset = Ecole.objects.order_by('nom')
        if ecole is not None:
            self.fields['ecole'].queryset = Ecole.objects.filter(pk=ecole.pk)
            self.fields['ecole'].initial = ecole
            self.fields['ecole'].widget = forms.HiddenInput()


class VenteFournitureForm(forms.ModelForm):
    class Meta:
        model = VenteFourniture
        fields = ['quantite', 'date_vente', 'acheteur', 'observations']
        widgets = {
            'quantite': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 1, 'autofocus': True,
            }),
            'date_vente': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'acheteur': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nom du parent, élève ou service (facultatif)',
            }),
            'observations': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def clean_quantite(self):
        quantite = self.cleaned_data.get('quantite')
        if not quantite or quantite <= 0:
            raise forms.ValidationError('La quantité doit être supérieure à zéro.')
        return quantite
