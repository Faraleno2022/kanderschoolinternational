# Audit de sécurité local — 9 au 11 septembre 2026

## Périmètre et méthode

Analyse statique de 505 fichiers Python suivis par Git, contrôle des bibliothèques avec pip-audit et tests HTTP Django sur des comptes et écoles fictifs. Les tests utilisent une base SQLite en mémoire, des médias temporaires et un backend email en mémoire. Aucune donnée réelle ni aucun paiement de production n’a été modifié. Le site public et son infrastructure n’ont pas été soumis à un test d’intrusion réseau.

Les alertes statiques ne constituent pas toutes des vulnérabilités démontrées. Les corrections ci-dessous reposent sur les chemins de code concernés et, pour les accès, permissions, CSRF, redirections et attributs HTML, des tests de régression exécutés avant et après correction.

## Corrections

| Domaine | Défaut observé | Correction |
| --- | --- | --- |
| Salaires et personnel | Des administrateurs d’école pouvaient consulter des salaires, proposer une école étrangère dans un formulaire et modifier le statut d’un salarié d’une autre école. Les comptes sans école pouvaient accéder à certaines listes globales. | Séparation entre administrateur d’école et superadministrateur ; refus des comptes sans école ; restriction des listes, exports, périodes et formulaires. |
| Exports de paiements | Les récapitulatifs par classe pouvaient inclure d’autres écoles pour un administrateur d’école. | Filtrage obligatoire par école pour les exports Excel et PDF ; seul le superadministrateur conserve une vue globale. |
| Notes et maternelle | Accès par identifiant à des élèves, classes et bulletins étrangers ; certaines recherches de classes abandonnaient le filtre d’école ; des appréciations pouvaient associer une matière locale à un élève étranger. | Restriction des objets avant utilisation, correspondance de classe limitée à son école, contrôle des élèves et matières dans les deux formats d’enregistrement des appréciations. |
| Autorisations d’écriture | Plusieurs API de notes, le changement de statut du personnel et le passage d’une dépense à « payée » omettaient les permissions déjà définies dans le projet. | Application des permissions existantes de gestion des notes, ajout/gestion du personnel et validation des dépenses. Les tests vérifient également les parcours autorisés. |
| Abonnements et cantine | Les listes et l’enregistrement des présences autorisaient des accès entre écoles ; certains comptes sans école pouvaient écrire. | Querysets limités à l’école, y compris les élèves fournis dans les requêtes POST et les présences de cantine. |
| Synchronisation | L’enregistrement d’un appareil acceptait une session d’administrateur sans protection CSRF. Un JSON de type liste pouvait provoquer une erreur. | Jeton CSRF requis pour les sessions par cookie ; authentification explicite par jeton conservée pour les clients machine ; objet JSON obligatoire. |
| Connexion et téléphone | Une destination commençant par deux barres obliques pouvait rediriger vers un domaine tiers. | Validation Django de l’hôte et du schéma de la destination, avec maintien des redirections locales. |
| Lectures de bulletins | Une simple requête GET créait des bulletins ou évaluations. | Création réservée aux requêtes POST autorisées. |
| HTML des images | Des guillemets dans les attributs du composant d’image permettaient d’ajouter un attribut exécutable. | Échappement via format_html, validation des noms d’attributs et refus des gestionnaires d’événements fournis en paramètres. L’injection a été démontrée au niveau du composant ; son exposition sur une page particulière n’a pas été démontrée. |
| Lanceurs Windows | La configuration desktop utilisait également une clé fixe. En cas d’échec d’écriture de la clé de session, la clé de secours était déduite d’un chemin prévisible. | Fonction commune aux deux configurations, avec une clé cryptographiquement aléatoire même lorsque sa persistance échoue ; fichier existant conservé, fichier vide remplacé. Sans persistance possible, la clé change au redémarrage. |
| Installateur Windows | Le nom d’un fichier VBScript temporaire était choisi avant sa création. | Création et ouverture simultanées par NamedTemporaryFile. La syntaxe est vérifiée ; l’installateur n’a pas été exécuté sur le poste pendant cet audit. |

## Dépendances

Le manifeste requirements.txt a été installé et vérifié dans le venv local. Versions de sécurité retenues : Django 5.2.17, aiohttp 3.14.3, idna 3.15, Pillow 12.3.0, PyJWT 2.13.0, requests 2.33.0, sqlparse 0.6.0, urllib3 2.7.0, WeasyPrint 70.0 et python-dotenv 1.2.2. Les outils locaux pip et setuptools ont également été actualisés.

Le dernier contrôle pip-audit retourne **0 alerte sur 71 bibliothèques installées**. Ce résultat décrit la base d’avis utilisée au moment du contrôle, pas une garantie d’absence de toute vulnérabilité. Deux avis PyJWT publiés le 8 septembre concernent le traitement de jeux de clés JWK et la réutilisation des options de décodage ; ces API ne sont pas appelées par le code applicatif inspecté. Aucun correctif applicatif de contournement n’a été ajouté pour ces usages absents.

Sources principales consultées :

- [Correctifs Django 5.2.17](https://www.djangoproject.com/weblog/2026/aug/04/security-releases/).
- [Injection CSS dans WeasyPrint](https://github.com/Kozea/WeasyPrint/security/advisories/GHSA-jhhc-3hcp-qhm5).
- [Chargement de ressources WeasyPrint et contournement du fetcher](https://github.com/Kozea/WeasyPrint/security/advisories/GHSA-jf6q-chmf-3h3v). Le scanner indique la version 70.0 comme corrigée ; elle a été installée, réanalysée et utilisée pour générer un PDF réel.
- [Avis PyJWT sur les jeux de clés](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-w6j9-cwv2-h6wq), [avis sur les options de décodage](https://github.com/jpadilla/pyjwt/security/advisories/GHSA-gvp8-978c-rx2q).

## Vérification

- 41 tests de sécurité dans ecole_moderne/test_vulnerabilites.py : réussis.
- 1 test supplémentaire de génération réelle d’un PDF : réussi avec WeasyPrint 70.0.
- 160 tests ciblés intermédiaires sur notes, salaires, synchronisation et sécurité : réussis avant les derniers compléments.
- Suite complète : **484 tests réussis**, sans échec ni erreur. Les trois tests de clé locale ajoutés ensuite sont inclus dans les 41 tests de sécurité complémentaires.
- Vérification des dépendances : aucune incompatibilité détectée par pip check.
- Migrations et contrôles Django : aucune incohérence de modèle détectée, aucune migration manquante, toutes les migrations appliquées avec succès sur une base SQLite en mémoire.

Les tests d’isolation couvrent les administrateurs d’école, les comptes sans école, les identifiants falsifiés et les accès autorisés du superadministrateur. Les tests de refus vérifient les données persistées, pas uniquement le code HTTP. La plupart des tests utilisent le moteur SQLite ; ils ne remplacent pas une validation de charge ou de concurrence sur la base de production.

Le module historique abonnements comporte des routes dont les templates ne sont pas distribués. Son test de liste contrôle le contexte préparé par la vue, avec le rendu remplacé ; ses écritures de présence sont testées par requêtes HTTP. Cet audit ne recrée pas ces anciens écrans.

Le MD5 restant dans license_manager.py sert à l’affichage d’une référence ; la signature associée utilise HMAC-SHA256. Les usages de random identifiés dans les scripts de données fictives ne sont pas des générateurs de secrets. Ces alertes n’ont pas été présentées comme des attaques démontrées.

## Livraison

Les corrections concernent les sources et le manifeste. Le déploiement du serveur et la reconstruction de l’installateur Windows ne sont pas effectués dans cet audit. La configuration réelle du proxy, de TLS, des secrets et des droits système de production reste hors de ces tests locaux.
