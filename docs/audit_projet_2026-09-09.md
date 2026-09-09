# Audit du projet — 9 septembre 2026

## Périmètre et méthode

Audit de la version locale issue de `fc06325`, sur la branche `codex/audit-projet-20260909`.

- Suite des 13 modules : élèves, paiements, dépenses, salaires, utilisateurs, rapports, administration, bus, notes, abonnements, vie scolaire, synchronisation et socle `ecole_moderne`.
- Analyse statique des 502 fichiers Python suivis initialement par Git, puis vérification des noms dans les 428 fonctions raccordées aux URLs.
- Compilation des 204 modèles HTML livrés dans `templates/`.
- Contrôles Django, détection de migrations manquantes et application de toutes les migrations sur une base SQLite en mémoire.
- Tests fonctionnels sur données fictives, avec deux écoles et différents droits utilisateur. Les fichiers des tests utilisent des répertoires temporaires. Aucun paiement réel n'a été modifié.

Environnement : Windows, Python 3.13.11, Django 5.2.6 du venv local. La suite de tests crée son schéma depuis les modèles pour accélérer l'exécution ; l'application effective des migrations est contrôlée séparément.

## Défauts corrigés

| Zone | Défaut constaté | Correction et vérification |
| --- | --- | --- |
| Matricules | Une erreur d'indentation interrompait la résolution du code par nom/niveau. Les nouvelles inscriptions utilisaient le repli `CL…` malgré un niveau connu. | Rétablissement de la fonction, normalisation des noms et prise en charge des sections A/B/C. Un code personnalisé reste prioritaire ; une modification ordinaire ne renumérote pas les matricules existants. |
| Dossiers et cartes élèves | Le rôle ADMIN d'une école contournait plusieurs filtres d'établissement. | Application des restrictions d'école aux listes, détails, formulaires, exports, cartes, corbeille et opérations associées. Le superutilisateur conserve l'accès global. |
| Choix des responsables et classes | Les formulaires d'édition pouvaient proposer les classes ou responsables d'une autre école. | Passage de l'utilisateur au formulaire, restriction des choix et repli sur une liste vide en cas d'erreur de filtrage. |
| Compteurs élèves | Le cache pouvait conserver des compteurs périmés après modification ou suppression. | Agrégation des compteurs à chaque lecture ; test du changement de statut puis de la suppression. |
| Pagination | Transformer en SQL un queryset explicitement vide levait `EmptyResultSet`. | Utilisation du décompte natif de Django et prise en charge des listes vides. |
| Saisie des notes | Appel à `_get_ecole`, fonction absente. | Utilisation des helpers existants d'école et de correspondance des classes ; sélection d'élève limitée à la classe affichée. |
| Bulletin web | Détecteur de niveau non importé et liens PDF/Excel sans namespace. | Import corrigé, liens résolus et restriction de la classe de notes à l'établissement autorisé. |
| Impression des notes | Le tableau HTML recherchait le statut `actif` au lieu de `ACTIF`, n'identifiait pas la classe réelle et ne fournissait pas les champs attendus au modèle HTML. | Préparation commune des données HTML/PDF, association des classes par le helper existant et affichage des prénoms, noms et notes. |
| Notes imprimées | Les zéros étaient masqués et les périodes étaient calculées comme des mois, y compris les trimestres. | Affichage du zéro, choix du calcul mensuel/trimestriel/semestriel/annuel et prise en charge des appréciations maternelles. |
| Classements | Un mapping d'identifiants 61→56 / 59→8 pouvait désigner la mauvaise classe ; le tri PDF dépendait du texte du rang. | Suppression du mapping historique, résolution dans la bonne école et tri numérique conservant les ex æquo. |
| Classement annuel | L'invalidation omettait les clés du cache des classements annuels. | Invalidation des deux systèmes annuels ; tests après modification puis suppression d'une composition. |
| Maternelle | La cinquième période était rabattue sur le premier trimestre par le calcul des rangs. | Reconnaissance des cinq périodes et vérification des appréciations imprimées. |
| Enregistrement des notes | Une note refusée après une première note valide laissait des écritures partielles ; certaines valeurs non numériques étaient ignorées avec une réponse de succès. | Validation de tout le formulaire avant écriture, transaction unique, contrôle des périodes, de l'année et des valeurs finies, respect du semestre demandé. Les tests vérifient que le refus ne modifie aucune note. |
| Configuration et pages HTML | Quatre modèles contenaient une syntaxe Django invalide ou des filtres non chargés. | Corrections dans `configurer_ecole`, `statistiques_complete`, `saisie_notes_guineen` et `gerer_rappels` ; test de compilation globale. |
| Analyse maternelle | `JsonResponse` n'était pas importé dans le helper d'analyse textuelle. | Import ajouté. |

Le code de dessin placé après des retours inconditionnels des cartes et les anciennes branches de calcul inaccessibles ont été retirés. Les règles centrales de calcul des paiements n'ont pas été remplacées.

## Résultats

- Avant correction : **415 tests réussis**, aucun test ignoré.
- Régressions ajoutées : **31 tests réussis**, dont des sous-cas de séparation des écoles, de sauvegarde indivisible, de périodes scolaires et de compilation HTML.
- Suite complète après correction : **446 tests réussis**, aucun échec, aucune erreur et aucun test ignoré (430,924 secondes).
- Contrôles Django : aucune anomalie signalée.
- Migrations : aucune migration manquante ; chaîne complète appliquée avec succès en mémoire.
- Export réel du tableau de notes avec WeasyPrint : **1 test supplémentaire réussi**, PDF généré.
- Analyse des vues raccordées aux URLs : aucun nom non défini détecté après correction. Cette analyse ne constitue pas une preuve d'absence de tout défaut d'exécution.

Tests ajoutés :

- `eleves/test_audit_matricules_cartes.py`
- `notes/test_audit_notes.py`
- `ecole_moderne/test_templates.py`

Pour relancer les régressions dans un environnement de développement configuré pour les tests :

```powershell
venv/Scripts/python.exe manage.py test eleves.test_audit_matricules_cartes notes.test_audit_notes ecole_moderne.test_templates --noinput
```

La campagne d'audit a utilisé un lanceur temporaire avec base en mémoire et médias isolés, conservé localement dans `tmp/audit_20260909/`, ainsi que les journaux et résumés JSON. Ce répertoire est ignoré par Git.

## Limites et ancien code

- Les 23 références d'URLs absentes relevées dans d'anciens modèles de dépenses concernent des écrans historiques non raccordés à l'application actuelle. Les routes stock/inventaires ont été volontairement retirées par le commit `afe6226` du 2 août 2026. Elles ne sont pas réactivées par cet audit.
- Les sauvegardes Python, les anciennes fonctions non raccordées aux URLs et les scripts de maintenance qui créent des données n'ont pas été exécutés sur une base réelle. Des alertes statiques y subsistent ; elles ne sont pas assimilées à des erreurs 500 des pages actives.
- Le test permanent du tableau PDF vérifie les données et les ex æquo avec un moteur PDF simulé. Un contrôle supplémentaire a généré un vrai tableau PDF avec WeasyPrint et des notes fictives ; les cartes scolaires ont également été produites par leur moteur réel. La mise en page de tous les documents n’a pas fait l’objet d’une revue visuelle exhaustive.
- Les modifications du code sont validées localement. Le fonctionnement après déploiement du serveur public n'est pas attesté par cet audit. L'installateur Windows n'est pas reconstruit dans cette campagne.
