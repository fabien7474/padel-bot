# Bot padel – Annecy Tennis

Surveille les réservations « Joueur » des pistes de padel dans ADOC (J à J+7) et repère :

- les **annulations** (réservation disparue avant l'heure du créneau) ;
- les **substitutions** : annulation puis re-réservation du même créneau avec au moins un joueur en commun et des noms différents ;
- les **modifications de joueurs** sur une réservation existante.

Chaque cas reçoit un niveau (faible / moyen / élevé), plus élevé si la réservation initiale a été faite dès l'ouverture (J-7), contenait des invités, ou si les mêmes noms sont retirés de façon répétée.

Sont classés **élevé** d'office :
- un **invité remplacé par un adhérent** (créneau pris à l'avance sans les vrais noms) ;
- un adhérent présent dans **plus de réservations à venir que le maximum autorisé** (`PADEL_MAX_SIMULT`, 2 par défaut, dans `.env`). Le bot ne connaît pas le type d'adhésion de chacun : à vérifier dans ADOC pour les adhérents limités à 1.

Lors d'une substitution, le bot précise aussi si l'adhérent ajouté avait déjà des réservations à venir au moment où le créneau a été pris. Le bot **signale**, il ne sanctionne pas : toute décision reste humaine.

## Fichiers produits (dossier `PADEL_OUT`)

| Fichier | Contenu | Conservation |
|---|---|---|
| `padel-cas-suspects.csv` | cas suspects | 90 jours |
| `padel-annulations.csv` | annulations | 14 jours |
| `padel-passages.csv` | passages du bot | 7 jours |
| `padel-reservations.csv` / `.json` | liste brute des réservations J à J+7 | état courant |
| `padel-journal.json` | tout le journal | — |
| `padel-rapport.html` | rapport lisible (double-clic pour l'ouvrir) | — |
| `padel-historique-cas-suspects.csv` | **tous** les cas suspects depuis le début | historique permanent |
| `padel-historique-annulations.csv` | **toutes** les annulations depuis le début | historique permanent |
| `historique/padel-evenements-AAAA.jsonl` | journal infalsifiable de chaque événement (création, annulation, modification, cas suspect) | `PADEL_HISTORY_YEARS` ans (3 par défaut) |

## Historique permanent (justification des avertissements)

Les fichiers ci-dessus « courants » sont des vues glissantes. Pour pouvoir justifier un avertissement ou une sanction, chaque événement est aussi **ajouté** (jamais réécrit) dans `historique/padel-evenements-AAAA.jsonl` :

- une ligne par événement, avec l'heure du constat et l'état exact de la réservation (piste, horaire, joueurs) avant et après ;
- chaque ligne contient l'**empreinte SHA-256** de la précédente : toute modification ou suppression casse la chaîne ;
- `python padel_bot.py --verifier` contrôle l'intégrité et affiche « INTACT » ou la ligne altérée ;
- les CSV `padel-historique-*.csv` sont régénérés à partir de ce journal et portent l'empreinte de chaque ligne.

Le bot constate ce qu'il voit à chaque passage : une annulation est datée entre deux passages (« vue à … , absente à … »).

CSV séparés par `;`, UTF-8 avec BOM : ils s'ouvrent directement dans Excel.

## Installation

**Windows** (utilise Edge) : clic droit sur `install-windows.ps1` › *Exécuter avec PowerShell*. Le script installe Python et Playwright, demande le dossier de sortie, crée la tâche planifiée « Bot padel ADOC » (toutes les 10 min) et ouvre Edge pour la connexion ADOC.

**Linux / mini-PC** :

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt && playwright install --with-deps chromium
echo "PADEL_OUT=$HOME/padel-resultats" > .env
python padel_bot.py --login        # nécessite un écran la première fois
# toutes les 10 minutes :
( crontab -l; echo "*/10 * * * * cd $PWD && .venv/bin/python padel_bot.py" ) | crontab -
```

## Connexion

Le bot ne stocke **aucun mot de passe**. `python padel_bot.py --login` ouvre un navigateur : on se connecte à ADOC une fois, la session est gardée dans un profil dédié (`%LOCALAPPDATA%\padel-bot` ou `~/.local/share/padel-bot`, hors de tout dossier synchronisé). Si la session FFT expire, le bot affiche une notification ; il suffit de relancer `--login`.

## Données personnelles (RGPD)

Les fichiers contiennent des noms d'adhérents : ne pas les publier, ne pas les mettre dans ce dépôt (le `.gitignore` les exclut). Vues courantes : durées limitées dans `monitor.js`. Historique permanent : `PADEL_HISTORY_YEARS` ans (3 par défaut), durée à fixer par le bureau (finalité : justification des avertissements et sanctions) et à inscrire au registre des traitements et dans le règlement intérieur.

## Structure

- `monitor.js` : lecture d'ADOC et détection (exécuté dans la page ADOC) ;
- `padel_bot.py` : lancement du navigateur, session, export CSV/JSON, notifications ;
- `report.py` : rapport HTML autonome ;
- `history.py` : historique permanent chaîné.
