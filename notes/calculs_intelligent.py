"""
Système de calcul intelligent des notes avec mentions et appréciations dynamiques
Version améliorée du 11 novembre 2024
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Optional


def calculer_moyenne_devoirs(notes: List[Decimal]) -> Optional[Decimal]:
    """
    Calcule la moyenne des devoirs (exclut les absents/None)
    
    Args:
        notes: Liste des notes des devoirs
        
    Returns:
        Moyenne arrondie à 2 décimales ou None si aucune note
    """
    notes_valides = [n for n in notes if n is not None]
    
    if not notes_valides:
        return None
    
    moyenne = sum(notes_valides) / len(notes_valides)
    return moyenne.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calculer_moyenne_periode(moyenne_cours: Optional[Decimal], 
                             composition: Optional[Decimal],
                             niveau: str = 'SECONDAIRE') -> Optional[Decimal]:
    """
    Calcule la moyenne d'une période (trimestre/semestre)
    
    SYSTÈME GUINÉEN:
    - PRIMAIRE: Composition uniquement (pas de notes mensuelles)
    - SECONDAIRE: (Moyenne Cours × 40%) + (Composition × 60%)
    
    Args:
        moyenne_cours: Moyenne des devoirs/cours mensuels
        composition: Note de composition
        niveau: 'PRIMAIRE' ou 'SECONDAIRE'
        
    Returns:
        Moyenne de la période ou None
    """
    # Primaire : composition uniquement
    if niveau == 'PRIMAIRE':
        return composition
    
    # Secondaire : formule 40/60
    # Si les deux sont None, pas de moyenne
    if moyenne_cours is None and composition is None:
        return None
    
    # Si on n'a que la composition
    if moyenne_cours is None:
        return composition
    
    # Si on n'a que les cours
    if composition is None:
        return moyenne_cours
    
    # Formule 40/60
    moyenne_ponderee = (moyenne_cours * Decimal('0.4')) + (composition * Decimal('0.6'))
    return moyenne_ponderee.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calculer_moyenne_annuelle(moyennes_periodes: List[Optional[Decimal]]) -> Optional[Decimal]:
    """
    Calcule la moyenne annuelle
    
    Args:
        moyennes_periodes: Liste des moyennes par période
        
    Returns:
        Moyenne annuelle ou None
    """
    if not moyennes_periodes or all(m is None for m in moyennes_periodes):
        return None

    # Une période attendue mais non évaluée compte comme zéro, conformément
    # au calcul centralisé des bulletins annuels dans calculs_moyennes.py.
    moyennes_avec_absents = [
        moyenne if moyenne is not None else Decimal('0')
        for moyenne in moyennes_periodes
    ]
    moyenne_annuelle = sum(moyennes_avec_absents) / len(moyennes_avec_absents)
    return moyenne_annuelle.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calculer_moyenne_generale(notes_matieres: Dict[str, Dict], 
                              niveau: str = 'SECONDAIRE') -> Optional[Decimal]:
    """
    Calcule la moyenne générale de toutes les matières
    
    Args:
        notes_matieres: {
            'matiere1': {'moyenne': Decimal('15'), 'coefficient': Decimal('3')},
            'matiere2': {'moyenne': Decimal('12'), 'coefficient': Decimal('2')},
            ...
        }
        niveau: 'PRIMAIRE' ou 'SECONDAIRE'
        
    Returns:
        Moyenne générale ou None
    """
    moyennes_valides = []
    total_points = Decimal('0')
    total_coefficients = Decimal('0')
    
    for matiere_data in notes_matieres.values():
        moyenne = matiere_data.get('moyenne')
        
        if moyenne is not None:
            moyennes_valides.append(moyenne)
            
            if niveau == 'SECONDAIRE':
                coefficient = matiere_data.get('coefficient', Decimal('1'))
                total_points += moyenne * coefficient
                total_coefficients += coefficient
    
    if not moyennes_valides:
        return None
    
    # Primaire : moyenne simple
    if niveau == 'PRIMAIRE':
        moyenne_generale = sum(moyennes_valides) / len(moyennes_valides)
        return moyenne_generale.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    
    # Secondaire : moyenne pondérée
    if total_coefficients == 0:
        return None
    
    moyenne_generale = total_points / total_coefficients
    return moyenne_generale.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def obtenir_mention_intelligente(moyenne: Optional[Decimal], niveau: str = 'SECONDAIRE') -> str:
    """
    Détermine la mention selon la moyenne avec les seuils adaptés au niveau scolaire
    
    SYSTÈME INTELLIGENT PAR NIVEAU:
    
    MATERNELLE (Acquisition en %):
    - >= 90%: Excellent
    - >= 75%: Très Bien
    - >= 60%: Bien
    - >= 50%: Assez Bien
    - < 50%: À encourager
    
    PRIMAIRE (Moyenne /10):
    - >= 9: Excellent
    - >= 8: Très Bien
    - >= 7: Bien
    - >= 6: Assez Bien
    - >= 5: Passable
    - >= 4: Insuffisant
    - >= 3: Faible
    - < 3: Très faible
    
    SECONDAIRE (Moyenne /20):
    - >= 18: Excellent
    - >= 16: Très Bien
    - >= 14: Bien
    - >= 12: Assez Bien
    - >= 10: Passable
    - >= 8: Insuffisant
    - >= 6: Faible
    - < 6: Très faible
    
    Args:
        moyenne: Moyenne de l'élève (ou taux d'acquisition pour maternelle)
        niveau: Niveau scolaire ('MATERNELLE', 'PRIMAIRE', 'SECONDAIRE')
        
    Returns:
        Mention appropriée
    """
    if moyenne is None:
        return "Non évalué"
    
    # Convertir en Decimal si nécessaire
    if not isinstance(moyenne, Decimal):
        moyenne = Decimal(str(moyenne))
    
    if niveau == 'MATERNELLE':
        # Maternelle : taux d'acquisition en %
        if moyenne >= Decimal('90'):
            return "Excellent"
        elif moyenne >= Decimal('75'):
            return "Très Bien"
        elif moyenne >= Decimal('60'):
            return "Bien"
        elif moyenne >= Decimal('50'):
            return "Assez Bien"
        else:
            return "À encourager"
    
    elif niveau == 'PRIMAIRE':
        # Primaire : moyenne sur 10
        if moyenne >= Decimal('9'):
            return "Excellent"
        elif moyenne >= Decimal('8'):
            return "Très Bien"
        elif moyenne >= Decimal('7'):
            return "Bien"
        elif moyenne >= Decimal('6'):
            return "Assez Bien"
        elif moyenne >= Decimal('5'):
            return "Passable"
        elif moyenne >= Decimal('4'):
            return "Insuffisant"
        elif moyenne >= Decimal('3'):
            return "Faible"
        else:
            return "Très faible"
    
    else:
        # Secondaire : moyenne sur 20 (par défaut)
        if moyenne >= Decimal('18'):
            return "Excellent"
        elif moyenne >= Decimal('16'):
            return "Très Bien"
        elif moyenne >= Decimal('14'):
            return "Bien"
        elif moyenne >= Decimal('12'):
            return "Assez Bien"
        elif moyenne >= Decimal('10'):
            return "Passable"
        elif moyenne >= Decimal('8'):
            return "Insuffisant"
        elif moyenne >= Decimal('6'):
            return "Faible"
        else:
            return "Très faible"


def obtenir_appreciation_intelligente(moyenne: Optional[Decimal], prenom: str = None, niveau: str = 'SECONDAIRE') -> str:
    """
    Génère une appréciation dynamique et personnalisée selon la moyenne
    
    Args:
        moyenne: Moyenne de l'élève
        prenom: Prénom de l'élève pour personnaliser
        niveau: 'PRIMAIRE' (sur 10), 'SECONDAIRE' (sur 20), ou 'MATERNELLE'
        
    Returns:
        Appréciation du conseil de classe
    """
    if moyenne is None:
        return "L'élève n'a pas été évalué sur cette période."
    
    # Personnalisation avec le prénom si disponible
    nom = prenom if prenom else "L'élève"
    
    # Pour le primaire (notation sur 10), convertir en équivalent sur 20
    if niveau == 'PRIMAIRE':
        moyenne_ref = moyenne * 2  # Convertir sur 20 pour comparer
    else:
        moyenne_ref = moyenne
    
    if moyenne_ref >= Decimal('18.5'):
        return f"Excellent travail ! {nom} est brillant(e) et exemplaire. Le conseil félicite chaleureusement."
    elif moyenne_ref >= Decimal('17'):
        return f"Travail remarquable ! {nom} fait preuve d'excellence. Félicitations du conseil."
    elif moyenne_ref >= Decimal('16.5'):
        return f"Très bon travail. {nom} est un(e) élève sérieux(se) et appliqué(e). Félicitations."
    elif moyenne_ref >= Decimal('15'):
        return f"Bon travail. {nom} obtient de bons résultats. Continuez ainsi."
    elif moyenne_ref >= Decimal('14.5'):
        return f"Travail satisfaisant. {nom} a de bonnes capacités. Persévérez."
    elif moyenne_ref >= Decimal('13'):
        return f"Résultats corrects. {nom} peut progresser avec plus de régularité."
    elif moyenne_ref >= Decimal('12.5'):
        return f"Résultats moyens mais encourageants. {nom} doit intensifier ses efforts."
    elif moyenne_ref >= Decimal('11'):
        return f"Résultats fragiles. {nom} doit travailler davantage pour progresser."
    elif moyenne_ref >= Decimal('10'):
        return f"Résultats justes passables. {nom} doit redoubler d'efforts dans toutes les matières."
    elif moyenne_ref >= Decimal('9'):
        return f"Résultats faibles et préoccupants. Un travail soutenu est indispensable."
    elif moyenne_ref >= Decimal('7'):
        return f"Résultats insuffisants. {nom} doit impérativement se ressaisir."
    else:
        return f"Résultats très insuffisants. Une remise en question complète est nécessaire."


def formater_rang_intelligent(rang: int, sexe: str = 'M', total_eleves: int = None, est_ex_aequo: bool = False) -> str:
    """
    Formate le rang avec accord grammatical intelligent
    
    Args:
        rang: Position dans le classement
        sexe: 'M' pour masculin, 'F' pour féminin
        total_eleves: Nombre total d'élèves (optionnel)
        est_ex_aequo: True si l'élève est ex-æquo avec d'autres
        
    Returns:
        Rang formaté avec accord grammatical (ex: "1er/25", "1ère/25", "2ème ex-æquo/25")
    """
    if rang is None or rang == 0:
        return "-"
    
    # Formater le rang avec accord grammatical
    if rang == 1:
        rang_str = "1ère" if sexe == 'F' else "1er"
    else:
        rang_str = f"{rang}ème"
    
    # Ajouter "ex" si c'est le cas
    if est_ex_aequo and rang > 1:
        rang_str += " ex"
    
    # Ne pas ajouter le total pour un affichage plus compact
    return rang_str


def calculer_rang_intelligent(moyennes_eleves: List[Dict]) -> List[Dict]:
    """
    Calcule le rang de chaque élève avec gestion des ex-aequo
    
    Args:
        moyennes_eleves: [
            {'eleve_id': 1, 'moyenne': Decimal('15.5'), 'sexe': 'F', 'prenom': 'Fatou'},
            {'eleve_id': 2, 'moyenne': Decimal('14.2'), 'sexe': 'M', 'prenom': 'Mamadou'},
            ...
        ]
        
    Returns:
        Liste avec rangs formatés intelligemment, triée par moyenne décroissante
    """
    # Filtrer les élèves avec moyenne
    eleves_avec_moyenne = [e for e in moyennes_eleves if e.get('moyenne') is not None]
    eleves_sans_moyenne = [e for e in moyennes_eleves if e.get('moyenne') is None]
    
    # Trier par moyenne décroissante
    eleves_tries = sorted(
        eleves_avec_moyenne,
        key=lambda x: x['moyenne'],
        reverse=True
    )
    
    # Attribuer les rangs avec gestion des ex-aequo
    rang_actuel = 1
    total_eleves = len(eleves_avec_moyenne)
    
    # Compter les occurrences de chaque moyenne pour détecter les ex-æquo
    from collections import Counter
    moyennes_occurrences = Counter([e['moyenne'] for e in eleves_tries])
    
    for i, eleve in enumerate(eleves_tries):
        # Gérer les ex-aequo
        if i > 0 and abs(eleve['moyenne'] - eleves_tries[i-1]['moyenne']) < Decimal('0.01'):
            eleve['rang_num'] = eleves_tries[i-1]['rang_num']
        else:
            eleve['rang_num'] = rang_actuel
        
        rang_actuel += 1
        
        # Détecter si c'est un ex-æquo
        moyenne_actuelle = eleve['moyenne']
        est_ex_aequo = moyennes_occurrences[moyenne_actuelle] > 1
        
        # Formater le rang avec accord grammatical
        sexe = eleve.get('sexe', 'M')
        eleve['rang'] = formater_rang_intelligent(eleve['rang_num'], sexe, total_eleves, est_ex_aequo)
        # Stocker aussi le total pour les vues qui en ont besoin
        eleve['total_eleves'] = total_eleves
        
        # Ajouter mention et appréciation intelligentes
        eleve['mention'] = obtenir_mention_intelligente(eleve['moyenne'])
        eleve['appreciation'] = obtenir_appreciation_intelligente(
            eleve['moyenne'], 
            eleve.get('prenom')
        )
    
    # Gérer les élèves sans moyenne
    for eleve in eleves_sans_moyenne:
        eleve['rang'] = "-"
        eleve['rang_num'] = None
        eleve['mention'] = "Non évalué"
        eleve['appreciation'] = "L'élève n'a pas été évalué sur cette période."
    
    return eleves_tries + eleves_sans_moyenne


def obtenir_encouragements(moyenne: Optional[Decimal]) -> str:
    """
    Détermine les encouragements selon la performance
    
    Args:
        moyenne: Moyenne de l'élève
        
    Returns:
        Type d'encouragement ou distinction
    """
    if moyenne is None:
        return ""
    
    if moyenne >= Decimal('18'):
        return "Tableau d'Excellence"
    elif moyenne >= Decimal('16'):
        return "Tableau d'Honneur"
    elif moyenne >= Decimal('14'):
        return "Félicitations"
    elif moyenne >= Decimal('12'):
        return "Encouragements"
    elif moyenne >= Decimal('10.5'):
        return "À encourager"
    else:
        return ""


def calculer_moyenne_cours_mensuels(notes_par_mois: Dict[str, List[Decimal]]) -> Optional[Decimal]:
    """
    Calcule la moyenne des cours mensuels sur une période
    
    Args:
        notes_par_mois: {
            'octobre': [Decimal('14'), Decimal('15')],
            'novembre': [Decimal('12'), Decimal('14')],
            ...
        }
        
    Returns:
        Moyenne de cours de la période ou None
    """
    moyennes_mensuelles = []
    
    for mois, notes in notes_par_mois.items():
        moyenne_mois = calculer_moyenne_devoirs(notes)
        if moyenne_mois is not None:
            moyennes_mensuelles.append(moyenne_mois)
    
    if not moyennes_mensuelles:
        return None
    
    moyenne_cours = sum(moyennes_mensuelles) / len(moyennes_mensuelles)
    return moyenne_cours.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def valider_note(note: any, note_sur: Decimal = Decimal('20')) -> tuple:
    """
    Valide une note
    
    Args:
        note: Note à valider
        note_sur: Note maximale (défaut 20)
        
    Returns:
        (est_valide: bool, message_erreur: str)
    """
    if note is None:
        return True, ""
    
    try:
        note_decimal = Decimal(str(note))
    except:
        return False, "Format de note invalide"
    
    if note_decimal < 0:
        return False, "La note ne peut pas être négative"
    
    if note_decimal > note_sur:
        return False, f"La note ne peut pas dépasser {note_sur}"
    
    return True, ""


# Fonctions de compatibilité (anciens noms conservés)
def obtenir_mention(moyenne: Decimal) -> str:
    """Fonction de compatibilité - utilise la version intelligente"""
    return obtenir_mention_intelligente(moyenne)


def obtenir_appreciation(moyenne: Decimal) -> str:
    """Fonction de compatibilité - utilise la version intelligente"""
    return obtenir_appreciation_intelligente(moyenne)


def calculer_rang(moyennes_eleves: List[Dict]) -> List[Dict]:
    """Fonction de compatibilité - utilise la version intelligente"""
    return calculer_rang_intelligent(moyennes_eleves)


# Tests du système intelligent
if __name__ == "__main__":
    from colorama import init, Fore, Style, Back
    init()
    
    print("\n" + "="*80)
    print(Fore.CYAN + " "*20 + "✨ SYSTÈME INTELLIGENT DE CALCUL ✨" + Style.RESET_ALL)
    print("="*80)
    
    print("\n" + Fore.YELLOW + "📊 TEST DES MENTIONS INTELLIGENTES" + Style.RESET_ALL)
    print("-"*80)
    
    # Test des mentions
    test_moyennes = [
        Decimal('19.2'), Decimal('18.5'), Decimal('17.8'), 
        Decimal('16.5'), Decimal('15.3'), Decimal('14.5'),
        Decimal('13.2'), Decimal('12.5'), Decimal('11.0'),
        Decimal('10.0'), Decimal('9.5'), Decimal('9.0'),
        Decimal('8.5'), Decimal('7.0')
    ]
    
    for moyenne in test_moyennes:
        mention = obtenir_mention_intelligente(moyenne)
        
        # Couleur selon la mention
        if "Excellent" in mention:
            couleur = Fore.GREEN + Style.BRIGHT
        elif "Très bien" in mention:
            couleur = Fore.GREEN
        elif "Bien" in mention:
            couleur = Fore.CYAN
        elif "Assez" in mention:
            couleur = Fore.YELLOW
        elif "Passable" in mention:
            couleur = Fore.MAGENTA
        elif "Faible" in mention:
            couleur = Fore.RED
        else:
            couleur = Fore.RED + Style.BRIGHT
        
        print(f"Moyenne: {moyenne:>5.2f}/20 → {couleur}{mention:15s}{Style.RESET_ALL}")
    
    print("\n" + Fore.YELLOW + "🎯 TEST DES RANGS INTELLIGENTS" + Style.RESET_ALL)
    print("-"*80)
    
    # Test des rangs avec accord grammatical
    eleves_test = [
        {'eleve_id': 1, 'prenom': 'Fatoumata', 'sexe': 'F', 'moyenne': Decimal('18.5')},
        {'eleve_id': 2, 'prenom': 'Mamadou', 'sexe': 'M', 'moyenne': Decimal('17.2')},
        {'eleve_id': 3, 'prenom': 'Aissatou', 'sexe': 'F', 'moyenne': Decimal('16.8')},
        {'eleve_id': 4, 'prenom': 'Ibrahim', 'sexe': 'M', 'moyenne': Decimal('16.8')},  # Ex-aequo
        {'eleve_id': 5, 'prenom': 'Mariam', 'sexe': 'F', 'moyenne': Decimal('14.5')},
    ]
    
    eleves_classes = calculer_rang_intelligent(eleves_test)
    
    print("\n┌──────────┬──────────────┬──────┬─────────┬───────────────┬─────────────┐")
    print("│   Rang   │    Prénom    │ Sexe │ Moyenne │    Mention    │ Distinction │")
    print("├──────────┼──────────────┼──────┼─────────┼───────────────┼─────────────┤")
    
    for eleve in eleves_classes:
        distinction = obtenir_encouragements(eleve['moyenne'])
        icone = "👧" if eleve['sexe'] == 'F' else "👦"
        
        print(f"│ {eleve['rang']:^8} │ {eleve['prenom']:12s} │  {icone}  │ {eleve['moyenne']:>7.2f} │ {eleve['mention']:13s} │ {distinction:11s} │")
    
    print("└──────────┴──────────────┴──────┴─────────┴───────────────┴─────────────┘")
    
    print("\n" + Fore.YELLOW + "💬 TEST DES APPRÉCIATIONS DYNAMIQUES" + Style.RESET_ALL)
    print("-"*80)
    
    for eleve in eleves_classes[:3]:
        print(f"\n{eleve['prenom']} ({eleve['moyenne']:.2f}/20):")
        print(f"→ {eleve['appreciation']}")
    
    print("\n" + Back.GREEN + Fore.WHITE + " ✅ SYSTÈME INTELLIGENT OPÉRATIONNEL " + Style.RESET_ALL)
    print("="*80 + "\n")
