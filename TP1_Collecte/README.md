# TP1 — Collecte et exploration (Projet fil rouge : Cyberbullying Detection)

Collecte d'un corpus **multimodal (texte + image)** de messages liés au
cyberharcèlement, à partir de deux sources publiques, avec traçabilité MLOps
(MLflow + DVC).

Auteure du sujet : Dr. Asma MEKKI — MLOps, Faculté des Sciences de Tunis (IDS 5).
Année universitaire 2026-2027.

---

## 1. Périmètre de collecte

| Élément | Choix retenu |
|---|---|
| Thème global | cyberharcèlement en ligne |
| Sources | **4chan** (archive publique `a.4cdn.org`, boards `g` et `v`) et **Stack Exchange** (API publique `api.stackexchange.com`, sites `stackoverflow` et `gaming`) |
| Langue | anglais |
| Classes visées | `insulte`, `menace`, `haine`, `provocation`, `neutre` |
| Mots-clés | définis par classe dans [`src/config.py`](src/config.py) (`KEYWORDS_BY_CLASS`) |

### Pourquoi ces deux sources ?

* **4chan (`a.4cdn.org`)** — API JSON publique, sans clé ni compte, qui expose
  l'intégralité des messages d'un fil *et* les métadonnées des images
  (`tim`, `ext`, taille), donc la seule source qui alimente la partie
  multimédia du corpus. Les boards `g` (technologie) et `v` (jeux vidéo) sont
  des boards **work-safe** : ils ont été choisis volontairement pour éviter tout
  contenu adulte. Les auteurs sont anonymes par construction, et le champ
  `name` / `trip` n'est jamais conservé.
* **Stack Exchange (`api.stackexchange.com`)** — API officielle, sans clé
  (quota 300 requêtes/jour), `robots.txt` favorable, contenu textuel public et
  modéré. La collecte passe par `search/advanced` puis par les **questions et
  leurs réponses** : le paramètre `q` de `/comments` ne cherche en réalité que
  dans le message parent, il ne ramenait donc presque aucun commentaire
  contenant les mots-clés. `search/advanced`, lui, cherche bien dans le corps
  des messages. Cette source apporte un vocabulaire d'insultes « techniques »
  (« RTFM », « idiot », « cope ») et des messages neutres.

### Avertissement sur le contenu

Le corpus contient volontairement des **propos haineux, insultants et
menaçants** : c'est l'objet même du projet fil rouge. Les fichiers
`data/*.csv` et ce dépôt ne doivent pas être diffusés hors du cadre
pédagogique, et aucune image ne doit être réutilisée hors de l'analyse.

### Éthique et conformité

* `robots.txt` respecté : seules des API publiques prévues pour la lecture sont
  utilisées (`/comments`, `/thread/*.json`), jamais de scraping HTML agressif.
* **Aucune donnée personnelle** : les pseudonymes, `name`, `trip`, `display_name`
  et `user_id` ne sont jamais écrits dans le corpus ; chaque message reçoit un
  identifiant anonymisé `source-<sha1[:12]>` (voir `src/textclean.make_id`).
* Pas d'image de visage exploitable : les images proviennent d'un board
  work-safe et ne sont jamais utilisées pour de la reconnaissance faciale.
* Délai de politesse de 1 s entre deux requêtes vers un même hôte
  (`config.REQUEST_PAUSE_S`) et `User-Agent` explicite identifiant le projet.

## 2. Structure du projet

```
TP1_Collecte/
├── data/
│   ├── cyberbullying_raw.csv          # brut : id|date|text|media|url|source|metadata
│   ├── cyberbullying_raw_clean.csv    # nettoyé : date|clean_text|media|url|source
│   ├── *.csv.dvc / images.dvc         # versions DVC des jeux de données
│   └── images/                        # images téléchargées (nommage anonymisé)
├── notebooks/
│   └── TP1_collecte.ipynb             # exécution + analyse rapide
├── src/
│   ├── config.py                      # périmètre, mots-clés, chemins, paramètres
│   ├── sources/fourchan.py            # collecteur 4chan
│   ├── sources/stackexchange.py       # collecteur Stack Exchange
│   ├── textclean.py                   # HTML→texte, nettoyage, identifiants, étiquetage
│   ├── images.py                      # téléchargement et validation des images
│   ├── dataset.py                     # dédoublonnage, table nettoyée, statistiques
│   ├── pipeline.py                    # orchestration + mini-rapport
│   ├── tracking.py                    # run MLflow, suivi DVC
│   └── run_collection.py              # point d'entrée CLI
├── tests/                             # 140 tests pytest (aucun accès réseau)
├── mlflow.db                          # backend de tracking MLflow (SQLite)
├── REPORT.md                          # mini-rapport (généré)
└── requirements.txt
```

Le dossier `src/` et `tests/` s'ajoutent à l'arborescence demandée : le
notebook appelle le même code que la CLI, ce qui évite de dupliquer la logique
et rend la collecte reproductible hors notebook.

## 3. Schéma des données

**Brut — `data/cyberbullying_raw.csv`** (une ligne = un message unique)

| colonne | contenu |
|---|---|
| `id` | identifiant anonymisé `source-sha1[:12]` |
| `date` | date de publication (ISO, UTC) |
| `text` | texte brut (HTML retiré, casse et URLs conservées) |
| `media` | URL distante de l'image, vide si aucune |
| `url` | permalien du message |
| `source` | `4chan` ou `stackexchange` |
| `metadata` | JSON : board/fil, nombre de réponses, score, présence d'image |

**Nettoyé — `data/cyberbullying_raw_clean.csv`** : `date`, `clean_text`,
`media`, `url`, `source`. Dans `clean_text`, les URLs, les mentions `@` et les
`#` sont retirés, le texte est mis en minuscules et normalisé (NFKC, guillemets
typographiques, répétitions du type « sooooo » → « soo »). Les **emojis sont
conservés** : ils portent un signal affectif utile pour la détection de
cyberharcèlement.

La colonne `media` contient un **chemin relatif** (`images/<id>.png`) pour les
images effectivement téléchargées (`MAX_IMAGES`, 20 par défaut, soit le minimum
demandé) et l'**URL distante** pour les autres : télécharger les 80 images
repérées alourdirait inutilement le dépôt, et le corpus reste ainsi léger tout
en restant honnête sur ce qu'il contient. Le taux de messages « avec image »
compte les deux cas ; le nombre d'images locales est donné séparément par le
pipeline (`images.downloaded`).

## 4. Exécution

```bash
# environnement (Python 3.14)
python -m venv ../.venv
../.venv/Scripts/python.exe -m pip install -r requirements.txt

# collecte réelle + run MLflow + mini-rapport
../.venv/Scripts/python.exe -m src.run_collection

# options utiles
../.venv/Scripts/python.exe -m src.run_collection --no-mlflow --max-images 5
../.venv/Scripts/python.exe -m src.run_collection --boards g v --sites stackoverflow gaming

# tests
../.venv/Scripts/python.exe -m pytest tests -q
```

Le notebook `notebooks/TP1_collecte.ipynb` exécute le même pipeline et affiche
les statistiques, les 10 exemples qualitatifs et quelques images du corpus.

## 5. Suivi MLOps

* **MLflow** — chaque exécution crée un run dans l'expérience
  `cyberbullying_Data_Collection` : paramètres (`sources`, `keywords`,
  `collection_date`, `max_images`), métriques (`nb_raw`, `nb_clean`,
  `nb_images`, `pct_with_image`, `mean_length`, `lexical_diversity`, effectifs
  par source et par classe) et artefacts (`cyberbullying_raw.csv`,
  `cyberbullying_raw_clean.csv`, `REPORT.md`, `README.md`). Le backend est
  SQLite (`mlflow.db`) : le *file store* est en fin de vie dans MLflow 3.x.
* **DVC** — les deux jeux de données et le dossier d'images sont versionnés
  (`data/*.dvc`) dans un dépôt Git initialisé pour l'occasion :

  ```bash
  git init && dvc init
  dvc add data/cyberbullying_raw.csv data/cyberbullying_raw_clean.csv data/images
  ```

  L'historique Git documente donc *quelle* version du corpus correspond à quel
  commit de code (à committer pour figer la version).

```bash
# visualiser les runs
../.venv/Scripts/mlflow.exe ui --backend-store-uri sqlite:///mlflow.db
# état des données versionnées
../.venv/Scripts/dvc.exe status
```

## 6. Tests

`tests/` contient 140 tests pytest qui ne touchent **pas** le réseau : les
collecteurs sont testés sur des payloads d'API figés (`tests/test_sources.py`),
le téléchargement d'images reçoit un *fetcher* injecté (`tests/test_images.py`)
et le pipeline complet tourne sur des collecteurs factices
(`tests/test_pipeline.py`).

```bash
../.venv/Scripts/python.exe -m pytest tests -q
```

## 7. Limites connues

* L'étiquetage des classes est une **heuristique par mots-clés** (priorité
  menace > haine > insulte > provocation > neutre) : elle sert à décrire le
  corpus, pas à entraîner un classifieur supervisé.
* Stack Exchange est un site modéré : les messages vraiment haineux y sont
  rares, la classe `haine` est donc sous-représentée et viendra surtout de
  4chan.
* Les commentaires Stack Exchange contiennent du code et des citations, ce qui
  ajoute du bruit lexical (visible dans la diversité lexicale).
* 4chan est une archive : un fil disparaît au bout de quelques jours, la
  collecte n'est donc pas rejouable à l'identique, d'où l'importance des runs
  MLflow et des versions DVC.
