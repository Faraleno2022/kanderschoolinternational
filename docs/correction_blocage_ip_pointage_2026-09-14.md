# Correction des blocages IP au pointage — 14 septembre 2026

## Défauts reproduits

- AXES prenait l'adresse du proxy `10.0.4.129`, tandis que l'application utilisait la première adresse `X-Forwarded-For`. Les deux mécanismes comptaient donc des clients différents. La liste AXES plate bloquait indépendamment par compte **ou** par IP, au lieu du couple compte/IP annoncé par le commentaire.
- Le compteur de requêtes repoussait son expiration à chaque visite : une navigation régulière sur plusieurs minutes finissait par dépasser le plafond annoncé par minute.
- Une observation normale contenant `;` ou `--` déclenchait un blocage SQL de 24 heures. Le contrôle XSS pouvait interpréter `observations=` ou `options=` dans une URL comme un attribut JavaScript.
- Les formulaires de déblocage effaçaient des clés du cache mais conservaient les tentatives AXES en base. Un administrateur déjà connecté ne pouvait pas ouvrir le formulaire de déblocage depuis son IP bloquée.

Les journaux fournis montrent des connexions réussies et un échec de connexion ; les messages de nettoyage AXES ne sont pas des erreurs. Ils ne contiennent pas le motif précis du refus au pointage. Les défauts ci-dessus ont été reproduits dans les tests, sans attribuer avec certitude le refus observé à un seul d'entre eux. L'erreur isolée `OSError: write error` reste non diagnostiquée faute de trace complète et de requête associée.

## Corrections

Une même fonction fournit désormais l'adresse client à AXES, à la connexion, aux décorateurs et aux middlewares de sécurité. Seul un proxy explicitement approuvé peut transmettre `X-Real-IP` ; à défaut d'adresse valide, la dernière adresse de `X-Forwarded-For` est utilisée. Les en-têtes envoyés directement par un client sont ignorés. Les adresses IPv4/IPv6 sont validées et normalisées.

Ce choix suit les garanties de [PythonAnywhere sur les adresses clientes](https://help.pythonanywhere.com/pages/WebAppClientIPAddresses) : `REMOTE_ADDR` désigne le proxy, `X-Real-IP` est remplacé par celui-ci, et seule la dernière adresse `X-Forwarded-For` est garantie par l'hébergeur. Cette politique ne doit pas être réutilisée pour un autre proxy sans vérifier ses garanties.

AXES bloque désormais le couple `[['username', 'ip_address']]`. Les échecs d'un autre compte sur la même IP ne verrouillent pas tous les comptes. Un même compte reste bloqué sur l'IP responsable des échecs. Voir la [configuration des paramètres de verrouillage AXES](https://django-axes.readthedocs.io/en/stable/5_customization.html).

Le compteur conserve une fenêtre de 60 secondes, plafonnée à 100 requêtes. Les formulaires sont analysés à partir des valeurs décodées, y compris les champs répétés ; la ponctuation normale et les noms de paramètres ne déclenchent plus de blocage. Les constructions SQL suspectes, les scripts/attributs HTML dangereux, la traversée de chemins et les protections CSRF restent contrôlés.

Le déblocage retire les entrées AXES et les clés applicatives correspondant aux critères saisis. Une recherche par compte respecte la casse des enregistrements AXES et ne supprime pas les blocages des autres comptes. Des critères vides ne déclenchent jamais de remise à zéro globale. Les formulaires existants gardent leurs contrôles d'autorisation et de CSRF.

Seul le formulaire `/utilisateurs/security/admin-unlock/` traverse un blocage IP existant. Son utilisation exige une session staff, le code de vérification configuré et un jeton CSRF valide. Son ouverture seule ne débloque rien ; le débit et les contrôles d'attaque restent appliqués.

## Validation

- Suite complète : **520 tests réussis**, aucun échec, aucune erreur, aucun test ignoré (418 secondes).
- Le nouveau module `ecole_moderne.test_pointage_ip` contient **33 tests** : pointage HTTP avec ponctuation, refus SQL/XSS/CSRF, compteur sur plusieurs minutes, en-têtes falsifiés, IPv6, isolation AXES, déblocage et contrôles d'autorisation.
- Première validation ciblée : **151 tests réussis** (salaires, pointage, sessions et sécurité), avant les derniers cas complémentaires inclus dans la suite complète.
- Contrôle Django sans anomalie ; aucune nouvelle migration détectée ; application de toutes les migrations réussie sur la base temporaire.
- `git diff --check` sans erreur.

 Les tests utilisent SQLite en mémoire, des médias temporaires et un serveur de messagerie simulé. Aucun paiement, compte ou pointage réel n'est modifié.

## Application sur le serveur

1. Récupérer la branche `main` mise à jour dans le dépôt utilisé par l'application web : `git pull --ff-only origin main`.
2. Vérifier les proxys approuvés. Sans configuration spécifique, `10.0.4.129/32` est utilisé, d'après les journaux fournis. Pour remplacer cette liste, définir `TRUSTED_PROXY_NETWORKS` dans l'environnement ou le `.env` du serveur, avec les IP/CIDR exacts séparés par des virgules. Une valeur explicitement vide ignore les en-têtes de proxy. Ne pas ajouter les IP publiques des utilisateurs à cette liste.
3. Recharger l'application dans l'onglet **Web → Reload** de PythonAnywhere. Cette correction ne nécessite ni nouvelle migration ni nouvelle dépendance.
4. Si un blocage subsiste, un administrateur déjà connecté ouvre `/utilisateurs/security/admin-unlock/`, renseigne l'IP publique du client et, si nécessaire, son compte, puis valide avec son code. Le plafond de débit reste actif : attendre la fin de la minute en cas de rafale. Avec seulement le nom du compte, seuls les couples retrouvés via AXES sont nettoyés ; saisir aussi l'IP pour retirer un blocage global IP ou un verrou résiduel du cache.
5. Vérifier que la prochaine connexion est journalisée avec la même IP cliente côté AXES et côté application, puis enregistrer un pointage avec une observation contenant un point-virgule.

Le code utilise le cache local en mémoire configuré dans le projet. Un déblocage par formulaire agit sur le processus qui traite la requête ; un rechargement des processus web vide leurs caches locaux. Aucun effacement global de la base ou des tentatives AXES n'est nécessaire. Le déploiement et le déblocage effectif du site public ne sont pas effectués depuis cet environnement local.
