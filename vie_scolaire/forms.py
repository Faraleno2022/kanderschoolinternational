from django import forms

from .models import Devoir


class DevoirForm(forms.ModelForm):
    class Meta:
        model = Devoir
        fields = ['classe', 'matiere', 'titre', 'description', 'date_donne', 'date_remise', 'fichier']
        widgets = {
            'classe': forms.Select(attrs={'class': 'form-select'}),
            'matiere': forms.TextInput(attrs={
                'class': 'form-control', 'list': 'matieres_list',
                'placeholder': 'Ex: Mathématiques'
            }),
            'titre': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Ex: Exercices page 12'
            }),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'date_donne': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'date_remise': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'fichier': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, classes_qs=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Les champs date acceptent le format ISO du widget HTML type=date
        self.fields['date_donne'].input_formats = ['%Y-%m-%d']
        self.fields['date_remise'].input_formats = ['%Y-%m-%d']
        if classes_qs is not None:
            self.fields['classe'].queryset = classes_qs

    def clean(self):
        cleaned = super().clean()
        date_donne = cleaned.get('date_donne')
        date_remise = cleaned.get('date_remise')
        if date_donne and date_remise and date_remise < date_donne:
            self.add_error('date_remise', "La date de remise doit être postérieure ou égale à la date du sujet.")
        return cleaned
