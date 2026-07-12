from django.db import models
from django.contrib.auth.models import User
from eleves.models import Ecole
from eleves.validators import validate_photo_size
from decimal import Decimal
from synchronisation.mixins import SyncTrackedModel

class ClasseNote(SyncTrackedModel):
    """Classe pour la gestion des notes"""
    NIVEAUX_CHOICES = [
        ('GARDERIE', 'Garderie'),
        ('MATERNELLE', 'Maternelle'),
        ('PRIMAIRE_1', 'Primaire 1ère'),
        ('PRIMAIRE_2', 'Primaire 2ème'),
        ('PRIMAIRE_3', 'Primaire 3ème'),
        ('PRIMAIRE_4', 'Primaire 4ème'),
        ('PRIMAIRE_5', 'Primaire 5ème'),
        ('PRIMAIRE_6', 'Primaire 6ème'),
        ('COLLEGE_7', 'Collège 7ème'),
        ('COLLEGE_8', 'Collège 8ème'),
        ('COLLEGE_9', 'Collège 9ème'),
        ('COLLEGE_10', 'Collège 10ème'),
        ('LYCEE_11', 'Lycée 11ème'),
        ('LYCEE_12', 'Lycée 12ème'),
        ('TERMINALE', 'Terminale'),
    ]
    
    NIVEAU_ENSEIGNEMENT_CHOICES = [
        ('MATERNELLE', 'Maternelle'),
        ('PRIMAIRE', 'Primaire'),
        ('SECONDAIRE', 'Secondaire'),
    ]
    
    ecole = models.ForeignKey(Ecole, on_delete=models.CASCADE, related_name='classes_notes')
    nom = models.CharField(max_length=100, verbose_name="Nom de la classe")
    niveau = models.CharField(max_length=20, choices=NIVEAUX_CHOICES, verbose_name="Niveau")
    niveau_enseignement = models.CharField(max_length=20, choices=NIVEAU_ENSEIGNEMENT_CHOICES, default='SECONDAIRE', verbose_name="Niveau d'enseignement")
    annee_scolaire = models.CharField(max_length=9, verbose_name="Année scolaire", help_text="Format: 2024-2025")
    effectif = models.PositiveIntegerField(default=0, verbose_name="Effectif")
    description = models.TextField(blank=True, null=True, verbose_name="Description")
    actif = models.BooleanField(default=True, verbose_name="Active")
    
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='classes_notes_creees')
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Classe (Notes)"
        verbose_name_plural = "Classes (Notes)"
        ordering = ['niveau', 'nom']
        unique_together = ['ecole', 'nom', 'annee_scolaire']
    
    def __str__(self):
        return f"{self.nom} - {self.get_niveau_display()} ({self.annee_scolaire})"

class MatiereNote(SyncTrackedModel):
    """Matière avec coefficient pour une classe"""
    classe = models.ForeignKey(ClasseNote, on_delete=models.CASCADE, related_name='matieres')
    nom = models.CharField(max_length=100, verbose_name="Nom de la matière")
    code = models.CharField(max_length=20, verbose_name="Code", help_text="Ex: MATH, FR, ANG")
    coefficient = models.DecimalField(max_digits=4, decimal_places=2, default=1.0, null=True, blank=True, verbose_name="Coefficient")
    description = models.TextField(blank=True, null=True, verbose_name="Description")
    actif = models.BooleanField(default=True, verbose_name="Active")
    
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='matieres_notes_creees')
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Matière (Notes)"
        verbose_name_plural = "Matières (Notes)"
        ordering = ['nom']
        unique_together = ['classe', 'code']
    
    def __str__(self):
        return f"{self.nom} ({self.code}) - Coef: {self.coefficient}"

class Evaluation(SyncTrackedModel):
    """Évaluation pour une matière"""
    TYPE_CHOICES = [
        ('DEVOIR', 'Devoir'),
        ('COMPOSITION', 'Composition'),
        ('EXAMEN', 'Examen'),
        ('CONTROLE', 'Contrôle'),
        ('INTERROGATION', 'Interrogation'),
    ]
    
    PERIODE_CHOICES = [
        # Périodes mensuelles (système guinéen)
        ('OCTOBRE', 'Octobre'),
        ('NOVEMBRE', 'Novembre'),
        ('DECEMBRE', 'Décembre'),
        ('JANVIER', 'Janvier'),
        ('FEVRIER', 'Février'),
        ('MARS', 'Mars'),
        ('AVRIL', 'Avril'),
        ('MAI', 'Mai'),
        ('JUIN', 'Juin'),
        # Périodes trimestrielles
        ('TRIMESTRE_1', 'Trimestre 1'),
        ('TRIMESTRE_2', 'Trimestre 2'),
        ('TRIMESTRE_3', 'Trimestre 3'),
        # Périodes semestrielles
        ('SEMESTRE_1', 'Semestre 1'),
        ('SEMESTRE_2', 'Semestre 2'),
    ]
    
    matiere = models.ForeignKey(MatiereNote, on_delete=models.CASCADE, related_name='evaluations')
    titre = models.CharField(max_length=200, verbose_name="Titre de l'évaluation")
    type_evaluation = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name="Type")
    periode = models.CharField(max_length=20, choices=PERIODE_CHOICES, verbose_name="Période")
    date_evaluation = models.DateField(verbose_name="Date de l'évaluation")
    note_sur = models.DecimalField(max_digits=5, decimal_places=2, default=20.0, verbose_name="Note sur")
    coefficient = models.DecimalField(max_digits=4, decimal_places=2, default=1.0, verbose_name="Coefficient")
    description = models.TextField(blank=True, null=True, verbose_name="Description")
    
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='evaluations_creees')
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Évaluation"
        verbose_name_plural = "Évaluations"
        ordering = ['-date_evaluation']
        indexes = [
            models.Index(fields=['matiere', 'periode'], name='eval_matiere_periode_idx'),
            models.Index(fields=['matiere', 'type_evaluation'], name='eval_matiere_type_idx'),
        ]
    
    def __str__(self):
        return f"{self.titre} - {self.matiere.nom} ({self.get_periode_display()})"

class NoteEleve(SyncTrackedModel):
    """Note d'un élève pour une évaluation"""
    from eleves.models import Eleve
    
    evaluation = models.ForeignKey(Evaluation, on_delete=models.CASCADE, related_name='notes')
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, related_name='notes_evaluations')
    note = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Note obtenue")
    absent = models.BooleanField(default=False, verbose_name="Absent")
    commentaire = models.TextField(blank=True, null=True, verbose_name="Commentaire")
    
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='notes_saisies')
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Note élève"
        verbose_name_plural = "Notes élèves"
        ordering = ['eleve__nom', 'eleve__prenom']
        unique_together = ['evaluation', 'eleve']
        indexes = [
            models.Index(fields=['eleve'], name='note_eleve_idx'),
            models.Index(fields=['evaluation', 'eleve'], name='note_eval_eleve_idx'),
        ]
    
    def __str__(self):
        if self.absent:
            return f"{self.eleve} - Absent"
        try:
            return f"{self.eleve} - {self.note}/{self.evaluation.note_sur}"
        except Evaluation.DoesNotExist:
            return f"{self.eleve} - {self.note}/? (évaluation supprimée)"
    
    @property
    def note_sur_20(self):
        """Convertir la note sur 20"""
        if self.absent:
            return 0
        return (self.note / self.evaluation.note_sur) * 20


class NoteMensuelle(SyncTrackedModel):
    """Notes mensuelles pour le système guinéen (Octobre à Mai)"""
    from eleves.models import Eleve
    
    MOIS_CHOICES = [
        ('OCTOBRE', 'Octobre'),
        ('NOVEMBRE', 'Novembre'),
        ('DECEMBRE', 'Décembre'),
        ('JANVIER', 'Janvier'),
        ('FEVRIER', 'Février'),
        ('MARS', 'Mars'),
        ('AVRIL', 'Avril'),
        ('MAI', 'Mai'),
        ('JUIN', 'Juin'),
    ]
    
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, related_name='notes_mensuelles')
    matiere = models.ForeignKey(MatiereNote, on_delete=models.CASCADE, related_name='notes_mensuelles')
    mois = models.CharField(max_length=20, choices=MOIS_CHOICES, verbose_name="Mois")
    annee_scolaire = models.CharField(max_length=9, verbose_name="Année scolaire")
    note = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Note sur 20", null=True, blank=True)
    absent = models.BooleanField(default=False, verbose_name="Absent")
    
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Note mensuelle"
        verbose_name_plural = "Notes mensuelles"
        ordering = ['eleve', 'matiere', 'mois']
        unique_together = ['eleve', 'matiere', 'mois', 'annee_scolaire']
        # OPTIMISATION: Index pour les requêtes en lot
        indexes = [
            models.Index(fields=['annee_scolaire', 'mois']),
            models.Index(fields=['eleve', 'annee_scolaire']),
            models.Index(fields=['matiere', 'annee_scolaire']),
        ]
    
    def __str__(self):
        if self.absent:
            return f"{self.eleve} - {self.matiere.nom} - {self.get_mois_display()} - Absent"
        return f"{self.eleve} - {self.matiere.nom} - {self.get_mois_display()} - {self.note}/20"


class CompositionNote(SyncTrackedModel):
    """Notes de composition pour le système guinéen"""
    from eleves.models import Eleve
    
    PERIODE_CHOICES = [
        ('SEMESTRE_1', 'Semestre 1'),
        ('SEMESTRE_2', 'Semestre 2'),
        ('TRIMESTRE_1', 'Trimestre 1'),
        ('TRIMESTRE_2', 'Trimestre 2'),
        ('TRIMESTRE_3', 'Trimestre 3'),
    ]
    
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, related_name='compositions')
    matiere = models.ForeignKey(MatiereNote, on_delete=models.CASCADE, related_name='compositions')
    periode = models.CharField(max_length=20, choices=PERIODE_CHOICES, verbose_name="Période")
    annee_scolaire = models.CharField(max_length=9, verbose_name="Année scolaire")
    note = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Note sur 20")
    absent = models.BooleanField(default=False, verbose_name="Absent")
    
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Note de composition"
        verbose_name_plural = "Notes de composition"
        ordering = ['eleve', 'matiere', 'periode']
        unique_together = ['eleve', 'matiere', 'periode', 'annee_scolaire']
        # OPTIMISATION: Index pour les requêtes en lot
        indexes = [
            models.Index(fields=['annee_scolaire', 'periode']),
            models.Index(fields=['eleve', 'annee_scolaire']),
            models.Index(fields=['matiere', 'annee_scolaire']),
        ]
    
    def __str__(self):
        if self.absent:
            return f"{self.eleve} - {self.matiere.nom} - {self.get_periode_display()} - Absent"
        return f"{self.eleve} - {self.matiere.nom} - {self.get_periode_display()} - {self.note}/20"


class AppreciationMaternelle(SyncTrackedModel):
    """Appréciations qualitatives pour la maternelle"""
    from eleves.models import Eleve
    
    APPRECIATION_CHOICES = [
        ('A+', 'Excellent'),
        ('A', 'Très bien'),
        ('B+', 'Bien'),
        ('B', 'Assez bien'),
        ('B-', 'Moyen'),
        ('C', 'Passable'),
        ('D', 'Éprouve des difficultés'),
    ]
    
    TRIMESTRE_CHOICES = [
        ('TRIMESTRE_1', 'Trimestre 1'),
        ('TRIMESTRE_2', 'Trimestre 2'),
        ('TRIMESTRE_3', 'Trimestre 3'),
    ]
    
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, related_name='appreciations_maternelle')
    matiere = models.ForeignKey(MatiereNote, on_delete=models.CASCADE, related_name='appreciations_maternelle')
    trimestre = models.CharField(max_length=20, choices=TRIMESTRE_CHOICES, verbose_name="Trimestre")
    annee_scolaire = models.CharField(max_length=9, verbose_name="Année scolaire")
    appreciation = models.CharField(max_length=20, choices=APPRECIATION_CHOICES, verbose_name="Appréciation")
    commentaire = models.TextField(blank=True, null=True, verbose_name="Commentaire")
    absent = models.BooleanField(default=False, verbose_name="Absent")
    
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Appréciation maternelle"
        verbose_name_plural = "Appréciations maternelle"
        ordering = ['eleve', 'matiere', 'trimestre']
        unique_together = ['eleve', 'matiere', 'trimestre', 'annee_scolaire']
        indexes = [
            models.Index(fields=['eleve', 'trimestre', 'annee_scolaire'], name='appmat_eleve_trim_idx'),
            models.Index(fields=['matiere', 'trimestre', 'annee_scolaire'], name='appmat_mat_trim_idx'),
        ]
    
    def __str__(self):
        if self.absent:
            return f"{self.eleve} - {self.matiere.nom} - {self.get_trimestre_display()} - Absent"
        return f"{self.eleve} - {self.matiere.nom} - {self.get_trimestre_display()} - {self.get_appreciation_display()}"


class BulletinMaternelle(SyncTrackedModel):
    """Bulletin maternelle avec analyses et recommandations"""
    from eleves.models import Eleve
    
    TRIMESTRE_CHOICES = [
        ('TRIMESTRE_1', 'Trimestre 1'),
        ('TRIMESTRE_2', 'Trimestre 2'),
        ('TRIMESTRE_3', 'Trimestre 3'),
    ]
    
    # Analyses du travail de l'enfant (champs booléens pour cases à cocher)
    ANALYSES_CHOICES = [
        ('comprend', "L'enfant comprend ce qu'on lui demande"),
        ('ne_comprend_pas', "L'enfant ne comprend pas ce qu'on lui demande"),
        ('trop_jeune', "L'enfant est trop jeune pour cette classe"),
        ('fixe_attention', "L'enfant fixe son attention"),
        ('pas_probleme_monitrice', "L'enfant n'a pas de problème avec sa monitrice"),
        ('pas_probleme_camarades', "L'enfant n'a pas de problème avec ses camarades"),
        ('pas_probleme_famille', "L'enfant n'a pas de problème avec sa famille"),
        ('doue', "L'enfant est doué"),
        ('paresseux', "L'enfant est paresseux"),
    ]
    
    # Recommandations de la monitrice
    RECOMMANDATIONS_CHOICES = [
        ('encourager_feliciter', "Enfant à encourager et à féliciter"),
        ('suivre_domicile', "Enfant à suivre à domicile"),
        ('gouter_sac', "Mettre le goûter dans le sac de l'enfant"),
        ('aide_parents', "L'enfant a besoin d'aide et d'encouragement des parents"),
        ('amour_parental', "L'enfant a besoin de l'amour maternel et paternel"),
        ('epanoui', "L'enfant a besoin d'être épanoui"),
        ('sorties_educatives', "L'enfant a besoin de sorties éducatives et récréatives"),
        ('aide_monitrice_parents', "L'enfant a besoin de l'aide de la monitrice et des parents pour développer ses facultés intellectuelles"),
        ('douceur_patience', "L'enfant doit être pris avec beaucoup de douceur et de patience"),
        ('fermete', "L'enfant a besoin de fermeté"),
        ('esprit_inferiorite', "L'enfant a un esprit d'infériorité"),
        ('attention_particuliere', "L'enfant a besoin d'une attention particulière des parents"),
    ]
    
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, related_name='bulletins_maternelle')
    classe = models.ForeignKey(ClasseNote, on_delete=models.CASCADE, related_name='bulletins_maternelle')
    trimestre = models.CharField(max_length=20, choices=TRIMESTRE_CHOICES, verbose_name="Trimestre")
    annee_scolaire = models.CharField(max_length=9, verbose_name="Année scolaire")
    
    # Analyses du travail (stockées en JSON pour flexibilité)
    analyses = models.JSONField(default=list, blank=True, verbose_name="Analyses du travail")
    
    # Recommandations (stockées en JSON pour flexibilité)  
    recommandations = models.JSONField(default=list, blank=True, verbose_name="Recommandations")
    
    # Appréciation générale de la monitrice
    appreciation_generale = models.TextField(blank=True, null=True, verbose_name="Appréciation générale")
    
    # Signature
    signature_monitrice = models.BooleanField(default=False, verbose_name="Signé par la monitrice")
    signature_directeur = models.BooleanField(default=False, verbose_name="Signé par le directeur")
    
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Bulletin maternelle"
        verbose_name_plural = "Bulletins maternelle"
        ordering = ['eleve', 'trimestre']
        unique_together = ['eleve', 'trimestre', 'annee_scolaire']
    
    def __str__(self):
        return f"Bulletin {self.eleve} - {self.get_trimestre_display()} - {self.annee_scolaire}"
    
    def get_analyses_display(self):
        """Retourne les analyses sélectionnées en texte"""
        analyses_dict = dict(self.ANALYSES_CHOICES)
        return [analyses_dict.get(a, a) for a in self.analyses if a in analyses_dict]
    
    def get_recommandations_display(self):
        """Retourne les recommandations sélectionnées en texte"""
        recommandations_dict = dict(self.RECOMMANDATIONS_CHOICES)
        return [recommandations_dict.get(r, r) for r in self.recommandations if r in recommandations_dict]


class ThemeBulletin(SyncTrackedModel):
    """Personnalisation des couleurs du bulletin"""
    
    nom = models.CharField(max_length=100, verbose_name="Nom du thème")
    ecole = models.ForeignKey(Ecole, on_delete=models.CASCADE, related_name='themes_bulletin', null=True, blank=True)
    
    # Couleurs principales
    couleur_primaire = models.CharField(max_length=7, default='#2c3e50', verbose_name="Couleur primaire", help_text="Ex: #2c3e50")
    couleur_secondaire = models.CharField(max_length=7, default='#3498db', verbose_name="Couleur secondaire", help_text="Ex: #3498db")
    couleur_accent = models.CharField(max_length=7, default='#e74c3c', verbose_name="Couleur accent", help_text="Ex: #e74c3c")
    
    # Couleurs de texte
    couleur_texte_principal = models.CharField(max_length=7, default='#2c3e50', verbose_name="Texte principal")
    couleur_texte_secondaire = models.CharField(max_length=7, default='#7f8c8d', verbose_name="Texte secondaire")
    
    # Couleurs de fond
    couleur_fond_header = models.CharField(max_length=7, default='#2c3e50', verbose_name="Fond en-tête")
    couleur_fond_tableau = models.CharField(max_length=7, default='#ecf0f1', verbose_name="Fond tableau")
    couleur_fond_carte = models.CharField(max_length=7, default='#ffffff', verbose_name="Fond cartes")
    
    # Couleurs des bordures
    couleur_bordure = models.CharField(max_length=7, default='#bdc3c7', verbose_name="Bordures")
    
    # Couleurs des mentions
    couleur_mention_tb = models.CharField(max_length=7, default='#27ae60', verbose_name="Mention Très Bien")
    couleur_mention_bien = models.CharField(max_length=7, default='#3498db', verbose_name="Mention Bien")
    couleur_mention_ab = models.CharField(max_length=7, default='#f39c12', verbose_name="Mention Assez Bien")
    couleur_mention_passable = models.CharField(max_length=7, default='#e67e22', verbose_name="Mention Passable")
    couleur_mention_insuffisant = models.CharField(max_length=7, default='#e74c3c', verbose_name="Mention Insuffisant")
    
    # Paramètres
    actif = models.BooleanField(default=False, verbose_name="Thème actif")
    par_defaut = models.BooleanField(default=False, verbose_name="Thème par défaut")
    
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Thème de bulletin"
        verbose_name_plural = "Thèmes de bulletin"
        ordering = ['-par_defaut', '-actif', 'nom']
    
    def __str__(self):
        return f"{self.nom}" + (" (Actif)" if self.actif else "") + (" (Par défaut)" if self.par_defaut else "")
    
    def save(self, *args, **kwargs):
        # Si ce thème est marqué comme par défaut, désactiver les autres
        if self.par_defaut:
            ThemeBulletin.objects.filter(ecole=self.ecole, par_defaut=True).exclude(id=self.id).update(par_defaut=False)
        super().save(*args, **kwargs)


# Signaux pour l'invalidation automatique du cache des rangs
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .utils_rangs import invalider_cache_rangs

@receiver(post_save, sender=NoteMensuelle)
@receiver(post_delete, sender=NoteMensuelle)
def invalider_cache_note_mensuelle(sender, instance, **kwargs):
    """Invalide le cache des rangs quand une note mensuelle est modifiée"""
    try:
        invalider_cache_rangs(instance.matiere.classe, instance.mois)
        print(f"Cache invalidé pour {instance.matiere.classe.nom} - {instance.mois}")
    except Exception as e:
        print(f"Erreur invalidation cache: {e}")

@receiver(post_save, sender=CompositionNote)
@receiver(post_delete, sender=CompositionNote)
def invalider_cache_composition(sender, instance, **kwargs):
    """Invalide le cache des rangs et moyennes quand une composition change"""
    try:
        invalider_cache_rangs(instance.matiere.classe, instance.periode)
        print(f"Cache invalidé pour {instance.matiere.classe.nom} - {instance.periode}")
    except Exception as e:
        print(f"Erreur invalidation cache: {e}")

@receiver(post_save, sender=NoteEleve)
@receiver(post_delete, sender=NoteEleve)
def invalider_cache_note_eleve(sender, instance, **kwargs):
    """Invalide le cache des rangs quand une note d'évaluation est modifiée"""
    try:
        invalider_cache_rangs(instance.evaluation.matiere.classe, instance.evaluation.periode)
        print(f"Cache invalidé pour {instance.evaluation.matiere.classe.nom} - {instance.evaluation.periode}")
    except Exception as e:
        print(f"Erreur invalidation cache: {e}")


# ============================================================================
# MODÈLES POUR L'ÉVALUATION MATERNELLE
# ============================================================================

class EvaluationMaternelle(SyncTrackedModel):
    """Évaluation complète pour un élève de maternelle"""
    from eleves.models import Eleve
    
    # Choix pour les lettres d'appréciation
    LETTRE_CHOICES = [
        ('A+', 'A+ - Excellent (10)'),
        ('A', 'A - Très bien (9,5)'),
        ('B+', 'B+ - Bien (8-9)'),
        ('B', 'B - Assez bien (7)'),
        ('B-', 'B- - Moyen (6)'),
        ('C', 'C - Passable (5-5,75)'),
        ('D', 'D - Éprouve des difficultés (3-4)'),
    ]
    
    TRIMESTRE_CHOICES = [
        ('TRIMESTRE_1', 'Trimestre 1'),
        ('TRIMESTRE_2', 'Trimestre 2'),
        ('TRIMESTRE_3', 'Trimestre 3'),
    ]
    
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, related_name='evaluations_maternelle')
    classe = models.ForeignKey(ClasseNote, on_delete=models.CASCADE, related_name='evaluations_maternelle')
    trimestre = models.CharField(max_length=20, choices=TRIMESTRE_CHOICES, verbose_name="Trimestre")
    annee_scolaire = models.CharField(max_length=9, verbose_name="Année scolaire")
    
    # Métadonnées
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='evaluations_maternelle_creees')
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Évaluation maternelle"
        verbose_name_plural = "Évaluations maternelle"
        ordering = ['eleve', 'trimestre']
        unique_together = ['eleve', 'classe', 'trimestre', 'annee_scolaire']
    
    def __str__(self):
        return f"{self.eleve} - {self.get_trimestre_display()} ({self.annee_scolaire})"
    
    def get_moyenne_generale(self):
        """Calcule la moyenne générale des notes"""
        notes = self.notes_matieres.exclude(note__isnull=True)
        if not notes.exists():
            return None
        total = sum(n.note for n in notes if n.note is not None)
        return round(total / notes.count(), 2)
    
    def get_lettre_generale(self):
        """Retourne la lettre correspondant à la moyenne générale"""
        moyenne = self.get_moyenne_generale()
        if moyenne is None:
            return None
        return self.note_vers_lettre(moyenne)
    
    @staticmethod
    def note_vers_lettre(note):
        """Convertit une note en lettre d'appréciation"""
        if note >= 10:
            return 'A+'
        elif note >= 9.5:
            return 'A'
        elif note >= 8:
            return 'B+'
        elif note >= 7:
            return 'B'
        elif note >= 6:
            return 'B-'
        elif note >= 5:
            return 'C'
        else:
            return 'D'
    
    @staticmethod
    def lettre_vers_mention(lettre):
        """Convertit une lettre en mention textuelle"""
        mentions = {
            'A+': 'Excellent',
            'A': 'Très bien',
            'B+': 'Bien',
            'B': 'Assez bien',
            'B-': 'Moyen',
            'C': 'Passable',
            'D': 'Éprouve des difficultés'
        }
        return mentions.get(lettre, '')


class NoteMaternelle(SyncTrackedModel):
    """Note pour une matière dans une évaluation maternelle"""
    
    evaluation = models.ForeignKey(EvaluationMaternelle, on_delete=models.CASCADE, related_name='notes_matieres')
    matiere = models.ForeignKey(MatiereNote, on_delete=models.CASCADE, related_name='notes_maternelle')
    note = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True, verbose_name="Note sur 10")
    lettre = models.CharField(max_length=2, blank=True, verbose_name="Lettre")
    commentaire = models.TextField(blank=True, null=True, verbose_name="Commentaire")
    
    class Meta:
        verbose_name = "Note maternelle"
        verbose_name_plural = "Notes maternelle"
        unique_together = ['evaluation', 'matiere']
    
    def save(self, *args, **kwargs):
        # Calcul automatique de la lettre en fonction de la note
        if self.note is not None:
            self.lettre = EvaluationMaternelle.note_vers_lettre(float(self.note))
        super().save(*args, **kwargs)
    
    def get_mention(self):
        """Retourne la mention correspondant à la lettre"""
        return EvaluationMaternelle.lettre_vers_mention(self.lettre)
    
    def __str__(self):
        return f"{self.matiere.nom} - {self.lettre} ({self.note}/10)"


class AnalyseTravailMaternelle(SyncTrackedModel):
    """Analyse du travail de l'enfant pour une évaluation maternelle"""
    
    evaluation = models.OneToOneField(EvaluationMaternelle, on_delete=models.CASCADE, related_name='analyse_travail')
    
    # Options d'analyse (cases à cocher)
    comprend_demandes = models.BooleanField(default=False, verbose_name="L'enfant comprend ce qu'on lui demande")
    ne_comprend_pas = models.BooleanField(default=False, verbose_name="L'enfant ne comprend pas ce qu'on lui demande")
    trop_jeune = models.BooleanField(default=False, verbose_name="L'enfant est trop jeune pour cette classe")
    fixe_attention = models.BooleanField(default=False, verbose_name="L'enfant fixe son attention")
    pas_probleme_monitrice = models.BooleanField(default=False, verbose_name="L'enfant n'a pas de problème avec sa monitrice")
    pas_probleme_camarades = models.BooleanField(default=False, verbose_name="L'enfant n'a pas de problème avec ses camarades")
    pas_probleme_famille = models.BooleanField(default=False, verbose_name="L'enfant n'a pas de problème avec sa famille")
    est_doue = models.BooleanField(default=False, verbose_name="L'enfant est doué")
    est_paresseux = models.BooleanField(default=False, verbose_name="L'enfant est paresseux")
    
    # Commentaire libre
    commentaire = models.TextField(blank=True, null=True, verbose_name="Commentaire supplémentaire")
    
    class Meta:
        verbose_name = "Analyse du travail (maternelle)"
        verbose_name_plural = "Analyses du travail (maternelle)"
    
    def __str__(self):
        return f"Analyse - {self.evaluation.eleve}"
    
    def get_analyses_selectionnees(self):
        """Retourne la liste des analyses sélectionnées"""
        analyses = []
        if self.comprend_demandes:
            analyses.append("L'enfant comprend ce qu'on lui demande")
        if self.ne_comprend_pas:
            analyses.append("L'enfant ne comprend pas ce qu'on lui demande")
        if self.trop_jeune:
            analyses.append("L'enfant est trop jeune pour cette classe")
        if self.fixe_attention:
            analyses.append("L'enfant fixe son attention")
        if self.pas_probleme_monitrice:
            analyses.append("L'enfant n'a pas de problème avec sa monitrice")
        if self.pas_probleme_camarades:
            analyses.append("L'enfant n'a pas de problème avec ses camarades")
        if self.pas_probleme_famille:
            analyses.append("L'enfant n'a pas de problème avec sa famille")
        if self.est_doue:
            analyses.append("L'enfant est doué")
        if self.est_paresseux:
            analyses.append("L'enfant est paresseux")
        return analyses


class RecommandationMaternelle(SyncTrackedModel):
    """Recommandations de la monitrice pour une évaluation maternelle"""
    
    evaluation = models.OneToOneField(EvaluationMaternelle, on_delete=models.CASCADE, related_name='recommandations')
    
    # Options de recommandations (cases à cocher)
    encourager_feliciter = models.BooleanField(default=False, verbose_name="Enfant à encourager et à féliciter")
    suivre_domicile = models.BooleanField(default=False, verbose_name="Enfant à suivre à domicile")
    gouter_dans_sac = models.BooleanField(default=False, verbose_name="Mettre le goûter dans le sac de l'enfant")
    aide_encouragement_parents = models.BooleanField(default=False, verbose_name="L'enfant a besoin d'aide et d'encouragement des parents")
    amour_parental = models.BooleanField(default=False, verbose_name="L'enfant a besoin de l'amour maternel et paternel")
    besoin_epanouissement = models.BooleanField(default=False, verbose_name="L'enfant a besoin d'être épanoui")
    sorties_educatives = models.BooleanField(default=False, verbose_name="L'enfant a besoin de sorties éducatives et récréatives")
    aide_intellectuelle = models.BooleanField(default=False, verbose_name="L'enfant a besoin de l'aide de la monitrice et des parents pour développer ses facultés intellectuelles")
    douceur_patience = models.BooleanField(default=False, verbose_name="L'enfant doit être pris avec beaucoup de douceur et de patience")
    besoin_fermete = models.BooleanField(default=False, verbose_name="L'enfant a besoin de fermeté")
    esprit_inferiorite = models.BooleanField(default=False, verbose_name="L'enfant a un esprit d'infériorité")
    attention_particuliere = models.BooleanField(default=False, verbose_name="L'enfant a besoin d'une attention particulière des parents")
    
    # Commentaire libre
    commentaire = models.TextField(blank=True, null=True, verbose_name="Recommandation personnalisée")
    
    class Meta:
        verbose_name = "Recommandation (maternelle)"
        verbose_name_plural = "Recommandations (maternelle)"
    
    def __str__(self):
        return f"Recommandations - {self.evaluation.eleve}"
    
    def get_recommandations_selectionnees(self):
        """Retourne la liste des recommandations sélectionnées"""
        recommandations = []
        if self.encourager_feliciter:
            recommandations.append("Enfant à encourager et à féliciter")
        if self.suivre_domicile:
            recommandations.append("Enfant à suivre à domicile")
        if self.gouter_dans_sac:
            recommandations.append("Mettre le goûter dans le sac de l'enfant")
        if self.aide_encouragement_parents:
            recommandations.append("L'enfant a besoin d'aide et d'encouragement des parents")
        if self.amour_parental:
            recommandations.append("L'enfant a besoin de l'amour maternel et paternel")
        if self.besoin_epanouissement:
            recommandations.append("L'enfant a besoin d'être épanoui")
        if self.sorties_educatives:
            recommandations.append("L'enfant a besoin de sorties éducatives et récréatives")
        if self.aide_intellectuelle:
            recommandations.append("L'enfant a besoin de l'aide de la monitrice et des parents pour développer ses facultés intellectuelles")
        if self.douceur_patience:
            recommandations.append("L'enfant doit être pris avec beaucoup de douceur et de patience")
        if self.besoin_fermete:
            recommandations.append("L'enfant a besoin de fermeté")
        if self.esprit_inferiorite:
            recommandations.append("L'enfant a un esprit d'infériorité")
        if self.attention_particuliere:
            recommandations.append("L'enfant a besoin d'une attention particulière des parents")
        return recommandations


class Classement(SyncTrackedModel):
    """Stocke les moyennes et rangs calculés pour garantir la cohérence"""
    eleve = models.ForeignKey('eleves.Eleve', on_delete=models.CASCADE, related_name='classements')
    classe = models.ForeignKey(ClasseNote, on_delete=models.CASCADE, related_name='classements')
    
    # Période
    periode = models.CharField(max_length=50, verbose_name="Période")  # TRIMESTRE_1, SEMESTRE_1, NOVEMBRE, etc.
    annee_scolaire = models.CharField(max_length=9, verbose_name="Année scolaire")
    
    # Moyennes calculées
    moyenne_generale = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Moyenne générale")
    total_points = models.DecimalField(max_digits=8, decimal_places=2, verbose_name="Total points")
    total_coefficients = models.DecimalField(max_digits=6, decimal_places=2, verbose_name="Total coefficients")
    
    # Rang
    rang = models.PositiveIntegerField(verbose_name="Rang")
    rang_formate = models.CharField(max_length=20, verbose_name="Rang formaté")  # "1er/31", "2ème/31", etc.
    effectif = models.PositiveIntegerField(verbose_name="Effectif de la classe")
    
    # Mention et appréciation
    mention = models.CharField(max_length=50, blank=True, verbose_name="Mention")
    appreciation = models.TextField(blank=True, verbose_name="Appréciation")
    
    # Métadonnées
    date_calcul = models.DateTimeField(auto_now=True, verbose_name="Date du calcul")
    calcule_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name = "Classement"
        verbose_name_plural = "Classements"
        ordering = ['classe', 'periode', 'rang']
        unique_together = ['eleve', 'classe', 'periode', 'annee_scolaire']
        indexes = [
            models.Index(fields=['classe', 'periode', 'annee_scolaire']),
            models.Index(fields=['eleve', 'periode']),
        ]
    
    def __str__(self):
        return f"{self.eleve} - {self.periode} - {self.rang_formate}"


# ============================================================================
# ACTIVITÉS JOURNALIÈRES
# ============================================================================

class ActiviteJournaliere(SyncTrackedModel):
    """Activité ou fait de vie scolaire concernant un élève."""
    TYPE_CHOICES = [
        ('ABSENCE', 'Absence'),
        ('RETARD', 'Retard'),
        ('DISCIPLINE', 'Discipline'),
        ('CONVOCATION', 'Convocation parent'),
        ('EVALUATION', 'Évaluation'),
        ('SPORTIVE', 'Sportive'),
        ('CULTURELLE', 'Culturelle'),
        ('ARTISTIQUE', 'Artistique'),
        ('SORTIE', 'Sortie éducative'),
        ('AUTRE', 'Autre'),
    ]

    classe = models.ForeignKey(ClasseNote, on_delete=models.CASCADE, related_name='activites_journalieres')
    eleve = models.ForeignKey('eleves.Eleve', on_delete=models.CASCADE, related_name='activites_journalieres')
    date = models.DateField(verbose_name="Date de l'activité")
    type_activite = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name="Type d'observation")
    titre = models.CharField(max_length=200, verbose_name="Titre de l'activité")
    description = models.TextField(blank=True, verbose_name="Description / Observation")
    appreciation = models.CharField(max_length=100, blank=True, verbose_name="Appréciation")

    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Observation de vie scolaire"
        verbose_name_plural = "Observations de vie scolaire"
        ordering = ['-date', '-date_creation']
        indexes = [
            models.Index(fields=['classe', 'date']),
            models.Index(fields=['eleve', 'date']),
        ]

    def __str__(self):
        return f"{self.eleve} - {self.titre} ({self.date})"


class PieceJointeActivite(SyncTrackedModel):
    """Fichier joint à une activité (copie d'évaluation, photo sportive, etc.)"""
    activite = models.ForeignKey(ActiviteJournaliere, on_delete=models.CASCADE, related_name='pieces_jointes')
    fichier = models.FileField(upload_to='activites_journalieres/%Y/%m/', verbose_name="Fichier")
    legende = models.CharField(max_length=255, blank=True, verbose_name="Légende")
    date_ajout = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Pièce jointe"
        verbose_name_plural = "Pièces jointes"

    def __str__(self):
        return self.legende or self.fichier.name

    @property
    def is_image(self):
        ext = self.fichier.name.lower().split('.')[-1] if self.fichier else ''
        return ext in ('jpg', 'jpeg', 'png', 'gif', 'webp')


class ActiviteCulturelle(models.Model):
    """Activité culturelle de l'école (fête, sortie, spectacle...) publiée sur le site public."""
    titre = models.CharField(max_length=200, verbose_name="Titre de l'activité")
    description = models.TextField(verbose_name="Description")
    image = models.ImageField(
        upload_to='activites_culturelles/', verbose_name="Image",
        help_text="Photo de l'activité (max 3 Mo)",
        validators=[validate_photo_size]
    )
    date_activite = models.DateField(blank=True, null=True, verbose_name="Date de l'activité")
    publie = models.BooleanField(
        default=True, verbose_name="Publié sur le site",
        help_text="Décocher pour masquer l'activité de la page publique"
    )
    ecole = models.ForeignKey(
        Ecole, on_delete=models.CASCADE, related_name='activites_culturelles',
        blank=True, null=True
    )
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Activité culturelle"
        verbose_name_plural = "Activités culturelles"
        ordering = ['-date_activite', '-date_creation']

    def __str__(self):
        return self.titre
