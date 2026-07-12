from django import forms
from django.forms import ClearableFileInput
from .models import ClasseNote, MatiereNote, Evaluation, NoteEleve, ThemeBulletin, ActiviteJournaliere, PieceJointeActivite, ActiviteCulturelle

class ClasseNoteForm(forms.ModelForm):
    """Formulaire pour créer/modifier une classe"""
    
    # Champ personnalisé pour le nom avec datalist
    nom = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ex: 7ème A, CM2 B, etc.',
            'list': 'classes-disponibles',
            'autocomplete': 'off'
        }),
        help_text='Sélectionnez une classe existante ou saisissez un nouveau nom'
    )
    
    class Meta:
        model = ClasseNote
        fields = ['nom', 'niveau', 'annee_scolaire', 'effectif', 'description', 'actif']
        widgets = {
            'niveau': forms.Select(attrs={
                'class': 'form-select'
            }),
            'annee_scolaire': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '2024-2025'
            }),
            'effectif': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'placeholder': 'Nombre d\'élèves'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Description optionnelle de la classe...'
            }),
            'actif': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        # Récupérer l'école depuis les kwargs
        ecole = kwargs.pop('ecole', None)
        super().__init__(*args, **kwargs)
        
        # Charger les classes disponibles depuis le module Élèves
        if ecole:
            try:
                from eleves.models import Classe as ClasseEleve
                # Récupérer les noms de classes uniques pour l'école
                classes_eleves = ClasseEleve.objects.filter(
                    ecole=ecole
                ).values_list('nom', flat=True).distinct().order_by('nom')
                
                # Stocker pour utilisation dans le template
                self.classes_disponibles = list(classes_eleves)
            except Exception:
                self.classes_disponibles = []
        else:
            self.classes_disponibles = []

class MatiereNoteForm(forms.ModelForm):
    """Formulaire pour créer/modifier une matière"""
    
    # Rendre le coefficient optionnel
    coefficient = forms.DecimalField(
        required=False,
        max_digits=4,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': '1.0 (optionnel pour Maternelle/Primaire)',
            'min': '0.5',
            'step': '0.5'
        })
    )
    
    class Meta:
        model = MatiereNote
        fields = ['nom', 'code', 'coefficient', 'description', 'actif']
        widgets = {
            'nom': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Mathématiques, Français, etc.'
            }),
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: MATH, FR, ANG'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Description optionnelle...'
            }),
            'actif': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }
    
    def clean_coefficient(self):
        """Si le coefficient est vide, retourner la valeur par défaut"""
        coefficient = self.cleaned_data.get('coefficient')
        if coefficient is None or coefficient == '':
            return 1.0
        return coefficient

class EvaluationForm(forms.ModelForm):
    """Formulaire pour créer/modifier une évaluation"""
    
    class Meta:
        model = Evaluation
        fields = ['titre', 'type_evaluation', 'periode', 'date_evaluation', 'note_sur', 'coefficient', 'description']
        widgets = {
            'titre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Devoir 1, Composition Trimestre 1'
            }),
            'type_evaluation': forms.Select(attrs={
                'class': 'form-select'
            }),
            'periode': forms.Select(attrs={
                'class': 'form-select'
            }),
            'date_evaluation': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'note_sur': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'step': '0.5',
                'placeholder': '20'
            }),
            'coefficient': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0.5',
                'step': '0.5',
                'placeholder': '1.0'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Description optionnelle...'
            }),
        }

class NoteEleveForm(forms.ModelForm):
    """Formulaire pour saisir une note"""
    
    class Meta:
        model = NoteEleve
        fields = ['note', 'absent', 'commentaire']
        widgets = {
            'note': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'step': '0.25'
            }),
            'absent': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'commentaire': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Commentaire optionnel...'
            }),
        }


class ThemeBulletinForm(forms.ModelForm):
    """Formulaire pour personnaliser les couleurs du bulletin"""
    
    class Meta:
        model = ThemeBulletin
        fields = [
            'nom', 'couleur_primaire', 'couleur_secondaire', 'couleur_accent',
            'couleur_texte_principal', 'couleur_texte_secondaire',
            'couleur_fond_header', 'couleur_fond_tableau', 'couleur_fond_carte',
            'couleur_bordure', 'couleur_mention_tb', 'couleur_mention_bien',
            'couleur_mention_ab', 'couleur_mention_passable', 'couleur_mention_insuffisant',
            'actif', 'par_defaut'
        ]
        widgets = {
            'nom': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Thème Bleu, Thème Vert, etc.'
            }),
            'couleur_primaire': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color'
            }),
            'couleur_secondaire': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color'
            }),
            'couleur_accent': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color'
            }),
            'couleur_texte_principal': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color'
            }),
            'couleur_texte_secondaire': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color'
            }),
            'couleur_fond_header': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color'
            }),
            'couleur_fond_tableau': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color'
            }),
            'couleur_fond_carte': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color'
            }),
            'couleur_bordure': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color'
            }),
            'couleur_mention_tb': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color'
            }),
            'couleur_mention_bien': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color'
            }),
            'couleur_mention_ab': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color'
            }),
            'couleur_mention_passable': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color'
            }),
            'couleur_mention_insuffisant': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color'
            }),
            'actif': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'par_defaut': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }


class ActiviteJournaliereForm(forms.ModelForm):
    class Meta:
        model = ActiviteJournaliere
        fields = ['classe', 'eleve', 'date', 'type_activite', 'titre', 'description', 'appreciation']
        widgets = {
            'classe': forms.Select(attrs={'class': 'form-select', 'id': 'id_classe'}),
            'eleve': forms.Select(attrs={'class': 'form-select', 'id': 'id_eleve'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'type_activite': forms.Select(attrs={'class': 'form-select'}),
            'titre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': "Titre de l'activité"}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Description ou observation...'}),
            'appreciation': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Très bien, Bien, À améliorer...'}),
        }


class MultipleFileInput(ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """FileField qui accepte plusieurs fichiers (liste retournée par MultipleFileInput)."""

    def clean(self, data, initial=None):
        # Le widget avec allow_multiple_selected retourne une liste
        if isinstance(data, (list, tuple)):
            if not data or all(d is None for d in data):
                if self.required:
                    raise forms.ValidationError(self.error_messages['required'])
                return []
            return [super().clean(f, initial) for f in data if f is not None]
        if not data:
            if self.required:
                raise forms.ValidationError(self.error_messages['required'])
            return []
        return [super().clean(data, initial)]


class PieceJointeActiviteForm(forms.Form):
    fichiers = MultipleFileField(
        widget=MultipleFileInput(attrs={'class': 'form-control', 'accept': 'image/*,.pdf,.doc,.docx'}),
        required=False,
        label="Pièces jointes (images, copies d'évaluations...)"
    )

    def clean_fichiers(self):
        files = self.files.getlist('fichiers')
        max_size = 10 * 1024 * 1024  # 10 MB
        allowed_ext = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'jfif', 'heic', 'heif', 'svg', 'tiff', 'tif', 'pdf', 'doc', 'docx'}
        for f in files:
            ext = f.name.rsplit('.', 1)[-1].lower() if '.' in f.name else ''
            if ext not in allowed_ext:
                raise forms.ValidationError(f"Type de fichier non autorisé : {f.name}")
            if f.size > max_size:
                raise forms.ValidationError(f"Fichier trop volumineux (max 10 Mo) : {f.name}")
        return files


class ActiviteCulturelleForm(forms.ModelForm):
    """Formulaire de gestion des activités culturelles publiées sur le site"""

    class Meta:
        model = ActiviteCulturelle
        fields = ['titre', 'description', 'image', 'date_activite', 'publie']
        widgets = {
            'titre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': "Ex: Fête de fin d'année, Sortie au zoo..."
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 4,
                'placeholder': "Description de l'activité affichée sur le site public"
            }),
            'image': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'date_activite': forms.DateInput(
                attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'
            ),
            'publie': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
