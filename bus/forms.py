from django import forms
from django.db.utils import OperationalError, ProgrammingError

from eleves.models import Classe, Eleve
from utilisateurs.utils import filter_by_user_school

from .models import (
    AbonnementBus,
    AbonnementCantine,
    TypePeriodiciteAbonnement,
    TypeRepasCantine,
)


class EleveAbonnementSelect(forms.Select):
    """Ajoute au DOM les données nécessaires au filtre de classe."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        instance = getattr(value, 'instance', None)
        if instance is not None:
            option['attrs']['data-classe-id'] = instance.classe_id or ''
            option['attrs']['data-matricule'] = instance.matricule or ''
        return option


class EleveAbonnementChoiceField(forms.ModelChoiceField):
    widget = EleveAbonnementSelect

    def label_from_instance(self, eleve):
        matricule = eleve.matricule or 'Sans matricule'
        return f'{matricule} — {eleve.prenom} {eleve.nom}'


class ConfiguredChoiceSelect(forms.Select):
    """Expose la durée d'une périodicité au calcul JavaScript."""

    option_metadata = {}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        metadata = self.option_metadata.get(str(value), {})
        option['attrs']['data-duree-mois'] = metadata.get('duree_mois', 0)
        option['attrs']['data-duree-jours'] = metadata.get('duree_jours', 0)
        return option


def _periodicite_choices(service, current_value, fallback_choices):
    choices = []
    metadata = {}
    try:
        options = list(
            TypePeriodiciteAbonnement.objects.filter(service=service, actif=True)
            .order_by('ordre', 'libelle')
        )
        if current_value and not any(option.code == current_value for option in options):
            current = TypePeriodiciteAbonnement.objects.filter(
                service=service,
                code=current_value,
            ).first()
            if current:
                options.append(current)
        for option in options:
            choices.append((option.code, option.libelle))
            metadata[option.code] = {
                'duree_mois': option.duree_mois,
                'duree_jours': option.duree_jours,
            }
    except (OperationalError, ProgrammingError):
        choices = []

    if not choices:
        choices = list(fallback_choices)
        default_durations = {
            'JOURNALIER': (0, 1),
            'HEBDOMADAIRE': (0, 7),
            'MENSUEL': (1, 0),
            'TRIMESTRIEL': (3, 0),
            'SEMESTRIEL': (6, 0),
            'ANNUEL': (12, 0),
        }
        metadata = {
            code: {
                'duree_mois': default_durations.get(code, (0, 0))[0],
                'duree_jours': default_durations.get(code, (0, 0))[1],
            }
            for code, _label in choices
        }

    if current_value and current_value not in {code for code, _label in choices}:
        choices.append((current_value, current_value))
        metadata[current_value] = {'duree_mois': 0, 'duree_jours': 0}
    return choices, metadata


def _type_repas_choices(current_value):
    try:
        options = list(TypeRepasCantine.objects.filter(actif=True).order_by('ordre', 'libelle'))
        if current_value and not any(option.code == current_value for option in options):
            current = TypeRepasCantine.objects.filter(code=current_value).first()
            if current:
                options.append(current)
        choices = [(option.code, option.libelle) for option in options]
    except (OperationalError, ProgrammingError):
        choices = []
    if not choices:
        choices = list(AbonnementCantine.TypeRepas.choices)
    if current_value and current_value not in {code for code, _label in choices}:
        choices.append((current_value, current_value))
    return choices


class AbonnementFormMixin:
    def _configure_students(self, user):
        students = Eleve.objects.select_related('classe', 'classe__ecole').order_by(
            'classe__nom', 'matricule', 'prenom', 'nom'
        )
        classes = Classe.objects.select_related('ecole').order_by('nom', 'annee_scolaire')
        if user is not None:
            students = filter_by_user_school(students, user, 'classe__ecole')
            classes = filter_by_user_school(classes, user, 'ecole')
        self.fields['eleve'].queryset = students
        self.fields['classe_filtre'].queryset = classes

        if not self.is_bound:
            eleve_initial = self.initial.get('eleve')
            if not eleve_initial and getattr(self.instance, 'eleve_id', None):
                eleve_initial = self.instance.eleve
            if eleve_initial:
                eleve_id = getattr(eleve_initial, 'pk', eleve_initial)
                classe_id = students.filter(pk=eleve_id).values_list('classe_id', flat=True).first()
                if classe_id:
                    self.initial['classe_filtre'] = classe_id

    def _current_value(self, field_name, default):
        if self.is_bound:
            return str(self.data.get(field_name) or default)
        value = self.initial.get(field_name)
        if value:
            return str(value)
        return str(getattr(self.instance, field_name, '') or default)


class AbonnementBusForm(AbonnementFormMixin, forms.ModelForm):
    classe_filtre = forms.ModelChoiceField(
        queryset=Classe.objects.none(), required=False, label='Filtrer par classe',
        empty_label='Toutes les classes', widget=forms.Select(attrs={'class': 'form-select'}),
    )
    eleve = EleveAbonnementChoiceField(
        queryset=Eleve.objects.none(), label='Élève', empty_label='Sélectionnez un élève',
        widget=EleveAbonnementSelect(attrs={'class': 'form-select'}),
    )
    periodicite = forms.ChoiceField(
        label="Type d'abonnement", widget=ConfiguredChoiceSelect(attrs={'class': 'form-select'}),
    )

    class Meta:
        model = AbonnementBus
        fields = [
            'eleve', 'montant', 'reference_paiement', 'periodicite', 'date_debut', 'date_expiration', 'statut',
            'alerte_avant_jours', 'zone', 'itineraire', 'point_arret', 'contact_parent', 'observations'
        ]
        widgets = {
            'montant': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'date_debut': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'date_expiration': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'statut': forms.Select(attrs={'class': 'form-select'}),
            'alerte_avant_jours': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'zone': forms.TextInput(attrs={'class': 'form-control'}),
            'itineraire': forms.TextInput(attrs={'class': 'form-control'}),
            'point_arret': forms.TextInput(attrs={'class': 'form-control'}),
            'contact_parent': forms.TextInput(attrs={'class': 'form-control'}),
            'observations': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'reference_paiement': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex. REC-2026-001 ou référence Mobile Money',
            }),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._configure_students(user)
        current = self._current_value('periodicite', AbonnementBus.Periodicite.MENSUEL)
        choices, metadata = _periodicite_choices(
            TypePeriodiciteAbonnement.Service.BUS, current, AbonnementBus.Periodicite.choices,
        )
        self.fields['periodicite'].choices = choices
        self.fields['periodicite'].widget.option_metadata = metadata


class AbonnementCantineForm(AbonnementFormMixin, forms.ModelForm):
    classe_filtre = forms.ModelChoiceField(
        queryset=Classe.objects.none(), required=False, label='Filtrer par classe',
        empty_label='Toutes les classes', widget=forms.Select(attrs={'class': 'form-select'}),
    )
    eleve = EleveAbonnementChoiceField(
        queryset=Eleve.objects.none(), label='Élève', empty_label='Sélectionnez un élève',
        widget=EleveAbonnementSelect(attrs={'class': 'form-select'}),
    )
    periodicite = forms.ChoiceField(
        label="Type d'abonnement", widget=ConfiguredChoiceSelect(attrs={'class': 'form-select'}),
    )
    type_repas = forms.ChoiceField(
        label='Type de repas', widget=forms.Select(attrs={'class': 'form-select'}),
    )

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
            'montant': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Montant en GNF'}),
            'reference_paiement': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex. REC-2026-001 ou référence Mobile Money',
            }),
            'statut': forms.Select(attrs={'class': 'form-select'}),
            'alerte_avant_jours': forms.NumberInput(attrs={'class': 'form-control', 'value': 7}),
            'regime_alimentaire': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Végétarien, Halal, etc.'}),
            'allergies': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Indiquez les allergies alimentaires'}),
            'contact_parent': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+224XXXXXXXXX'}),
            'observations': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._configure_students(user)
        current_periodicite = self._current_value('periodicite', AbonnementCantine.Periodicite.MENSUEL)
        choices, metadata = _periodicite_choices(
            TypePeriodiciteAbonnement.Service.CANTINE,
            current_periodicite,
            AbonnementCantine.Periodicite.choices,
        )
        self.fields['periodicite'].choices = choices
        self.fields['periodicite'].widget.option_metadata = metadata
        current_repas = self._current_value('type_repas', AbonnementCantine.TypeRepas.DEJEUNER)
        self.fields['type_repas'].choices = _type_repas_choices(current_repas)
