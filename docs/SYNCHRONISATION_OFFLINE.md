# Synchronisation offline / online

## 1. Configurer le serveur Render

Dans Render, ajoute une variable d'environnement secrete :

```text
MYSCHOOL_SYNC_ADMIN_TOKEN=une-longue-cle-secrete
```

Garde aussi :

```text
MYSCHOOL_SYNC_SERVER_URL=https://gs-hadja-kanfing-dian.onrender.com
```

## 2. Enregistrer un poste offline

Sur chaque poste local/offline, mets d'abord dans `.env` :

```text
MYSCHOOL_SYNC_SERVER_URL=https://gs-hadja-kanfing-dian.onrender.com
MYSCHOOL_SYNC_ADMIN_TOKEN=la-meme-cle-que-sur-render
MYSCHOOL_SYNC_ECOLE_ID=1
```

Puis lance :

```bash
python manage.py register_sync_device --nom "Direction"
```

La commande affiche :

```text
MYSCHOOL_SYNC_DEVICE_ID=...
MYSCHOOL_SYNC_TOKEN=...
MYSCHOOL_SYNC_ECOLE_ID=...
```

Copie ces valeurs dans le `.env` du poste offline. Le token n'est affiche qu'une seule fois.

## 3. Synchroniser

Sur le poste offline :

```bash
python manage.py sync_offline
```

Pour la premiere synchronisation d'un poste nouvellement installe :

```bash
python manage.py sync_offline --initial
```

Pour recevoir seulement les changements :

```bash
python manage.py sync_offline --pull-only
```

Pour envoyer seulement les changements locaux :

```bash
python manage.py sync_offline --push-only
```

Le poste memorise desormais lui-meme ou il en est : inutile de repasser
`--since-id` a chaque fois. Ne l'utilisez que pour forcer une reprise a un
point precis :

```bash
python manage.py sync_offline --since-id 0
```

## 4. Ecoute continue (recommandee)

```bash
python manage.py sync_offline --boucle
```

Le poste envoie ce qu'il a en attente, puis tient une requete ouverte que le
serveur debloque des qu'un changement arrive. Une donnee saisie sur le
serveur descend donc **en une seconde environ**, sans WebSocket ni broker :
une seule requete HTTP retenue, que n'importe quel reseau domestique laisse
passer.

C'est ce mode qui rend la synchronisation vivante ; sans lui, rien ne
descend tant que personne ne relance la commande a la main.

### Reglages du delai

| Reglage | Defaut | Role |
|---|---|---|
| `MYSCHOOL_SYNC_WAIT` | 25 s | Duree pendant laquelle le poste demande au serveur de retenir sa requete |
| `MYSCHOOL_SYNC_LONGPOLL_MAX` | 30 s | Plafond impose par le serveur, quelle que soit la demande du poste |
| `MYSCHOOL_SYNC_LONGPOLL_INTERVAL` | 1,0 s | Frequence a laquelle le serveur regarde s'il a du neuf a livrer |

`MYSCHOOL_SYNC_WAIT` doit rester **sous** le delai d'inactivite de
l'hebergeur et du reverse proxy, sinon la requete est coupee en pleine
attente. En cas de doute, descendez a 15 s : la latence reste d'environ une
seconde, seul le nombre de requetes augmente.

### Latence attendue

| Sens | Delai |
|---|---|
| Serveur vers poste | ~1 seconde |
| Poste vers serveur | jusqu'a `MYSCHOOL_SYNC_WAIT` |

L'asymetrie est assumee : la requete retenue occupe le tour, donc une saisie
faite au poste part au tour suivant. Baisser `MYSCHOOL_SYNC_WAIT` reduit ce
delai au prix de plus de requetes.

### En cas de coupure reseau

La boucle survit a une panne : elle reessaie avec un delai qui double a
chaque echec, plafonne a 5 minutes, sans jamais abandonner. Les changements
locaux restent en attente et repartent au retour du reseau.

Un jeton refuse (401 ou 403) arrete en revanche la commande : reessayer
indefiniment avec de mauvais identifiants ne menerait a rien.

## Notes importantes

- Chaque poste offline doit avoir son propre `MYSCHOOL_SYNC_DEVICE_ID` et `MYSCHOOL_SYNC_TOKEN`.
- Les changements sont echanges via `/api/v1/sync/push/` et `/api/v1/sync/pull/`.
- Les modeles synchronises sont listes dans `synchronisation/registry.py` : un modele absent de cette liste ne circule pas.
- Un changement qui echoue a s'appliquer est marque `FAILED` avec son erreur, et **le repere avance quand meme** : un changement irrecuperable ne bloque pas indefiniment tout ce qui le suit. Ces lignes sont a examiner dans l'administration.
- Le repere courant d'un poste est stocke dans la table `SyncCursor`, une ligne par ecole.
