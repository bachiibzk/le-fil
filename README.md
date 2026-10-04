# Le Fil — Journal du matin

Ton fil d'infos personnel (crypto, meme coins, marchés, tech, tendances), rédigé par Claude et installable sur n'importe quel téléphone depuis le navigateur. Pas d'App Store : une seule adresse pour tous tes téléphones.

## Ce que fait l'app

| Onglet | Contenu | Fraîcheur |
|---|---|---|
| 💬 Fil | Posts courts façon X, rédigés par Claude, avec leurs sources | Dès qu'une info nouvelle et pertinente tombe (vérification toutes les 10 min) |
| 📊 Marchés | Top 60 des meme coins (prix, 1 h, 24 h, 7 j, MC, volume), triable | En direct dans le téléphone, chaque minute |
| 🗞️ Journal | Le journal du matin complet (Essentiel, Marchés, Memes, Tendances, Tech), avec les 14 dernières éditions | Chaque matin vers 7h |
| ⚙️ Réglages | Liste de prix du bandeau, filtre d'importance, thème, notifications | Propre à chaque téléphone |

Le bandeau de prix en haut (BTC, ETH, SOL, DOGE, PEPE, PENGU par défaut) se met à jour en direct chaque minute.

## Comment marche le « en direct »

```
Toutes les 10 min (GitHub Actions, gratuit)
  1. bot/live.py lit les sources gratuites : flux RSS (CoinDesk, Cointelegraph, Decrypt, The Block,
     TechCrunch, The Verge, CNBC, Les Echos, Fed, BCE, SEC, Google Trends), prix CoinGecko,
     meme coins CoinGecko + CoinMarketCap, trending CoinGecko
  2. Il garde seulement le NOUVEAU (jamais vu) et le PERTINENT (mots-clés, gros mouvements)
  3. Rien de nouveau → aucun appel à Claude, coût nul
  4. Du nouveau → Claude juge et rédige 0 à N posts (souvent 0 : il ignore le bruit)
  5. Les posts sont ajoutés à data/feed.json, l'app les affiche dans la minute
```

Garde-fous de fiabilité (les mêmes règles que le journal) :

- Claude n'écrit qu'à partir des données collectées.
- Un post dont les sources ne viennent pas des données collectées est rejeté automatiquement.
- Un meme coin dont CoinGecko et CoinMarketCap donnent des variations de signe opposé est écarté.
- Les posts d'importance 3 déclenchent une notification.

## Installation (environ 15 minutes, depuis un ordinateur)

### 1. Créer le dépôt GitHub

1. Sur github.com : **New repository**, nom `le-fil`, visibilité **Public**. GitHub Pages gratuit exige un dépôt public ; les infos du fil seront donc visibles par qui a le lien.
2. Décompresse le zip, puis sur la page du dépôt : **uploading an existing file**. Glisse **tout le contenu** du dossier, y compris le dossier `.github`. Sur Mac, `Cmd+Maj+.` affiche les dossiers cachés. Termine avec **Commit changes**.

   Avec git, c'est plus simple : `git init && git add . && git commit -m "Le Fil" && git branch -M main && git remote add origin https://github.com/<toi>/le-fil.git && git push -u origin main`

### 2. Activer GitHub Pages

**Settings → Pages → Build and deployment → Source : GitHub Actions.**

### 3. Ajouter les clés

**Settings → Secrets and variables → Actions** :

| Type | Nom | Valeur |
|---|---|---|
| Secret (obligatoire) | `ANTHROPIC_API_KEY` | Ta clé API, à créer sur console.anthropic.com (avec une limite de dépense mensuelle conseillée) |
| Secret (optionnel) | `NTFY_TOPIC` | Un nom secret et difficile à deviner, ex. `lefil-alex-8f3k2q`, pour les notifications app fermée |
| Variable | `APP_URL` | L'adresse de l'app, ex. `https://<toi>.github.io/le-fil/` |
| Variable (optionnelle) | `LIVE_MODEL` | Modèle du fil (défaut : `claude-haiku-4-5`, rapide et économique) |
| Variable (optionnelle) | `JOURNAL_MODEL` | Modèle du journal (défaut : `claude-sonnet-4-5`) |

### 4. Démarrer

Onglet **Actions** → active les workflows si GitHub le demande, puis lance-les à la main (**Run workflow**) dans cet ordre :

1. **Publier l'app** : met l'app en ligne.
2. **Fil en direct** : le premier passage mémorise seulement les références, sans rien publier. Les passages suivants publient automatiquement.
3. **Journal du matin** (facultatif) : pour tester une édition tout de suite.

### 5. Installer sur chaque téléphone

Ouvre `https://<toi>.github.io/le-fil/` :

- **iPhone** : Safari → bouton Partager → **Sur l'écran d'accueil**
- **Android** : Chrome → menu ⋮ → **Installer l'application**

**Notifications app fermée** : installe l'app gratuite **ntfy** (iOS et Android), puis abonne-toi au sujet choisi dans `NTFY_TOPIC`. Tu recevras les posts importants et le journal du matin.

## Personnaliser

- **Sources, mots-clés, seuils d'alerte** : `bot/sources.json`. Par exemple, `memes.move_alert_pct` vaut 20 (alerte au-delà de ±20 % sur 24 h) et `markets.coins` fixe le seuil de mouvement par crypto.
- **Ton et règles des posts** : `bot/prompts/live.md`.
- **Contenu du journal** : `bot/prompts/journal.md`, qui reprend les consignes de la routine Cowork.
- **Fréquence** : la ligne `cron` de `.github/workflows/live.yml`. GitHub peut retarder les tâches planifiées de quelques minutes aux heures chargées.
- **Heure du journal** : `cron: "0 5 * * *"` dans `journal.yml` est en UTC (7h à Paris l'été, 6h l'hiver).

## Coûts

- GitHub Actions et Pages : gratuits pour un dépôt public.
- Prix en direct dans l'app : gratuits (API publique CoinGecko).
- API Anthropic : facturée à l'usage, sur ta clé. Le fil n'appelle Claude que lorsqu'il y a du nouveau ; le journal fait un gros appel par jour avec recherche web. Fixe une limite de dépense dans la console Anthropic et surveille la première semaine.

## Le journal Cowork existant

La routine Cowork actuelle continue de publier sur ta page claude.ai. `journal.yml` fait le même travail dans le dépôt. Garde les deux le temps de comparer la qualité, puis désactive celui que tu n'utilises plus pour éviter de payer deux fois.

## Structure

```
index.html, app.js, style.css   l'app (fil, marchés, réglages)
journal.html                    le lecteur du journal (repris de la page claude.ai)
manifest.webmanifest, sw.js     installation sur téléphone et mode hors ligne
data/feed.json                  posts du fil      (écrit par bot/live.py)
data/journal.json               éditions du jour  (écrit par bot/journal.py)
data/state.json                 mémoire du bot (déjà vu, références de prix)
bot/                            scripts Python + consignes données à Claude
.github/workflows/              live.yml (10 min), journal.yml (matin), pages.yml (publication)
```

Test local : `python3 -m http.server` puis http://localhost:8000. Pour tester le bot sans appeler Claude : `cd bot && DRY_RUN=1 python live.py`.

*Rien dans ce fil n'est un conseil d'investissement : les meme coins peuvent perdre la majorité de leur valeur en quelques heures.*
