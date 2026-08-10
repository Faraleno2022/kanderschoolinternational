"""
Module d'importation d'élèves depuis Excel/CSV
Permet l'importation massive d'élèves avec génération automatique de matricules
"""
import pandas as pd
from datetime import datetime
from django.db import transaction
from django.core.exceptions import ValidationError
from eleves.models import Eleve, Classe, Responsable


class ImportElevesError(Exception):
    """Exception personnalisée pour l'importation d'élèves"""
    pass


def generer_matricule(classe, numero_ordre, annee_scolaire=None, matricules_existants=None):
    """
    Génère un matricule unique pour un élève - VERSION OPTIMISÉE
    Format: [CODE_CLASSE][ANNEE][NUMERO]
    Exemple: 6A-2024-001
    
    Args:
        matricules_existants: Set des matricules déjà utilisés (pour éviter requêtes SQL)
    """
    if not annee_scolaire:
        annee_scolaire = datetime.now().year
    
    # Extraire l'année du format "2024-2025"
    if isinstance(annee_scolaire, str) and '-' in annee_scolaire:
        annee_scolaire = annee_scolaire.split('-')[0]
    
    # Obtenir le code de la classe ou utiliser le nom simplifié
    code_classe = getattr(classe, 'code_matricule', None) or classe.nom.replace(' ', '').upper()[:3]
    
    # Format du matricule
    matricule = f"{code_classe}-{annee_scolaire}-{numero_ordre:03d}"
    
    # ⚡ OPTIMISATION: Vérifier l'unicité en mémoire (pas de requête SQL)
    if matricules_existants is None:
        # Fallback si pas de set fourni (pas optimal)
        while Eleve.objects.filter(matricule=matricule).exists():
            numero_ordre += 1
            matricule = f"{code_classe}-{annee_scolaire}-{numero_ordre:03d}"
    else:
        # Utiliser le set en mémoire (RAPIDE!)
        while matricule in matricules_existants:
            numero_ordre += 1
            matricule = f"{code_classe}-{annee_scolaire}-{numero_ordre:03d}"
        # Ajouter au set pour éviter réutilisation
        matricules_existants.add(matricule)
    
    return matricule


def lire_fichier_eleves(file_path_or_obj):
    """
    Lit un fichier Excel ou CSV contenant la liste des élèves
    """
    try:
        # Déterminer le type de fichier
        if hasattr(file_path_or_obj, 'name'):
            if file_path_or_obj.name.endswith('.csv'):
                df = pd.read_csv(file_path_or_obj)
            else:
                df = pd.read_excel(file_path_or_obj)
        else:
            # Si c'est un chemin
            if str(file_path_or_obj).endswith('.csv'):
                df = pd.read_csv(file_path_or_obj)
            else:
                df = pd.read_excel(file_path_or_obj)
        
        # Nettoyer les noms de colonnes
        df.columns = df.columns.str.strip()
        
        return df
    except Exception as e:
        raise ImportElevesError(f"Erreur lors de la lecture du fichier: {e}")


def generer_template_eleves(classe_id=None):
    """
    Génère un template Excel pour l'importation d'élèves
    """
    try:
        # Colonnes du template
        colonnes = [
            'Matricule',  # Optionnel - sera généré si vide
            'Prénom',  # Obligatoire
            'Nom',  # Obligatoire
            'Sexe',  # M ou F - Obligatoire
            'Date de Naissance',  # Optionnel - Format: JJ/MM/AAAA
            'Lieu de Naissance',  # Optionnel
            'Nom du Père/Tuteur',  # Optionnel
            'Prénom du Père/Tuteur',  # Optionnel
            'Téléphone Principal',  # Optionnel
            'Adresse',  # Optionnel
            'Nom de la Mère',  # Optionnel
            'Prénom de la Mère',  # Optionnel
            'Téléphone Secondaire',  # Optionnel
            'Email'  # Optionnel
        ]
        
        # Créer un DataFrame avec des exemples
        data = {col: [] for col in colonnes}
        
        # Ajouter quelques lignes d'exemple
        data['Matricule'] = ['', '', '']  # Laisser vide pour génération auto
        data['Prénom'] = ['Mamadou', 'Fatoumata', 'Ibrahim']
        data['Nom'] = ['DIALLO', 'BAH', 'CAMARA']
        data['Sexe'] = ['M', 'F', 'M']
        data['Date de Naissance'] = ['15/01/2010', '23/05/2010', '10/09/2010']
        data['Lieu de Naissance'] = ['Conakry', 'Kindia', 'Labé']
        data['Nom du Père/Tuteur'] = ['DIALLO', 'BAH', 'CAMARA']
        data['Prénom du Père/Tuteur'] = ['Amadou', 'Ousmane', 'Sékou']
        data['Téléphone Principal'] = ['622000001', '622000002', '622000003']
        data['Adresse'] = ['Ratoma', 'Matoto', 'Dixinn']
        data['Nom de la Mère'] = ['BARRY', 'SOW', 'SYLLA']
        data['Prénom de la Mère'] = ['Aissatou', 'Mariama', 'Binta']
        data['Téléphone Secondaire'] = ['', '', '']
        data['Email'] = ['', '', '']
        
        df = pd.DataFrame(data)
        
        return df
    
    except Exception as e:
        raise ImportElevesError(f"Erreur lors de la génération du template: {e}")


class ImportElevesValidator:
    """
    Validateur pour l'importation d'élèves
    """
    
    def __init__(self, df, classe_id):
        self.df = df
        self.classe_id = classe_id
        self.erreurs = []
        self.avertissements = []
        
    def valider(self):
        """
        Valide le fichier importé
        """
        # Vérifier les colonnes requises (seuls Prénom, Nom et Sexe sont obligatoires)
        colonnes_requises = ['Prénom', 'Nom', 'Sexe']
        
        colonnes_manquantes = []
        for col in colonnes_requises:
            if col not in self.df.columns:
                colonnes_manquantes.append(col)
        
        if colonnes_manquantes:
            raise ImportElevesError(
                f"Colonnes manquantes: {', '.join(colonnes_manquantes)}"
            )
        
        # Valider chaque ligne
        for index, row in self.df.iterrows():
            self._valider_ligne(index + 2, row)  # +2 car Excel commence à 1 + en-tête
        
        return len(self.erreurs) == 0
    
    def _valider_ligne(self, ligne_num, row):
        """
        Valide une ligne du fichier
        """
        # Vérifier les champs obligatoires (seuls Prénom, Nom et Sexe sont obligatoires)
        champs_obligatoires = ['Prénom', 'Nom', 'Sexe']
        
        for champ in champs_obligatoires:
            if pd.isna(row.get(champ)) or str(row.get(champ)).strip() == '':
                self.erreurs.append(
                    f"Ligne {ligne_num}: Le champ '{champ}' est obligatoire"
                )
        
        # Valider le sexe
        if row.get('Sexe') and str(row['Sexe']).upper() not in ['M', 'F']:
            self.erreurs.append(
                f"Ligne {ligne_num}: Le sexe doit être 'M' ou 'F' (trouvé: {row['Sexe']})"
            )
        
        # Valider la date de naissance (optionnel - valider uniquement si présent)
        date_val = row.get('Date de Naissance')
        if date_val and not pd.isna(date_val) and str(date_val).strip() != '':
            try:
                # Essayer différents formats
                date_str = str(date_val).strip()
                for fmt in ['%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y']:
                    try:
                        date_naissance = datetime.strptime(date_str, fmt)
                        break
                    except:
                        continue
                else:
                    raise ValueError("Format de date invalide")
                    
                # Vérifier que la date est raisonnable
                age = (datetime.now() - date_naissance).days // 365
                if age < 3 or age > 25:
                    self.avertissements.append(
                        f"Ligne {ligne_num}: Âge inhabituel ({age} ans)"
                    )
            except Exception as e:
                self.erreurs.append(
                    f"Ligne {ligne_num}: Date de naissance invalide (format attendu: JJ/MM/AAAA)"
                )
        
        # Valider le téléphone (optionnel - valider uniquement si présent)
        tel_val = row.get('Téléphone Principal')
        if tel_val and not pd.isna(tel_val) and str(tel_val).strip() != '':
            tel = str(tel_val).replace(' ', '').replace('-', '')
            if not tel.isdigit() or len(tel) < 8:
                self.erreurs.append(
                    f"Ligne {ligne_num}: Téléphone invalide (doit contenir au moins 8 chiffres)"
                )
        
        # Vérifier les doublons potentiels
        if row.get('Prénom') and row.get('Nom'):
            prenom = str(row['Prénom']).strip()
            nom = str(row['Nom']).strip()
            
            # Vérifier dans la base de données
            if Eleve.objects.filter(
                prenom__iexact=prenom,
                nom__iexact=nom,
                classe_id=self.classe_id
            ).exists():
                self.avertissements.append(
                    f"Ligne {ligne_num}: Un élève '{prenom} {nom}' existe déjà dans cette classe"
                )


class ImportElevesProcessor:
    """
    Processeur pour importer les élèves
    """
    
    def __init__(self, df, classe_id, user=None, generer_matricules=True):
        self.df = df
        self.classe_id = classe_id
        self.user = user
        self.generer_matricules = generer_matricules
        self.stats = {
            'total': 0,
            'crees': 0,
            'modifies': 0,
            'erreurs': 0,
            'matricules_generes': 0
        }
        self.eleves_importes = []
        
    def importer(self):
        """
        Importe les élèves depuis le DataFrame - VERSION OPTIMISÉE
        """
        try:
            # Récupérer la classe
            classe = Classe.objects.get(id=self.classe_id)
        except Classe.DoesNotExist:
            raise ImportElevesError("Classe introuvable")
        
        # ⚡ OPTIMISATION: Charger tous les matricules existants (1 seule requête)
        matricules_existants = set(Eleve.objects.values_list('matricule', flat=True))
        
        # ⚡ OPTIMISATION: Charger tous les responsables existants (1 seule requête)
        responsables_dict = {r.telephone: r for r in Responsable.objects.all()}
        
        # ⚡ OPTIMISATION: Charger les élèves de la classe (détection doublons)
        eleves_existants = {}
        for eleve in Eleve.objects.filter(classe=classe).select_related('responsable_principal', 'responsable_secondaire'):
            key = f"{eleve.prenom}_{eleve.nom}".lower()
            eleves_existants[key] = eleve
        
        # Obtenir le prochain numéro d'ordre pour les matricules
        derniere_matricule = Eleve.objects.filter(
            classe=classe
        ).order_by('-matricule').first()
        
        if derniere_matricule and '-' in derniere_matricule.matricule:
            try:
                numero_ordre = int(derniere_matricule.matricule.split('-')[-1]) + 1
            except:
                numero_ordre = 1
        else:
            numero_ordre = 1
        
        # Listes pour bulk operations
        eleves_a_creer = []
        eleves_a_modifier = []
        responsables_a_creer = []
        
        with transaction.atomic():
            for index, row in self.df.iterrows():
                try:
                    self.stats['total'] += 1
                    resultat = self._preparer_eleve(
                        row, classe, numero_ordre, 
                        matricules_existants, responsables_dict, eleves_existants
                    )
                    
                    if resultat:
                        if resultat['type'] == 'creer':
                            eleves_a_creer.append(resultat['eleve'])
                        elif resultat['type'] == 'modifier':
                            eleves_a_modifier.append(resultat['eleve'])
                        responsables_a_creer.extend(resultat.get('responsables') or [])

                    numero_ordre += 1
                    
                except Exception as e:
                    self.stats['erreurs'] += 1
                    print(f"Erreur ligne {index + 2}: {e}")
            
            # ⚡ BULK CREATE responsables d'abord
            if responsables_a_creer:
                Responsable.objects.bulk_create(responsables_a_creer, ignore_conflicts=True)
                # Recharger pour avoir les IDs
                responsables_dict = {r.telephone: r for r in Responsable.objects.all()}
            
            # Assigner les responsables aux élèves. Les responsables gardés en
            # cache pendant la boucle ne sont pas encore enregistrés : on les
            # relit tous ici, sinon bulk_create/bulk_update refuse l'objet lié.
            for eleve_data in eleves_a_creer + eleves_a_modifier:
                tel_principal = getattr(eleve_data, '_responsable_tel', None)
                if tel_principal:
                    eleve_data.responsable_principal = responsables_dict.get(tel_principal)
                tel_secondaire = getattr(eleve_data, '_responsable2_tel', None)
                if tel_secondaire:
                    eleve_data.responsable_secondaire = responsables_dict.get(tel_secondaire)

            # ⚡ BULK CREATE élèves
            if eleves_a_creer:
                Eleve.objects.bulk_create(eleves_a_creer, batch_size=500)
                self.stats['crees'] += len(eleves_a_creer)
            
            # ⚡ BULK UPDATE élèves
            if eleves_a_modifier:
                Eleve.objects.bulk_update(
                    eleves_a_modifier,
                    ['prenom', 'nom', 'sexe', 'date_naissance', 'lieu_naissance', 
                     'responsable_principal', 'responsable_secondaire', 'statut'],
                    batch_size=500
                )
                self.stats['modifies'] += len(eleves_a_modifier)
        
        return self.stats
    
    def _preparer_eleve(self, row, classe, numero_ordre, matricules_existants, responsables_dict, eleves_existants):
        """
        Prépare un élève pour bulk creation/update - VERSION OPTIMISÉE
        """
        # Préparer les données de l'élève
        matricule = row.get('Matricule')
        
        # Générer le matricule si nécessaire
        if not matricule or pd.isna(matricule) or str(matricule).strip() == '':
            if self.generer_matricules:
                matricule = generer_matricule(classe, numero_ordre, classe.annee_scolaire, matricules_existants)
                self.stats['matricules_generes'] += 1
            else:
                raise ImportElevesError("Matricule manquant et génération désactivée")
        else:
            matricule = str(matricule).strip()
        
        # Gérer le responsable principal (optionnel)
        responsable = None
        nouveau_resp = None
        if (row.get('Téléphone Principal') and not pd.isna(row.get('Téléphone Principal')) and 
            str(row.get('Téléphone Principal')).strip() != ''):
            responsable, nouveau_resp = self._preparer_responsable(row, responsables_dict)
        
        # Gérer le responsable secondaire (mère) - optionnel
        responsable_secondaire = None
        nouveau_resp2 = None
        if row.get('Nom de la Mère') and not pd.isna(row.get('Nom de la Mère')):
            responsable_secondaire, nouveau_resp2 = self._preparer_responsable_secondaire(row, responsables_dict)
        
        # Formater la date de naissance (optionnel)
        date_naissance = self._formater_date(row.get('Date de Naissance'))
        
        # Vérifier si l'élève existe déjà
        key = f"{str(row['Prénom']).strip()}_{str(row['Nom']).strip()}".lower()
        eleve_existant = eleves_existants.get(key)
        
        # Gérer lieu de naissance (optionnel)
        lieu_naissance = None
        if row.get('Lieu de Naissance') and not pd.isna(row.get('Lieu de Naissance')):
            lieu_naissance = str(row['Lieu de Naissance']).strip()
        
        # Les responsables trouvés en cache peuvent encore être non enregistrés :
        # on ne mémorise que leur téléphone, la liaison est faite après le
        # bulk_create des responsables.
        tel_principal = getattr(responsable or nouveau_resp, 'telephone', None)
        tel_secondaire = getattr(responsable_secondaire or nouveau_resp2, 'telephone', None)

        nouveaux_resp = []
        if nouveau_resp:
            nouveaux_resp.append(nouveau_resp)
        if nouveau_resp2:
            nouveaux_resp.append(nouveau_resp2)

        if eleve_existant:
            # Modifier
            eleve_existant.prenom = str(row['Prénom']).strip()
            eleve_existant.nom = str(row['Nom']).strip().upper()
            eleve_existant.sexe = str(row['Sexe']).upper()
            eleve_existant.date_naissance = date_naissance
            eleve_existant.lieu_naissance = lieu_naissance
            eleve_existant.responsable_principal = None
            eleve_existant.responsable_secondaire = None
            eleve_existant._responsable_tel = tel_principal
            eleve_existant._responsable2_tel = tel_secondaire
            eleve_existant.statut = 'ACTIF'

            return {
                'type': 'modifier',
                'eleve': eleve_existant,
                'responsables': nouveaux_resp,
            }
        else:
            # Créer
            eleve = Eleve(
                matricule=matricule,
                prenom=str(row['Prénom']).strip(),
                nom=str(row['Nom']).strip().upper(),
                sexe=str(row['Sexe']).upper(),
                date_naissance=date_naissance,
                lieu_naissance=lieu_naissance,
                classe=classe,
                date_inscription=datetime.now().date(),
                statut='ACTIF'
            )
            eleve._responsable_tel = tel_principal
            eleve._responsable2_tel = tel_secondaire

            return {
                'type': 'creer',
                'eleve': eleve,
                'responsables': nouveaux_resp,
            }
    
    def _preparer_responsable(self, row, responsables_dict):
        """
        Prépare un responsable principal (père/tuteur) - VERSION OPTIMISÉE
        Retourne (responsable_existant, nouveau_responsable)
        """
        telephone = str(row['Téléphone Principal']).replace(' ', '').replace('-', '')
        
        # Vérifier en mémoire
        if telephone in responsables_dict:
            return (responsables_dict[telephone], None)
        
        # Créer un nouveau responsable (sera bulk_create plus tard)
        nouveau_resp = Responsable(
            telephone=telephone,
            nom=str(row['Nom du Père/Tuteur']).strip().upper(),
            prenom=str(row['Prénom du Père/Tuteur']).strip(),
            adresse=str(row['Adresse']).strip(),
            email=row.get('Email') if not pd.isna(row.get('Email')) else None
        )
        
        # Ajouter au dict pour éviter duplicatas dans le même batch
        responsables_dict[telephone] = nouveau_resp
        
        return (None, nouveau_resp)
    
    def _preparer_responsable_secondaire(self, row, responsables_dict):
        """
        Prépare un responsable secondaire (mère) - VERSION OPTIMISÉE
        Retourne (responsable_existant, nouveau_responsable)
        """
        telephone = row.get('Téléphone Secondaire')
        
        if pd.isna(telephone) or str(telephone).strip() == '':
            telephone = str(row['Téléphone Principal']).replace(' ', '').replace('-', '') + '_2'
        else:
            telephone = str(telephone).replace(' ', '').replace('-', '')
        
        # Vérifier en mémoire
        if telephone in responsables_dict:
            return (responsables_dict[telephone], None)
        
        # Créer un nouveau responsable (sera bulk_create plus tard)
        nouveau_resp = Responsable(
            telephone=telephone,
            nom=str(row['Nom de la Mère']).strip().upper(),
            prenom=str(row['Prénom de la Mère']).strip(),
            adresse=str(row['Adresse']).strip()
        )
        
        # Ajouter au dict pour éviter duplicatas dans le même batch
        responsables_dict[telephone] = nouveau_resp
        
        return (None, nouveau_resp)
    
    def _formater_date(self, date_str):
        """
        Formate une date depuis différents formats possibles
        """
        if pd.isna(date_str):
            return None
        
        date_str = str(date_str)
        
        # Essayer différents formats
        for fmt in ['%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d.%m.%Y']:
            try:
                return datetime.strptime(date_str, fmt).date()
            except:
                continue
        
        # Si aucun format ne marche, lever une exception
        raise ImportElevesError(f"Format de date invalide: {date_str}")


COLONNES_MODELE_IMPORT = [
    'Matricule', 'Prénom', 'Nom', 'Sexe', 'Date de Naissance',
    'Lieu de Naissance', 'Nom du Père/Tuteur', 'Prénom du Père/Tuteur',
    'Téléphone Principal', 'Adresse', 'Nom de la Mère',
    'Prénom de la Mère', 'Téléphone Secondaire', 'Email',
]

COLONNES_CONTEXTE_EXPORT = ['École', 'Classe', 'Année scolaire']


def exporter_liste_eleves_queryset(eleves, inclure_classe=False):
    """Construit un export compatible avec les colonnes du template d'import."""
    data = []
    for eleve in eleves:
        responsable = eleve.responsable_principal
        responsable_2 = eleve.responsable_secondaire

        ligne = {}
        if inclure_classe:
            ligne.update({
                'École': eleve.classe.ecole.nom,
                'Classe': eleve.classe.nom,
                'Année scolaire': eleve.classe.annee_scolaire,
            })
        ligne.update({
            'Matricule': eleve.matricule,
            'Prénom': eleve.prenom,
            'Nom': eleve.nom,
            'Sexe': eleve.sexe,
            'Date de Naissance': eleve.date_naissance.strftime('%d/%m/%Y') if eleve.date_naissance else '',
            'Lieu de Naissance': eleve.lieu_naissance,
            'Nom du Père/Tuteur': responsable.nom if responsable else '',
            'Prénom du Père/Tuteur': responsable.prenom if responsable else '',
            'Téléphone Principal': responsable.telephone if responsable else '',
            'Adresse': responsable.adresse if responsable else '',
            'Nom de la Mère': responsable_2.nom if responsable_2 else '',
            'Prénom de la Mère': responsable_2.prenom if responsable_2 else '',
            'Téléphone Secondaire': responsable_2.telephone if responsable_2 else '',
            'Email': responsable.email if responsable else '',
        })
        data.append(ligne)
    colonnes = (
        COLONNES_CONTEXTE_EXPORT + COLONNES_MODELE_IMPORT
        if inclure_classe else COLONNES_MODELE_IMPORT
    )
    # Fournir les en-têtes exacts même lorsque la liste est vide.
    return pd.DataFrame(data, columns=colonnes)


def exporter_liste_eleves(classe_id):
    """
    Exporte la liste des élèves d'une classe au format Excel
    """
    try:
        classe = Classe.objects.get(id=classe_id)
        eleves = Eleve.objects.filter(
            classe=classe, statut='ACTIF', est_dans_corbeille=False,
        ).select_related(
            'classe', 'classe__ecole', 'responsable_principal', 'responsable_secondaire',
        ).order_by('nom', 'prenom')
        return exporter_liste_eleves_queryset(eleves)

    except Exception as e:
        raise ImportElevesError(f"Erreur lors de l'export: {e}")
