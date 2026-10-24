# Bot padel – Annecy Tennis

Surveille les réservations « Joueur » des pistes de padel dans ADOC (J à J+7) et repère :

- les **annulations** (réservation disparue avant l'heure du créneau) ;
- les **substitutions** : annulation puis re-réservation du même créneau avec au moins un joueur en commun et des noms différents ;
- les **modifications de joueurs** sur une réservation existante.

Chaque cas reçoit un niveau (faible / moyen / élevé), plus élevé si la réservation initiale a été faite dès l'ouverture (J-7), contenait des invités, ou si les mêmes noms sont retirés de façon répétée. Le bot **signale**, il ne sanctionne pas : toute décision reste humaine.

## Fichiers produits (dossier `PADEL_OUT`)

| Fichier | Contenu | Conservation |
|---|---|---|
| `padel-cas-suspects.csv` | cas suspects | 90 jours |
| `padel-annulations.csv` | annulations | 14 jours |
| `padel-passages.csv` | passages du bot | 7 jours |
| `padel-reservations.csv` / `.json` | liste brute des réservations J à J+7 | état courant |
| `padel-journal.json` | tout le journal | — |

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

Les fichiers contiennent des noms d'adhérents : ne pas les publier, ne pas les mettre dans ce dépôt (le `.gitignore` les exclut). Durées de conservation limitées dans `monitor.js`. Traitement à mentionner au registre du club et dans le règlement intérieur.

## Structure

- `monitor.js` : lecture d'ADOC et détection (exécuté dans la page ADOC) ;
- `padel_bot.py` : lancement du navigateur, session, export CSV/JSON, notifications.
