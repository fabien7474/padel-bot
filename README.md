# Bot padel – Annecy Tennis

Surveille les réservations « Joueur » des pistes de padel dans ADOC (J à J+7) et repère :

- les **annulations** : une réservation disparaît avant l'heure du créneau ;
- les **substitutions** : un créneau est annulé puis re-réservé avec au moins un joueur en commun et des noms différents ;
- les **modifications de joueurs** sur une réservation existante ;
- les **réservations simultanées** au-delà du maximum autorisé.

Le bot **signale**, il ne sanctionne pas : toute décision reste humaine. L'historique permanent (voir plus bas) sert à justifier les avertissements et sanctions éventuels.

## Niveaux d'alerte

Chaque cas reçoit un score et un niveau : faible, moyen ou élevé (score ≥ 7). Le score augmente quand :

| Signal | Points |
|---|---|
| Annulation puis re-réservation du même créneau, ou joueurs modifiés | base 3 |
| **Invité ou externe remplacé par un adhérent** (créneau pris à l'avance sans les vrais noms) | +4 (élevé d'office) |
| Réservation initiale faite dès l'ouverture (J-7) | +2 |
| Invités ou externes dans la réservation initiale | +2 |
| L'adhérent ajouté avait déjà des réservations à venir quand le créneau a été pris | +2 |
| Nouvelle réservation faite après l'ouverture | +1 |
| Même adhérent retiré à plusieurs reprises | +1 |

Un adhérent présent dans **plus de `PADEL_MAX_SIMULT` réservations à venir** (2 par défaut) déclenche aussi un cas élevé. Le bot ne connaît pas le type d'adhésion de chacun : pour un adhérent limité à 1 réservation, il faut vérifier dans ADOC.

## Installation (Windows, Git Bash)

Prérequis : Git, et Edge, qui est déjà installé sous Windows. L'installateur installe Python s'il manque.

```bash
cd /c/work/github
git clone https://github.com/fabien7474/padel-bot.git
cd padel-bot
powershell.exe -ExecutionPolicy Bypass -File ./install-windows.ps1 -Minutes 30
```

L'installateur :

1. crée l'environnement Python `.venv` et installe Playwright, qui utilise Edge sans rien télécharger d'autre ;
2. crée ou met à jour la tâche planifiée **« Bot padel ADOC »**, qui tourne toutes les `-Minutes` minutes (10 par défaut) ;
3. ouvre Edge pour la **connexion à ADOC**, sauf si une session est déjà enregistrée.

Il peut être relancé sans risque, par exemple pour changer la fréquence ou après avoir déplacé le dossier : la tâche est alors remise à jour.

## Utilisation au quotidien

| Action | Commande (Git Bash, dans le dossier du projet) | ou double-clic |
|---|---|---|
| Mettre à jour le bot | `git pull` | `mettre-a-jour.cmd` (`git pull` + dépendances) |
| Lancer un passage à la main | `.venv/Scripts/python.exe padel_bot.py; echo $?` | `test-passage.cmd` |
| Se reconnecter à ADOC | `.venv/Scripts/python.exe padel_bot.py --login` | `connexion-adoc.cmd` |
| Vérifier l'intégrité de l'historique | `.venv/Scripts/python.exe padel_bot.py --verifier` | — |
| Voir le journal technique | `tail -20 bot.log` | ouvrir `bot.log` |

Si une mise à jour ajoute une dépendance, lancer aussi `.venv/Scripts/python.exe -m pip install -r requirements.txt`. `mettre-a-jour.cmd` le fait automatiquement.

Codes retour, visibles dans le Planificateur de tâches comme « Résultat de la dernière exécution » :

| Code | Signification | Que faire |
|---|---|---|
| `0x0` | passage réussi | rien |
| `0x2` | session ADOC/FFT expirée | lancer `connexion-adoc.cmd` |
| `0x1` | erreur technique | lire `bot.log` |

## Connexion et captcha

Le bot ne stocke **aucun mot de passe**.

- `connexion-adoc.cmd` ouvre un **Edge normal**, non piloté, que la page de connexion FFT accepte. On s'y connecte soi-même, captcha compris, jusqu'à l'accueil ADOC, puis on appuie sur Entrée dans la console. Le bot récupère alors la session.
- La session (profil Edge et cookies) est gardée dans `%LOCALAPPDATA%\padel-bot`, ou `~/.local/share/padel-bot` sous Linux, en dehors du projet et de tout dossier synchronisé.
- Quand la **session ADOC** expire, le bot la rouvre seul grâce à la connexion FFT, sans captcha.
- Quand la **connexion FFT** expire, le bot ne tente pas de passer le captcha. Il affiche **une** notification Windows, enregistre l'échec avec le code `0x2`, et reprend dès qu'on s'est reconnecté.

Une fréquence de 15 à 30 minutes maintient les sessions actives plus longtemps.

## Configuration

Les réglages sont facultatifs. Pour en changer, copier `.env.example` en `.env` et décommenter les lignes voulues :

```bash
cp .env.example .env
```

| Variable | Rôle | Défaut |
|---|---|---|
| `PADEL_OUT` | dossier des résultats (par exemple un dossier Google Drive) | `resultats/` dans le projet |
| `PADEL_MAX_SIMULT` | réservations à venir simultanées autorisées par adhérent | `2` |
| `PADEL_HISTORY_YEARS` | conservation de l'historique permanent, en années | `3` |

Le fichier `.env` est propre à chaque machine et n'est jamais envoyé sur GitHub.

## Fichiers produits (dans `PADEL_OUT`, par défaut `resultats/`)

| Fichier | Contenu | Conservation |
|---|---|---|
| `padel-rapport.html` | **rapport lisible** : état, chiffres clés, cas suspects, annulations, réservations, passages | réécrit à chaque passage |
| `padel-cas-suspects.csv` | cas suspects récents | 90 jours |
| `padel-annulations.csv` | annulations récentes | 14 jours |
| `padel-passages.csv` | passages du bot | 7 jours |
| `padel-reservations.csv` / `.json` | liste brute des réservations de J à J+7 | état courant |
| `padel-journal.json` | données des vues ci-dessus | réécrit à chaque passage |
| `padel-historique-cas-suspects.csv` | **tous** les cas suspects depuis le début | historique permanent |
| `padel-historique-annulations.csv` | **toutes** les annulations depuis le début | historique permanent |
| `historique/padel-evenements-AAAA.jsonl` | journal infalsifiable de chaque événement | `PADEL_HISTORY_YEARS` ans |

Les CSV utilisent le séparateur `;` et sont encodés en UTF-8 avec BOM : ils s'ouvrent directement dans Excel.

## Historique permanent (justification des avertissements)

Les fichiers « récents » sont des vues glissantes. Pour pouvoir justifier un avertissement ou une sanction, chaque événement (réservation créée, annulée, joueurs modifiés, cas suspect, période d'échec du bot) est aussi **ajouté, sans jamais être réécrit**, dans `historique/padel-evenements-AAAA.jsonl` :

- une ligne par événement, avec l'heure du constat et l'état exact de la réservation (piste, horaire, joueurs) avant et après ;
- chaque ligne contient l'**empreinte SHA-256** de la précédente : la moindre modification ou suppression casse la chaîne ;
- `padel_bot.py --verifier` affiche « INTACT » ou indique la ligne altérée ;
- les CSV `padel-historique-*.csv` sont régénérés à partir de ce journal et portent l'empreinte de chaque ligne.

Le bot constate ce qu'il voit à chaque passage. Une annulation est donc datée entre deux passages : « vue au passage de … , absente au passage de … ».

Pour sauvegarder l'historique, copier régulièrement `resultats/historique/` ailleurs, ou faire pointer `PADEL_OUT` vers un dossier synchronisé.

## Données personnelles (RGPD)

Les résultats contiennent des noms d'adhérents.

- Ils ne doivent jamais être publiés. Le dépôt est public, et le `.gitignore` exclut `resultats/`, `historique/`, les CSV, JSON et JSONL, le `.env` et les journaux.
- Les vues récentes sont conservées 7, 14 ou 90 jours (durées définies dans `monitor.js`). L'historique permanent est conservé `PADEL_HISTORY_YEARS` ans, puis supprimé année par année.
- Le bureau doit fixer cette durée en fonction de la finalité (justification des avertissements et sanctions), l'inscrire au **registre des traitements** et annoncer ce contrôle dans le **règlement intérieur**.

## Linux (mini-PC)

```bash
git clone https://github.com/fabien7474/padel-bot.git && cd padel-bot
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt && playwright install --with-deps chromium
python padel_bot.py --login        # nécessite un écran la première fois
( crontab -l; echo "*/30 * * * * cd $PWD && .venv/bin/python padel_bot.py" ) | crontab -
```

Sous Linux, le bot utilise le Chromium de Playwright, et les notifications passent par `notify-send`.

## Structure

| Fichier | Rôle |
|---|---|
| `monitor.js` | lecture d'ADOC et détection, exécuté dans la page ADOC |
| `padel_bot.py` | navigateur, session, exports CSV/JSON, notifications, commandes `--login` et `--verifier` |
| `report.py` | rapport HTML autonome |
| `history.py` | historique permanent chaîné |
| `install-windows.ps1` | installation et tâche planifiée Windows |
| `connexion-adoc.cmd`, `test-passage.cmd`, `mettre-a-jour.cmd` | raccourcis double-clic |
| `.env.example` | modèle de configuration |
