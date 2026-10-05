# Recherche locale dans les tutoriels

Application Windows légère pour rechercher dans le contenu des fichiers Markdown, les noms de tous les fichiers et les noms des dossiers. Google Drive Desktop fournit le dossier local ; aucune API Google Drive n'est utilisée. Les recherches consultent uniquement un index SQLite FTS5 persistant.

## Prérequis

- Windows 10/11 et Python **3.12 ou supérieur**, disponible dans le PATH.
- SQLite compilé avec FTS5 (inclus dans le Python Windows officiel ; vérifié ici avec Python 3.13.15 et SQLite 3.50.4).
- Google Drive Desktop démarré, avec les tutoriels **disponibles hors connexion**.
- Internet uniquement pour installer les dépendances au premier lancement.

## Installation et démarrage simple

Double-cliquez sur **`scripts\start.bat`**. Le script crée `.venv` et installe les dépendances si nécessaire. Ouvrez ensuite **http://localhost:8000** dès que la console indique `Uvicorn running`. Le premier lancement indexe les fichiers en arrière-plan ; les suivants réutilisent l'index enregistré, sans parcourir à nouveau le dossier. Utilisez **Réindexer** pour actualiser les ajouts, modifications et suppressions.
Gardez cette fenêtre ouverte. Pour arrêter, utilisez `Ctrl+C`.

Le serveur écoute exclusivement sur **127.0.0.1:8000** avec cette commande de lancement.
N'utilisez pas `--host 0.0.0.0`. Lancez une seule instance et un seul worker.

## Installation manuelle (PowerShell)

Depuis le dossier du projet :

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Si PowerShell interdit l'activation, aucune modification de la politique système
n'est nécessaire : utilisez directement `.venv\Scripts\python.exe` à la place de `python`.

## Configuration

Copiez `.env.example` vers `.env` pour adapter le chemin. Enregistrez ce fichier en UTF-8 :

```dotenv
DOCUMENT_ROOT=G:\Mon Drive\Fillon Technologies\Résumer\Tutorial
DATABASE_PATH=data/search.db
```

Les espaces, accents et caractères Unicode sont acceptés. Les variables d'environnement
existantes ont priorité sur `.env`. Les chemins relatifs sont résolus depuis le projet,
indépendamment du dossier de lancement. Redémarrez après un changement de configuration.
La base est créée automatiquement ; il est préférable de la conserver hors du dossier indexé.
Un changement de racine remplace l'ancien index au prochain scan accessible.

## Utilisation et recherche

Saisissez un terme puis cliquez sur **Rechercher**, ou appuyez sur Entrée.

| Filtre | Périmètre |
| --- | --- |
| Tous | Contenu Markdown, noms des fichiers et noms des dossiers |
| Contenu | Contenu des fichiers `.md`, y compris `.MD` |
| Fichiers | Noms de tous les fichiers et contenu Markdown, affichés dans une seule liste de titres |
| Dossiers | Noms propres des dossiers, y compris les dossiers vides |

Chaque élément apparaît une fois. Les enfants d'un dossier ne sont pas ajoutés simplement
parce que leur parent correspond. La racine elle-même n'est pas un résultat.
Les résultats affichent un chemin relatif, un extrait pour les correspondances de contenu,
et les boutons **Ouvrir** / **Ouvrir le dossier**. Windows utilise l'application associée
au type de fichier. Les résultats sont paginés par 50.

Dans **Fichiers**, une seule liste affiche les titres des fichiers trouvés par leur
nom ou leur contenu Markdown, avec les boutons d'ouverture. Chaque fichier apparaît
une seule fois, même s'il correspond dans les deux champs. Aucun extrait ni chemin
n'est affiché dans ce mode ; le chemin reste consultable au survol du titre.
Les catégories de formats restent appliquées. Les modes Tous et Contenu conservent
leurs extraits de texte.

### Choix du format mémorisé

Choisissez une catégorie dans les cartes au-dessus du champ de recherche :
**Tous les formats**, **Markdown**, **Images**, **PDF**, **Documents**, **Autres fichiers**.
Le titre, les indications et les résultats s'adaptent au format sélectionné.
Le navigateur mémorise le format, le périmètre et l'option Mot exact pour les visites
suivantes, sur la même adresse locale. Le terme recherché n'est pas mémorisé.
Si le stockage navigateur est interdit, les choix restent actifs pendant la visite.

- Markdown : contenu et noms des `.md`.
- Images : noms des PNG, JPEG, GIF, WebP, SVG, BMP, TIFF, ICO, AVIF, HEIC et HEIF.
- PDF : noms des `.pdf`.
- Documents : noms des fichiers texte, Word, OpenDocument, tableurs et présentations.
- Autres fichiers : noms des fichiers hors de ces catégories, y compris sans extension.

Le texte des PDF et documents ainsi que le contenu des images ne sont pas indexés.
Le filtre Contenu est donc désactivé pour ces catégories. Le filtre Dossiers est
disponible avec Tous les formats. Aucun nouveau scan n'est nécessaire pour utiliser
les catégories : les extensions sont déjà enregistrées dans SQLite.

La recherche ignore la casse et les accents usuels (`resume` trouve `résumé`).
Par défaut elle recherche des **préfixes de mots** : `boot` trouve `bootloader`,
mais pas `rebootloader`. **Mot exact** désactive ce préfixe : `boot` trouve uniquement
le mot `boot`. Plusieurs mots doivent tous être présents dans les champs recherchés.
Les opérateurs FTS sont traités comme du texte ordinaire. La ponctuation sépare les
mots, selon FTS5 : `C++` recherche le mot `C`, sans distinction des signes `+`.
Il n'y a ni recherche fuzzy ni recherche par sous-chaîne au milieu d'un mot.

## Indexation

- Scan automatique uniquement lorsqu'aucun index validé n'existe pour la racine configurée
  (premier lancement, base supprimée ou changement de dossier). Les autres démarrages
  réutilisent l'index SQLite sans scan. Le bouton **Réindexer** actualise l'index à la demande.
- Le scan initial s'exécute en arrière-plan. Le statut se rafraîchit automatiquement
  toutes les 1,5 seconde pendant le scan ; le dernier index validé reste consultable.
  Les nouveaux résultats sont validés à la fin du scan, puis la recherche affichée est relancée.
  Le nombre total définitif n'est connu qu'à la fin : aucun deuxième scan n'est fait pour le compter.
- À l'arrêt, le scan est interrompu entre les fichiers et sa transaction incomplète
  est annulée. Si un index existait déjà, il est réutilisé au prochain lancement ;
  cliquez sur Réindexer pour reprendre la mise à jour. Si le premier scan n'avait
  jamais abouti, l'indexation initiale sera retentée au prochain lancement.
- Aucun watchdog ni surveillance permanente du disque.
- Seuls les Markdown nouveaux ou dont la date de modification en nanosecondes ou
  la taille a changé sont relus. Les autres fichiers servent à la recherche par nom.
- Les suppressions sont répercutées dans les tables et dans FTS5 par des triggers.
- Les fichiers sont lus en UTF-8, avec ou sans BOM. Un fichier illisible est journalisé
  et ignoré ; s'il avait déjà été indexé, sa dernière version reste consultable.
- Une arborescence partiellement inaccessible empêche toute suppression dans l'index.
  Une racine absente laisse l'index existant intact.
- Les liens symboliques et jonctions internes sont ignorés pour éviter de sortir de la racine.
- Les compteurs d'indexation incluent fichiers **et** dossiers ; le statut les détaille.

Une modification conservant exactement date et taille n'est pas détectée. Pour reconstruire
l'index dans ce cas, arrêtez l'application, supprimez `data\search.db` et ses éventuels
fichiers `-wal` / `-shm`, puis redémarrez.

## API

| Route | Fonction |
| --- | --- |
| `GET /` | Interface Jinja2 |
| `GET /api/search?q=bootloader&type=all&exact=false&limit=50&offset=0` | Recherche FTS5 |
| `GET /api/status` | Compteurs, racine, dernière indexation et erreurs |
| `POST /api/reindex` | Scan incrémental |
| `POST /api/open/{id}` avec `{"target":"file"}` ou `{"target":"directory"}` | Ouverture Windows |

Valeurs de `type` : `all`, `content`, `files`, `directories`.
Paramètre facultatif `format` : `all` (par défaut), `markdown`, `images`, `pdf`,
`documents`, `other`. Exemple : `/api/search?q=schema&format=images&type=files`.
Le filtre est appliqué avant le comptage et la pagination. Une combinaison
`type=content&format=pdf` ne donne aucun résultat, le contenu PDF n'étant pas indexé.
Les actions POST nécessitent le jeton `X-Local-Token` présent dans la page locale.
L'interface le transmet automatiquement. Cette protection et la validation de l'origine
empêchent un autre site de déclencher des actions locales. Aucun chemin fourni par
le navigateur n'est utilisé pour ouvrir un élément : son identifiant est résolu dans
SQLite, puis le chemin réel est vérifié sous la racine. Les contenus affichés sont
échappés avant surlignage, les requêtes SQL sont paramétrées, et les hôtes sont limités
à localhost/loopback.

## Tests

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
```

Si Node.js est disponible, vérifiez aussi la mémorisation des préférences :

```powershell
node --test tests/test_preferences.js
```

Node.js sert uniquement à ces tests optionnels ; l'application n'en dépend pas.

Les tests utilisent exclusivement des dossiers temporaires, jamais le vrai Google Drive.
Ils couvrent l'ajout, la modification, l'absence de relecture, la suppression, UTF-8/BOM,
les erreurs de lecture et de scan, les filtres, les accents, la casse, les mots exacts,
la pagination, l'échappement HTML, les actions locales et le confinement des chemins.

### Vérification de cette livraison

- 58 tests Python et 6 tests JavaScript réussis sous Windows avec Python 3.13.15 et SQLite 3.50.4.
- Démarrage réel d'Uvicorn sur `127.0.0.1:8000` : page, assets, recherche et statut répondent HTTP 200, même avec la racine inaccessible.
- Jeu synthétique de 3 000 Markdown : index initial en 3,56 s ; recherche médiane
  de 32,5 ms, maximum de 47,5 ms sur 20 requêtes ; scan incrémental de 1,81 s,
  3 000 fichiers inchangés. Ces mesures dépendent du matériel et du contenu.
- Aucun navigateur connecté n'était disponible pour une vérification visuelle.
  Le vrai dossier Google Drive était inaccessible depuis l'environnement de développement.

## Architecture

```text
app/config.py       Configuration .env / environnement
app/database.py     Schéma SQLite, FTS5, triggers et connexions
app/formats.py      Catégories de formats et extensions
app/indexer.py      Scan incrémental et gestion des erreurs disque
app/search.py       Requêtes FTS5, classement BM25 et surlignage
app/models.py       Modèles et validation
app/main.py         FastAPI, démarrage, statut et actions Windows
app/templates/     Interface Jinja2
app/static/        CSS et JavaScript Vanilla, sans CDN
data/search.db     Index créé au premier lancement
scripts/start.bat  Lanceur Windows
tests/             Tests pytest
```

Les connexions SQLite sont courtes, transactionnelles et fermées explicitement.
Le mode WAL permet les recherches pendant un scan. Les opérations synchrones sont
exécutées dans le pool de threads de FastAPI ; le scan initial utilise un thread en
arrière-plan. Un verrou empêche deux scans simultanés.
Références de mise en œuvre : [cycle de vie FastAPI](https://fastapi.tiangolo.com/advanced/events/)
et [templates Jinja2](https://fastapi.tiangolo.com/advanced/templates/).

## Dépannage

**Connexion échouée au démarrage** : attendez la ligne `Uvicorn running on http://127.0.0.1:8000`
après le lancement, puis rechargez la page. L'indexation ne bloque plus l'ouverture du
serveur. Après une mise à jour du code, arrêtez l'ancienne instance avec `Ctrl+C` et
relancez `start.bat`.

**Google Drive indisponible / lecteur G: absent** : la page reste accessible et affiche
« Le dossier de documentation est inaccessible. Vérifiez que Google Drive est démarré
et synchronisé. » Démarrez Drive, vérifiez le chemin et la disponibilité hors connexion,
puis cliquez sur Réindexer. Le dernier index reste consultable.

**Indexation partielle** : consultez les avertissements dans la console. Fermez le
programme verrouillant le fichier, corrigez son encodage ou ses permissions, puis réindexez.

**SQLite verrouillé** : l'application attend jusqu'à cinq secondes puis retourne une
erreur lisible. Arrêtez les autres instances et réessayez. Gardez la base sur un disque local.

**Port 8000 occupé** : fermez l'autre application ou lancez Uvicorn avec `--port 8001`
et utilisez http://localhost:8001.

**Ouvrir ne fonctionne pas** : vérifiez que le fichier existe et qu'une application
Windows est associée à son extension. L'ouverture n'est prise en charge que sous Windows.

**FTS5 absent** : utilisez une distribution officielle récente de Python pour Windows.
Vérification :

```powershell
python -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute('CREATE VIRTUAL TABLE test USING fts5(content)'); print('FTS5 disponible')"
```
