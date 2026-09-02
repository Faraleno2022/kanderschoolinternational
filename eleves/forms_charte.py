from django import forms

from .models import Ecole


COLOR_FIELDS = (
    'couleur_principale', 'couleur_secondaire', 'couleur_accent',
    'couleur_fond_clair', 'couleur_texte', 'couleur_succes',
    'couleur_avertissement', 'couleur_danger', 'couleur_carte_eleves',
    'couleur_carte_paiements', 'couleur_carte_notes',
    'couleur_carte_salaires', 'couleur_carte_bus',
    'couleur_carte_cantine', 'couleur_carte_depenses',
)


class CharteGraphiqueEcoleForm(forms.ModelForm):
    class Meta:
        model = Ecole
        fields = COLOR_FIELDS + ('afficher_filigrane', 'opacite_filigrane')
        widgets = {
            **{
                field: forms.TextInput(attrs={
                    'type': 'color',
                    'class': 'form-control form-control-color school-color-input',
                })
                for field in COLOR_FIELDS
            },
            'afficher_filigrane': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'opacite_filigrane': forms.NumberInput(attrs={
                'class': 'form-control', 'min': '0', 'max': '0.25', 'step': '0.01',
            }),
        }

    def clean(self):
        cleaned = super().clean()
        for field in COLOR_FIELDS:
            value = str(cleaned.get(field) or '').upper()
            if value:
                cleaned[field] = value
        return cleaned

