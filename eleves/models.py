from django.db import models
from django.contrib.auth.models import User
from django.core.validators import RegexValidator
from decimal import Decimal
import unicodedata
from synchronisation.mixins import SyncTrackedModel
from eleves.validators import validate_photo_size, validate_logo_size

class Ecole(SyncTrackedModel):
    """Modèle pour représenter une école"""
    ETAT_CHOICES = [
        ("BROUILLON", "Brouillon"),
        ("EN_ATTENTE", "En attente de validation"),
        ("VALIDE", "Validée"),
        ("REJETE", "Rejetée"),
    ]
    nom = models.CharField(max_length=200, verbose_name="Nom de l'école")
    adresse = models.TextField(verbose_name="Adresse")
    telephone = models.CharField(
        max_length=20, 
        validators=[RegexValidator(r'^\+224\d{8,9}$', 'Format: +224XXXXXXXXX')],
        verbose_name="Téléphone principal"
    )
    telephone2 = models.CharField(
        max_length=20, blank=True, null=True,
        validators=[RegexValidator(r'^\+224\d{8,9}$', 'Format: +224XXXXXXXXX')],
        verbose_name="Téléphone 2"
    )
    telephone3 = models.CharField(
        max_length=20, blank=True, null=True,
        validators=[RegexValidator(r'^\+224\d{8,9}$', 'Format: +224XXXXXXXXX')],
        verbose_name="Téléphone 3"
    )
    email = models.EmailField(blank=True, null=True, verbose_name="Email")
    directeur = models.CharField(max_length=100, verbose_name="Directeur")
    censeur = models.CharField(max_length=100, blank=True, null=True, verbose_name="Censeur de l'établissement")
    logo = models.ImageField(
        upload_to='ecoles/logos/', blank=True, null=True,
        validators=[validate_logo_size]
    )
    image = models.ImageField(upload_to='ecoles/images/', blank=True, null=True,
                              verbose_name="Photo de l'ecole",
                              help_text="Photo du batiment de l'ecole (affichee sur le livret scolaire)",
                              validators=[validate_photo_size])
    # Préfixe explicite pour les matricules (ex: "AL-FUR/")
    code_prefixe = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name="Préfixe matricules",
        help_text="Préfixe d'école pour les matricules, ex: AL-FUR/ (laisser vide pour ne pas utiliser)"
    )
    # Informations officielles pour entête des bulletins
    ire = models.CharField(max_length=100, blank=True, null=True, verbose_name="IRE")
    dpe = models.CharField(max_length=100, blank=True, null=True, verbose_name="DPE")
    desee = models.CharField(max_length=100, blank=True, null=True, verbose_name="DESEE")
    date_creation = models.DateTimeField(auto_now_add=True)
    etat = models.CharField(max_length=20, choices=ETAT_CHOICES, default="BROUILLON", db_index=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='ecoles_creees')
    
    class Meta:
        verbose_name = "École"
        verbose_name_plural = "Écoles"
    
    def save(self, *args, **kwargs):
        # Normaliser le code_prefixe: supprimer doublons ('AL-FUR/AL-FUR/') et assurer un seul '/'
        try:
            if self.code_prefixe is not None:
                self.code_prefixe = _normalize_code_prefixe(self.code_prefixe)
        except Exception:
            pass
        super().save(*args, **kwargs)
    
    @property
    def tous_telephones(self):
        """Retourne tous les numéros de téléphone séparés par ' / '"""
        nums = [self.telephone]
        if self.telephone2:
            nums.append(self.telephone2)
        if self.telephone3:
            nums.append(self.telephone3)
        return ' / '.join(nums)
    
    def __str__(self):
        return self.nom

class Classe(SyncTrackedModel):
    """Modèle pour représenter une classe"""
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
    
    ecole = models.ForeignKey(Ecole, on_delete=models.CASCADE, related_name='classes')
    nom = models.CharField(max_length=100, verbose_name="Nom de la classe")
    niveau = models.CharField(max_length=20, choices=NIVEAUX_CHOICES, verbose_name="Niveau")
    code_matricule = models.CharField(
        max_length=12,
        blank=True,
        null=True,
        verbose_name="Code matricule",
        help_text="Préfixe utilisé pour les matricules (ex: PN3, CN7, L11SL)."
    )
    annee_scolaire = models.CharField(max_length=9, verbose_name="Année scolaire", help_text="Format: 2024-2025")
    capacite_max = models.PositiveIntegerField(default=30, verbose_name="Capacité maximale")
    
    class Meta:
        verbose_name = "Classe"
        verbose_name_plural = "Classes"
        unique_together = ['ecole', 'nom', 'annee_scolaire']
        indexes = [
            models.Index(fields=['ecole', 'niveau']),
            models.Index(fields=['ecole', 'annee_scolaire']),
            models.Index(fields=['ecole', 'code_matricule']),
        ]
    
    def __str__(self):
        return f"{self.nom} - {self.get_niveau_display()} ({self.annee_scolaire})"
    
    @property
    def nombre_eleves(self):
        return self.eleves.count()

# --- Helper: Resolve class code for matricule generation ---
def _code_classe_from_nom_ou_niveau(classe: "Classe") -> str:
    """Retourne le code matricule à partir du nom (prioritaire) ou du niveau de la classe.
    Mapping fourni par l'utilisateur. Si aucun mapping trouvé, retourne une chaîne vide.
    """
    # 1) Si le champ dédié est renseigné, on l'utilise en priorité
    code_direct = getattr(classe, 'code_matricule', None)
    if code_direct:
        return code_direct.strip()
    # Mapping par nom exact (insensible à la casse/espaces superflus)
    mapping_nom = {
        "garderie": "GA",
        "petite section": "MPS",
        "moyen section": "MMS",
        "moyenne section": "MMS",
        "ps": "MPS",
        "ms": "MMS",
        "gs": "MGS",
        "grande section": "MGS",
        "1ère année": "PN1",
        "2ème année": "PN2",
        "3ème année": "PN3",
        "4ème année": "PN4",
        "5ème année": "PN5",
        "6ème année": "PN6",
        "7ème année": "CN7",
        "8ème année": "CN8",
        "9ème année": "CN9",
        "10ème année": "CN10",
        "11ème série littéraire": "L11SL",
        "11ème série scientifique i": "L11SSI",
        "11ème série scientifique ii": "L11SSII",
        "12ème ss": "L12SS",
        "12ème sm": "L12SM",
        "12ème se": "L12SE",
        "terminale ss": "TSS",
        "terminale se": "TSE",
        "terminale sm": "TSM",
    }

    # Normalisation robuste: suppression accents/espaces multiples, lower
    def _normalize_nom(value: str) -> str:
        try:
            s = (value or "").strip().lower()
            s = unicodedata.normalize('NFD', s)
            s = ''.join(ch for ch in s if unicodedata.category(ch) != 'Mn')  # remove accents
            # Uniformiser espaces
            s = ' '.join(s.split())
            return s
        except Exception:
            return ""

# --- Helper: Normalize school prefix like 'AL-FUR/' and avoid duplicates 'AL-FUR/AL-FUR/' ---
def _normalize_code_prefixe(value: str) -> str:
    """Normalize a school code prefix:
    - Trim spaces
    - Split on '/'
    - Remove empty parts
    - Collapse immediate duplicate segments (e.g., ['AL-FUR','AL-FUR'] -> ['AL-FUR'])
    - Join back with one '/'
    - Ensure trailing '/'
    """
    try:
        s = (value or "").strip()
        if not s:
            return ""
        parts = [p.strip() for p in s.split('/') if p.strip()]
        # Collapse duplicates
        normalized_parts = []
        for p in parts:
            if not normalized_parts or normalized_parts[-1] != p:
                normalized_parts.append(p)
        if not normalized_parts:
            return ""
        return "/".join(normalized_parts).rstrip('/') + "/"
    except Exception:
        return ""

    nom_norm = _normalize_nom(getattr(classe, 'nom', ''))
    code = mapping_nom.get(nom_norm, "")
    if code:
        return code

    # Fallback basique sur niveau si le nom ne correspond pas
    niveau = getattr(classe, "niveau", "")
    fallback_niveau = {
        "GARDERIE": "GA",
        "PRIMAIRE_1": "PN1",
        "PRIMAIRE_2": "PN2",
        "PRIMAIRE_3": "PN3",
        "PRIMAIRE_4": "PN4",
        "PRIMAIRE_5": "PN5",
        "PRIMAIRE_6": "PN6",
        "COLLEGE_7": "CN7",
        "COLLEGE_8": "CN8",
        "COLLEGE_9": "CN9",
        "COLLEGE_10": "CN10",
        "LYCEE_11": "L11",
        "LYCEE_12": "L12",
        "TERMINALE": "T",
    }
    code_fb = fallback_niveau.get(niveau, "")
    if code_fb:
        return code_fb

    # Fallback avancé basé sur motifs (ex: 1ere/2eme annee, 11eme/12eme, terminale)
    nom_tokens = nom_norm
    # Détection des années 1-10 → PN/CN
    import re
    m = re.search(r"\b(1|2|3|4|5|6|7|8|9|10)\b", nom_tokens)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 6:
            return f"PN{n}"
        if 7 <= n <= 10:
            return f"CN{n}"

    # 11ème séries
    if '11' in nom_tokens:
        if 'litteraire' in nom_tokens:
            return 'L11SL'
        if 'scientifique' in nom_tokens:
            if 'ii' in nom_tokens or '2' in nom_tokens:
                return 'L11SSII'
            return 'L11SSI'
        return 'L11'

    # 12ème séries
    if '12' in nom_tokens:
        if 'ss' in nom_tokens:
            return 'L12SS'
        if 'sm' in nom_tokens:
            return 'L12SM'
        if 'se' in nom_tokens:
            return 'L12SE'
        return 'L12'

    # Terminale séries
    if 'terminale' in nom_tokens:
        if 'ss' in nom_tokens:
            return 'TSS'
        if 'se' in nom_tokens:
            return 'TSE'
        if 'sm' in nom_tokens:
            return 'TSM'
        return 'T'

    # Dernier recours: vide → le save() appliquera le fallback CL{id}
    return ""

class Responsable(SyncTrackedModel):
    """Modèle pour représenter un responsable d'élève"""
    RELATION_CHOICES = [
        ('PERE', 'Père'),
        ('MERE', 'Mère'),
        ('TUTEUR', 'Tuteur'),
        ('TUTRICE', 'Tutrice'),
        ('GRAND_PERE', 'Grand-père'),
        ('GRAND_MERE', 'Grand-mère'),
        ('ONCLE', 'Oncle'),
        ('TANTE', 'Tante'),
        ('AUTRE', 'Autre'),
    ]
    
    prenom = models.CharField(max_length=100, verbose_name="Prénom")
    nom = models.CharField(max_length=100, verbose_name="Nom")
    relation = models.CharField(max_length=20, choices=RELATION_CHOICES, verbose_name="Relation")
    telephone = models.CharField(
        max_length=20, 
        validators=[RegexValidator(r'^\+224\d{8,9}$', 'Format: +224XXXXXXXXX')],
        verbose_name="Téléphone"
    )
    email = models.EmailField(blank=True, null=True, verbose_name="Email")
    adresse = models.TextField(verbose_name="Adresse")
    profession = models.CharField(max_length=100, blank=True, null=True, verbose_name="Profession")
    
    class Meta:
        verbose_name = "Responsable"
        verbose_name_plural = "Responsables"
    
    def __str__(self):
        return f"{self.prenom} {self.nom} ({self.get_relation_display()})"

    @property
    def nom_complet(self) -> str:
        """Retourne le nom complet du responsable (Prénom Nom)."""
        return f"{self.prenom} {self.nom}"

class GrilleTarifaire(SyncTrackedModel):
    """Modèle pour les grilles tarifaires par école et niveau"""
    ecole = models.ForeignKey(Ecole, on_delete=models.CASCADE, related_name='grilles_tarifaires')
    niveau = models.CharField(max_length=20, choices=Classe.NIVEAUX_CHOICES, verbose_name="Niveau")
    annee_scolaire = models.CharField(max_length=9, verbose_name="Année scolaire")
    
    # Frais d'inscription
    frais_inscription = models.DecimalField(
        max_digits=10, decimal_places=0, default=Decimal('0'),
        verbose_name="Frais d'inscription (GNF)"
    )
    # Frais de réinscription (peut être différent)
    frais_reinscription = models.DecimalField(
        max_digits=10, decimal_places=0, default=Decimal('0'),
        verbose_name="Frais de réinscription (GNF)"
    )
    
    # Frais de scolarité par tranches
    tranche_1 = models.DecimalField(
        max_digits=10, decimal_places=0, default=Decimal('0'),
        verbose_name="1ère tranche (GNF)"
    )
    tranche_2 = models.DecimalField(
        max_digits=10, decimal_places=0, default=Decimal('0'),
        verbose_name="2ème tranche (GNF)"
    )
    tranche_3 = models.DecimalField(
        max_digits=10, decimal_places=0, default=Decimal('0'),
        verbose_name="3ème tranche (GNF)"
    )
    
    # Périodes de paiement
    periode_1 = models.CharField(max_length=50, default="À l'inscription", verbose_name="Période 1")
    periode_2 = models.CharField(max_length=50, default="Début janvier", verbose_name="Période 2")
    periode_3 = models.CharField(max_length=50, default="Début mars", verbose_name="Période 3")
    # Échéances par défaut (optionnelles) pour initialiser les échéanciers des élèves
    # Si non renseignées, la logique applicative utilisera des valeurs par défaut (15/01, 15/03, 15/05)
    date_echeance_inscription_defaut = models.DateField(
        null=True, blank=True, verbose_name="Échéance inscription (défaut)"
    )
    date_echeance_tranche_1_defaut = models.DateField(
        null=True, blank=True, verbose_name="Échéance Tranche 1 (défaut)"
    )
    date_echeance_tranche_2_defaut = models.DateField(
        null=True, blank=True, verbose_name="Échéance Tranche 2 (défaut)"
    )
    date_echeance_tranche_3_defaut = models.DateField(
        null=True, blank=True, verbose_name="Échéance Tranche 3 (défaut)"
    )
    
    date_creation = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Grille tarifaire"
        verbose_name_plural = "Grilles tarifaires"
        unique_together = ['ecole', 'niveau', 'annee_scolaire']
    
    def __str__(self):
        return f"{self.ecole.nom} - {self.get_niveau_display()} ({self.annee_scolaire})"
    
    @property
    def total_scolarite(self):
        return self.tranche_1 + self.tranche_2 + self.tranche_3
    
    @property
    def total_avec_inscription(self):
        return self.frais_inscription + self.total_scolarite

class Eleve(SyncTrackedModel):
    """Modèle principal pour représenter un élève"""
    SEXE_CHOICES = [
        ('M', 'Masculin'),
        ('F', 'Féminin'),
    ]
    
    STATUT_CHOICES = [
        ('ACTIF', 'Actif'),
        ('SUSPENDU', 'Suspendu'),
        ('EXCLU', 'Exclu'),
        ('TRANSFERE', 'Transféré'),
        ('DIPLOME', 'Diplômé'),
    ]
    
    # Informations personnelles
    matricule = models.CharField(max_length=20, unique=True, verbose_name="Matricule")
    prenom = models.CharField(max_length=100, verbose_name="Prénom")
    nom = models.CharField(max_length=100, verbose_name="Nom")
    sexe = models.CharField(max_length=1, choices=SEXE_CHOICES, verbose_name="Sexe")
    date_naissance = models.DateField(verbose_name="Date de naissance", blank=True, null=True)
    lieu_naissance = models.CharField(max_length=100, verbose_name="Lieu de naissance", blank=True, null=True)
    photo = models.ImageField(
        upload_to='eleves/photos/', blank=True, null=True, verbose_name="Photo",
        validators=[validate_photo_size]
    )

    # Informations médicales
    GROUPE_SANGUIN_CHOICES = [
        ('A+', 'A+'), ('A-', 'A-'),
        ('B+', 'B+'), ('B-', 'B-'),
        ('AB+', 'AB+'), ('AB-', 'AB-'),
        ('O+', 'O+'), ('O-', 'O-'),
    ]
    groupe_sanguin = models.CharField(
        max_length=3, choices=GROUPE_SANGUIN_CHOICES, blank=True, null=True,
        verbose_name="Groupe sanguin"
    )
    allergies = models.TextField(
        blank=True, null=True, verbose_name="Allergies",
        help_text="Allergies connues (alimentaires, médicamenteuses, etc.)"
    )
    maladies_chroniques = models.TextField(
        blank=True, null=True, verbose_name="Maladies chroniques / antécédents médicaux"
    )
    traitement_en_cours = models.TextField(
        blank=True, null=True, verbose_name="Traitement en cours",
        help_text="Médicaments pris régulièrement, posologie"
    )
    observations_medicales = models.TextField(
        blank=True, null=True, verbose_name="Observations médicales",
        help_text="Toute autre information utile pour le personnel encadrant (régime alimentaire, peur particulière, etc.)"
    )

    # Scolarité
    classe = models.ForeignKey(Classe, on_delete=models.CASCADE, related_name='eleves')
    date_inscription = models.DateField(verbose_name="Date d'inscription", blank=True, null=True)
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='ACTIF', verbose_name="Statut", db_index=True)
    
    # Responsables
    responsable_principal = models.ForeignKey(
        Responsable, on_delete=models.SET_NULL, 
        related_name='eleves_principal', verbose_name="Responsable principal",
        blank=True, null=True
    )
    responsable_secondaire = models.ForeignKey(
        Responsable, on_delete=models.SET_NULL, 
        related_name='eleves_secondaire', blank=True, null=True,
        verbose_name="Responsable secondaire"
    )
    
    # Métadonnées
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name = "Élève"
        verbose_name_plural = "Élèves"
        ordering = ['nom', 'prenom']
        indexes = [
            models.Index(fields=['classe', 'statut']),
            models.Index(fields=['nom', 'prenom']),
            models.Index(fields=['date_inscription']),
        ]
    
    def __str__(self):
        return f"{self.matricule} - {self.prenom} {self.nom}"
    
    @property
    def nom_complet(self):
        return f"{self.prenom} {self.nom}"
    
    @property
    def age(self):
        from datetime import date
        if not self.date_naissance:
            return None
        today = date.today()
        return today.year - self.date_naissance.year - ((today.month, today.day) < (self.date_naissance.month, self.date_naissance.day))

    def _reaffecter_matricules_ancienne_classe(self, ancienne_classe, ancien_matricule):
        """Désactivée pour éviter les conflits UNIQUE"""
        pass
    def save(self, *args, **kwargs):
        """Génère automatiquement le matricule au format CODE-### si absent.
        - CODE déterminé par la classe via `_code_classe_from_nom_ou_niveau`
        - ### est une séquence à 3 chiffres, incrémentée par classe (et donc par école)
        - Si des matricules existants de la classe contiennent un préfixe d'école (ex: "AL-FUR/PN4-001"),
          ce préfixe est détecté et conservé pour les nouveaux matricules de la même classe.
        - Si la classe change, le matricule est automatiquement régénéré avec le code de la nouvelle classe.
        - NOUVEAU: Réaffectation intelligente des matricules de l'ancienne classe pour combler le "trou".
        """
        # Détecter un changement de classe pour régénérer le matricule
        regenerer_matricule = False
        ancienne_classe = None
        ancien_matricule = None
        changement_classe_info = None
        reaffecter_ancienne_classe = False
        
        if self.pk:  # Si l'élève existe déjà
            try:
                old_instance = Eleve.objects.get(pk=self.pk)
                if old_instance.classe_id != self.classe_id:
                    # Changement de classe détecté
                    regenerer_matricule = True
                    ancienne_classe = old_instance.classe
                    ancien_matricule = self.matricule
                    reaffecter_ancienne_classe = True
                    # Stocker les infos pour créer l'historique après la sauvegarde
                    changement_classe_info = {
                        'ancienne_classe': old_instance.classe.nom,
                        'nouvelle_classe': self.classe.nom,
                        'ancien_matricule': ancien_matricule,
                        'utilisateur': getattr(self, '_current_user', None)
                    }
            except Eleve.DoesNotExist:
                pass
        
        # Ne générer le matricule automatiquement que si :
        # 1. Il n'y a pas de matricule ou on doit le régénérer (changement de classe)
        # 2. ET qu'on n'a pas demandé de skip la génération (saisie manuelle)
        if (not self.matricule or regenerer_matricule) and getattr(self, 'classe_id', None) and not getattr(self, '_skip_matricule_generation', False):
            code = _code_classe_from_nom_ou_niveau(self.classe)
            # Fallback de sécurité pour éviter un matricule vide si le code n'est pas résolu
            if not code:
                try:
                    cls_id = getattr(self.classe, 'id', None) or 'X'
                except Exception:
                    cls_id = 'X'
                code = f"CL{cls_id}"
            if code:
                import re
                # 1) Déterminer s'il existe un préfixe d'école pour cette classe
                #    On inspecte les matricules existants de la même classe uniquement (reset par classe)
                classe_qs = Eleve.objects.filter(classe=self.classe)
                prefix_ecole = ""  # ex: "AL-FUR/" si présent

                # 1.a) Utiliser en priorité le préfixe explicite de l'école s'il est fourni
                ec_prefix = getattr(self.classe.ecole, 'code_prefixe', None) or ""
                ec_prefix = _normalize_code_prefixe(ec_prefix)
                if ec_prefix:
                    prefix_ecole = ec_prefix
                # Chercher un exemple existant correspondant au motif optionnel prefix + code-###
                exemple = (
                    classe_qs
                    .filter(matricule__contains=f"{code}-")
                    .order_by('-id')
                    .first()
                )
                if not prefix_ecole and exemple:
                    m_pref = re.match(rf"^(.*?/)?{re.escape(code)}-\d+$", exemple.matricule)
                    if m_pref and m_pref.group(1):
                        prefix_ecole = m_pref.group(1)  # conserve le '/'
                # Sinon, essayer d'inférer un préfixe d'école depuis d'autres classes de la même école
                if not prefix_ecole:
                    autre = (
                        Eleve.objects
                        .filter(classe__ecole=self.classe.ecole)
                        .order_by('-id')
                        .first()
                    )
                    if autre:
                        m_ec = re.match(r"^(.*?/)[A-Z0-9]+-\d+$", autre.matricule)
                        if m_ec:
                            prefix_ecole = m_ec.group(1)

                # 2) Calculer le prochain numéro en cherchant GLOBALEMENT tous les matricules avec ce code
                #    pour éviter les conflits UNIQUE (le matricule est unique dans toute la base)
                motif = rf"^(?:.*/)?{re.escape(code)}-(\d+)$"
                next_num = 1
                # Chercher dans TOUS les élèves (pas seulement la classe) pour éviter les conflits
                all_with_code = Eleve.objects.filter(matricule__contains=f"{code}-")
                for e in all_with_code.order_by('-id'):
                    m = re.match(motif, e.matricule)
                    if m:
                        try:
                            num_found = int(m.group(1))
                            if num_found >= next_num:
                                next_num = num_found + 1
                        except Exception:
                            continue

                # 3) Générer un candidat avec ou sans préfixe école détecté, en évitant les collisions
                #    Augmenter le nombre de tentatives et utiliser une approche plus robuste
                max_attempts = 1000
                for _ in range(max_attempts):
                    candidat = f"{prefix_ecole}{code}-{next_num:03d}"
                    if not Eleve.objects.filter(matricule=candidat).exists():
                        self.matricule = candidat
                        break
                    next_num += 1
                else:
                    # Si toutes les tentatives échouent, utiliser un UUID pour garantir l'unicité
                    import uuid
                    self.matricule = f"{prefix_ecole}{code}-{uuid.uuid4().hex[:6].upper()}"

        # Si changement de classe, libérer temporairement le matricule avant réaffectation
        # pour éviter les conflits UNIQUE
        matricule_final = None
        if reaffecter_ancienne_classe and ancienne_classe:
            matricule_final = self.matricule
            # Attribuer un matricule temporaire unique pour libérer l'ancien
            import uuid
            self.matricule = f"TEMP-{uuid.uuid4().hex[:8]}"
        
        super().save(*args, **kwargs)
        
        # Réaffectation intelligente des matricules de l'ancienne classe
        if reaffecter_ancienne_classe and ancienne_classe:
            #self._reaffecter_matricules_ancienne_classe(ancienne_classe, ancien_matricule)
            # Restaurer le matricule final de l'élève transféré
            if matricule_final:
                self.matricule = matricule_final
                super().save(update_fields=['matricule'])
        
        # Créer l'historique du changement de classe après la sauvegarde
        if changement_classe_info:
            # Transférer les notes vers la nouvelle classe
            transfert_result = self._transferer_notes_vers_nouvelle_classe(ancienne_classe, self.classe)
            notes_transferees = transfert_result.get('transferees', 0)
            notes_ignorees = transfert_result.get('ignorees', 0)
            # Stocker le résultat sur l'instance pour que la vue puisse l'afficher
            self._transfert_info = transfert_result

            description = f"Changement de classe: {changement_classe_info['ancienne_classe']} → {changement_classe_info['nouvelle_classe']}. Ancien matricule: {changement_classe_info['ancien_matricule']}, Nouveau matricule: {self.matricule}"
            if notes_transferees > 0:
                description += f". {notes_transferees} note(s) transférée(s) vers la nouvelle classe."
            if notes_ignorees > 0:
                description += f" {notes_ignorees} note(s) non transférée(s) (matières sans équivalent)."

            HistoriqueEleve.objects.create(
                eleve=self,
                action='CHANGEMENT_CLASSE',
                description=description,
                utilisateur=changement_classe_info['utilisateur']
            )
    
    def _transferer_notes_vers_nouvelle_classe(self, ancienne_classe, nouvelle_classe):
        """
        Transfère TOUTES les notes de l'élève vers la nouvelle classe.

        Cherche les matières équivalentes (par code OU par nom) dans la nouvelle ClasseNote
        et met à jour les références des notes.

        Types transférés :
        - NoteMensuelle (notes mensuelles)
        - CompositionNote (compositions)
        - AppreciationMaternelle (appréciations maternelle)
        - NoteEleve (notes d'évaluation)
        - EvaluationMaternelle + NoteMaternelle (évaluations maternelle complètes)
        - BulletinMaternelle (bulletins maternelle)

        Returns:
            int: Nombre total de notes/éléments transférés
        """
        from notes.models import (
            ClasseNote, MatiereNote,
            NoteMensuelle, CompositionNote, NoteEleve, Evaluation,
            AppreciationMaternelle, Classement,
            EvaluationMaternelle, NoteMaternelle, BulletinMaternelle,
        )
        from django.core.cache import cache
        import re as _re
        import logging as _logging

        _logger = _logging.getLogger(__name__)
        notes_transferees = 0
        notes_ignorees = 0

        try:
            # ── Trouver la ClasseNote correspondant à la nouvelle classe ─────
            annee = nouvelle_classe.annee_scolaire

            # Essai 1 : correspondance exacte nom + année
            nouvelle_classe_note = ClasseNote.objects.filter(
                ecole=nouvelle_classe.ecole,
                nom__iexact=nouvelle_classe.nom,
                annee_scolaire=annee,
                actif=True
            ).first()

            # Essai 2 : correspondance nom sans filtre année
            if not nouvelle_classe_note:
                nouvelle_classe_note = ClasseNote.objects.filter(
                    ecole=nouvelle_classe.ecole,
                    nom__iexact=nouvelle_classe.nom,
                    actif=True
                ).first()

            # Essai 3 : correspondance par numéro de niveau (regex exact, pas icontains)
            #   Ex: "3ÈME ANNÉE A" → cherche les ClasseNote dont le nom commence par "3"
            #   IMPORTANT : regex ^\b3\b pour éviter que "3" matche "13"
            if not nouvelle_classe_note:
                chiffres = _re.findall(r'\d+', nouvelle_classe.nom)
                if chiffres:
                    num = chiffres[0]
                    # Chercher les classes qui commencent par ce numéro
                    candidats = ClasseNote.objects.filter(
                        ecole=nouvelle_classe.ecole,
                        annee_scolaire=annee,
                        actif=True
                    )
                    pattern = _re.compile(rf'^{_re.escape(num)}(?:\s|È|E|è|e)', _re.IGNORECASE)
                    for candidat in candidats:
                        if pattern.match(candidat.nom.strip()):
                            nouvelle_classe_note = candidat
                            break

            # Essai 4 : correspondance par niveau
            if not nouvelle_classe_note:
                nouvelle_classe_note = ClasseNote.objects.filter(
                    ecole=nouvelle_classe.ecole,
                    niveau=nouvelle_classe.niveau,
                    annee_scolaire=annee,
                    actif=True
                ).first()

            if not nouvelle_classe_note:
                _logger.warning(
                    f"Transfert notes élève {self.id}: aucune ClasseNote trouvée "
                    f"pour '{nouvelle_classe.nom}' ({annee}). Notes non transférées."
                )
                return {'transferees': 0, 'ignorees': 0, 'classe_note_manquante': True}

            # ── Indexer les matières de la nouvelle classe ────────────────────
            nouvelles_matieres_par_code = {}
            nouvelles_matieres_par_nom = {}
            for m in MatiereNote.objects.filter(classe=nouvelle_classe_note, actif=True):
                if m.code:
                    nouvelles_matieres_par_code[m.code.upper()] = m
                if m.nom:
                    nouvelles_matieres_par_nom[m.nom.upper().strip()] = m

            def trouver_matiere_equivalente(ancienne_matiere):
                """Trouve la matière équivalente par code, puis par nom."""
                if not ancienne_matiere:
                    return None
                # Priorité 1 : code exact
                if ancienne_matiere.code:
                    code = ancienne_matiere.code.upper()
                    if code in nouvelles_matieres_par_code:
                        return nouvelles_matieres_par_code[code]
                # Priorité 2 : nom exact
                if ancienne_matiere.nom:
                    nom = ancienne_matiere.nom.upper().strip()
                    if nom in nouvelles_matieres_par_nom:
                        return nouvelles_matieres_par_nom[nom]
                return None

            if not nouvelles_matieres_par_code and not nouvelles_matieres_par_nom:
                _logger.warning(
                    f"Transfert notes élève {self.id}: ClasseNote '{nouvelle_classe_note.nom}' "
                    f"n'a aucune matière active. Notes non transférées."
                )
                return {'transferees': 0, 'ignorees': 0, 'matieres_manquantes': True}

            notes_ignorees = 0

            # ── 1. Transférer les NoteMensuelle ──────────────────────────────
            notes_mensuelles = NoteMensuelle.objects.filter(eleve=self).select_related('matiere')
            for note in notes_mensuelles:
                nouvelle_matiere = trouver_matiere_equivalente(note.matiere)
                if nouvelle_matiere:
                    existe = NoteMensuelle.objects.filter(
                        eleve=self,
                        matiere=nouvelle_matiere,
                        mois=note.mois,
                        annee_scolaire=note.annee_scolaire
                    ).exclude(id=note.id).exists()
                    if not existe:
                        note.matiere = nouvelle_matiere
                        note.save(update_fields=['matiere'])
                        notes_transferees += 1
                    else:
                        notes_ignorees += 1
                else:
                    notes_ignorees += 1

            # ── 2. Transférer les CompositionNote ────────────────────────────
            compositions = CompositionNote.objects.filter(eleve=self).select_related('matiere')
            for comp in compositions:
                nouvelle_matiere = trouver_matiere_equivalente(comp.matiere)
                if nouvelle_matiere:
                    existe = CompositionNote.objects.filter(
                        eleve=self,
                        matiere=nouvelle_matiere,
                        periode=comp.periode,
                        annee_scolaire=comp.annee_scolaire
                    ).exclude(id=comp.id).exists()
                    if not existe:
                        comp.matiere = nouvelle_matiere
                        comp.save(update_fields=['matiere'])
                        notes_transferees += 1
                    else:
                        notes_ignorees += 1
                else:
                    notes_ignorees += 1

            # ── 3. Transférer les AppreciationMaternelle ─────────────────────
            appreciations = AppreciationMaternelle.objects.filter(eleve=self).select_related('matiere')
            for appr in appreciations:
                nouvelle_matiere = trouver_matiere_equivalente(appr.matiere)
                if nouvelle_matiere:
                    existe = AppreciationMaternelle.objects.filter(
                        eleve=self,
                        matiere=nouvelle_matiere,
                        trimestre=appr.trimestre,
                        annee_scolaire=appr.annee_scolaire
                    ).exclude(id=appr.id).exists()
                    if not existe:
                        appr.matiere = nouvelle_matiere
                        appr.save(update_fields=['matiere'])
                        notes_transferees += 1
                    else:
                        notes_ignorees += 1
                else:
                    notes_ignorees += 1

            # ── 4. Transférer les NoteEleve (via Evaluation) ─────────────────
            notes_eleve = NoteEleve.objects.filter(eleve=self).select_related('evaluation__matiere')
            for note_eleve in notes_eleve:
                if note_eleve.evaluation and note_eleve.evaluation.matiere:
                    nouvelle_matiere = trouver_matiere_equivalente(note_eleve.evaluation.matiere)
                    if nouvelle_matiere:
                        eval_equivalente = Evaluation.objects.filter(
                            matiere=nouvelle_matiere,
                            type_evaluation=note_eleve.evaluation.type_evaluation,
                            periode=note_eleve.evaluation.periode
                        ).first()
                        if eval_equivalente:
                            existe = NoteEleve.objects.filter(
                                eleve=self,
                                evaluation=eval_equivalente
                            ).exclude(id=note_eleve.id).exists()
                            if not existe:
                                note_eleve.evaluation = eval_equivalente
                                note_eleve.save(update_fields=['evaluation'])
                                notes_transferees += 1
                            else:
                                notes_ignorees += 1
                        else:
                            notes_ignorees += 1
                    else:
                        notes_ignorees += 1

            # ── 5. Transférer les EvaluationMaternelle + NoteMaternelle ──────
            evals_maternelle = EvaluationMaternelle.objects.filter(
                eleve=self
            ).prefetch_related('notes_matieres')
            for eval_mat in evals_maternelle:
                # Mettre à jour la classe de l'évaluation
                eval_mat.classe = nouvelle_classe_note
                eval_mat.save(update_fields=['classe'])
                notes_transferees += 1
                # Transférer les NoteMaternelle liées vers les nouvelles matières
                for note_mat in eval_mat.notes_matieres.all():
                    nouvelle_matiere = trouver_matiere_equivalente(note_mat.matiere)
                    if nouvelle_matiere:
                        note_mat.matiere = nouvelle_matiere
                        note_mat.save(update_fields=['matiere'])
                        notes_transferees += 1
                    else:
                        notes_ignorees += 1

            # ── 6. Transférer les BulletinMaternelle ─────────────────────────
            bulletins_mat = BulletinMaternelle.objects.filter(eleve=self)
            for bulletin in bulletins_mat:
                bulletin.classe = nouvelle_classe_note
                bulletin.save(update_fields=['classe'])
                notes_transferees += 1

            # ── 7. Supprimer les anciens classements (seront recalculés) ─────
            Classement.objects.filter(eleve=self).delete()

            # ── 8. Invalider le cache des rangs pour les deux classes ────────
            try:
                if ancienne_classe:
                    ancienne_classe_note = ClasseNote.objects.filter(
                        ecole=ancienne_classe.ecole,
                        nom__iexact=ancienne_classe.nom,
                        actif=True
                    ).first()
                    if ancienne_classe_note:
                        for pattern in [
                            f'rangs_classe_{ancienne_classe_note.id}_*',
                            f'classement_*_{ancienne_classe_note.id}_*',
                        ]:
                            try:
                                cache.delete_pattern(pattern)
                            except Exception:
                                pass

                for pattern in [
                    f'rangs_classe_{nouvelle_classe_note.id}_*',
                    f'classement_*_{nouvelle_classe_note.id}_*',
                ]:
                    try:
                        cache.delete_pattern(pattern)
                    except Exception:
                        pass
            except Exception:
                pass  # Le cache n'est pas critique

            # ── Log d'avertissement si des notes n'ont pas pu être transférées
            if notes_ignorees > 0:
                _logger.warning(
                    f"Transfert notes élève {self.id} ({self.prenom} {self.nom}): "
                    f"{notes_transferees} transférée(s), {notes_ignorees} ignorée(s) "
                    f"(matière ou évaluation équivalente non trouvée dans "
                    f"'{nouvelle_classe_note.nom}')."
                )

        except Exception as e:
            _logger.error(
                f"Erreur lors du transfert des notes pour l'élève {self.id}: {e}",
                exc_info=True
            )

        return {'transferees': notes_transferees, 'ignorees': notes_ignorees}

class HistoriqueEleve(SyncTrackedModel):
    """Modèle pour l'historique des modifications d'un élève"""
    ACTION_CHOICES = [
        ('CREATION', 'Création'),
        ('MODIFICATION', 'Modification'),
        ('CHANGEMENT_CLASSE', 'Changement de classe'),
        ('CHANGEMENT_STATUT', 'Changement de statut'),
        ('SUSPENSION', 'Suspension'),
        ('EXCLUSION', 'Exclusion'),
        ('TRANSFERT', 'Transfert'),
        ('DIPLOME', 'Diplômé / Archivé'),
        ('FIN_CYCLE', 'Fin de cycle'),
    ]
    
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, related_name='historique')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, verbose_name="Action")
    description = models.TextField(verbose_name="Description")
    date_action = models.DateTimeField(auto_now_add=True, verbose_name="Date de l'action")
    utilisateur = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name = "Historique élève"
        verbose_name_plural = "Historiques élèves"
        ordering = ['-date_action']
    
    def __str__(self):
        return f"{self.eleve.nom_complet} - {self.get_action_display()} ({self.date_action.strftime('%d/%m/%Y')})"
