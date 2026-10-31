# Bot padel – Annecy Tennis

Surveille les réservations « Joueur » des pistes de padel dans ADOC (J à J+7) et repère :

- les **annulations** : une réservation disparaît avant l'heure du créneau ;
- les **substitutions** : un créneau est annulé puis re-réservé avec au moins un joueur en commun et des noms différents ;
- les **modifications de joueurs** sur une réservation existante ;
- les **changements de mode de réservation** à joueurs identiques : ticket invitation (carnet) remplacé par l'adhésion padel ;

Le bot **signale**, il ne sanctionne pas : toute décision reste humaine. L'historique permanent (voir plus bas) sert à justifier les avertissements et sanctions éventuels.

## Niveaux d'alerte

Chaque cas reçoit un score et un niveau : faible, moyen ou élevé (score ≥ 7). Le score augmente quand :

| Signal | Points |
|---|---|
| Annulation puis re-réservation du même créneau, ou joueurs modifiés | base 3 |
| **Invité ou externe remplacé par un adhérent** (créneau pris à l'avance sans les vrais noms) | +4 (élevé d'office) |
| **Mêmes joueurs, mais réservation initiale avec un ticket invitation (carnet) refaite sur l'adhésion padel** (annulation + re-réservation, ou modification directe) | +4 (élevé d'office) |
| **Joueur noté externe (`*`, ticket invité) qui réapparaît comme adhérent** | +4 |
| Réservation initiale faite dès l'ouverture (J-7) | +2 |
| Invités ou externes dans la réservation initiale | +2 |
| L'adhérent ajouté avait déjà des réservations à venir quand le créneau a été pris (Ten'Up l'empêchait donc de réserver lui-même) | +2 |
| Nouvelle réservation faite après l'ouverture | +1 |
| Même adhérent retiré à plusieurs reprises | +1 |

### Fiche détaillée des réservations

Pour chaque nouvelle réservation, et après chaque modification, le bot lit la **fiche ADOC** de la réservation, en lecture seule. Elle indique, pour chaque joueur, **l'adhésion utilisée** (son numéro), s'il est **invité** et s'il a consommé un **ticket payant**. Cette fiche est conservée avec la réservation dans l'historique. Lors d'une annulation suivie d'une re-réservation, ou d'une modification, le bot compare les fiches :

| Constat sur les fiches | Points |
|---|---|
| Joueur invité avec ticket payant dans la réservation initiale, inscrit comme adhérent ensuite | +4 |
| Adhésion utilisée changée pour un même adhérent, par exemple carnet de tickets → adhésion padel | +3 |
| Moins de tickets payants qu'au départ | +2 |

Si la fiche n'est pas disponible, le bot se rabat sur l'indicateur « ticket » de la liste et sur les marqueurs `*`.

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
| Lancer un passage à la main (même pendant la pause) | `.venv/Scripts/python.exe padel_bot.py --forcer; echo $?` | `test-passage.cmd` |
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

**Durée de la session ADOC** : le serveur ADOC ferme une session restée environ 30 minutes sans activité, et la reconnexion automatique par la FFT est bloquée pour un navigateur piloté. Sous Linux, **le planning est entièrement dans cron** (`crontab -l` pour le voir, `crontab -e` pour le changer) : un relevé complet (`--releve`) toutes les 20 minutes de 7h à 1h et une seule fois la nuit à 3h30, et, jour et nuit, une simple visite de la page d'accueil ADOC (`--entretien`, sans navigateur, quelques Ko) toutes les 7 minutes plus 0 à 2 minutes tirées au hasard (5 à 9 minutes environ), qui garde la session vivante sans rythme trop régulier. Les relevés partent aussi avec 0 à 90 secondes de décalage aléatoire. Le rapport lit la crontab pour afficher le prochain relevé. Si la session est malgré tout perdue, `bot.log` indique sur quelle page la reconnexion a échoué, et le rapport passe en « session expirée ».

**Pause nocturne (Windows seulement)** : de minuit à 7h (réglable avec `PADEL_PAUSE`), le bot ne relève pas les réservations ; il continue seulement la visite d'entretien toutes les 10 minutes, pour ne pas devoir se reconnecter chaque matin. Cette visite se désactive avec `PADEL_PAUSE_KEEPALIVE=non`. Les changements faits pendant la nuit sont détectés au premier relevé du matin ; une annulation de nuit est alors datée entre le dernier relevé de la veille et celui du matin.

## Configuration

Les réglages sont facultatifs. Pour en changer, copier `.env.example` en `.env` et décommenter les lignes voulues :

```bash
cp .env.example .env
```

| Variable | Rôle | Défaut |
|---|---|---|
| `PADEL_OUT` | dossier des résultats (par exemple un dossier Google Drive) | `resultats/` dans le projet |
| `PADEL_HISTORY_YEARS` | conservation de l'historique permanent, en années | `3` |
| `PADEL_ALERTE_EMAIL` | adresse qui reçoit les alertes e-mail (voir « Alertes par e-mail ») | aucune |
| `PADEL_SMTP_PASSWORD` | mot de passe d'application Gmail du compte d'envoi | aucun |
| `PADEL_HEALTHCHECK_URL` | adresse de ping de la surveillance externe (healthchecks.io) | aucune |
| `PADEL_ALERTE_RAPPEL_H` | rappel tant que le problème dure, en heures | `6` |
| `PADEL_PAUSE` | (Windows) pause nocturne, sans aucun passage (`HH:MM-HH:MM`, peut chevaucher minuit ; `non` pour désactiver) | `00:00-07:00` |
| `PADEL_PAUSE_KEEPALIVE` | (Windows) visite d'entretien de la session pendant la pause nocturne | `oui` |
| `PADEL_CHANNEL` | navigateur sous Windows : `msedge` ou `chrome` (relancer `connexion-adoc.cmd` après un changement) | `msedge` |
| `PADEL_MAX_DETAILS` | fiches de réservation lues par passage | `60` |
| `PADEL_INTERVALLE` | (Windows) minutes entre deux relevés, à accorder avec le Planificateur | `30` |

Le fichier `.env` est propre à chaque machine et n'est jamais envoyé sur GitHub.

## Fichiers produits (dans `PADEL_OUT`, par défaut `resultats/`)

| Fichier | Contenu | Conservation |
|---|---|---|
| `padel-rapport.html` | **rapport lisible** : état du bot, chiffres clés, cas suspects, annulations, réservations, passages | réécrit à chaque passage |
| `padel-statut.json` | état du bot (dernier passage, prochain passage, session, cas suspects, historique), **sans aucun nom** | réécrit à chaque passage |
| `bot-log.txt` | journal technique (sans noms), plus récent en haut | 300 dernières lignes |
| `index.html` | renvoie vers le rapport (page d'accueil quand le dossier est servi en web) | créé une fois |
| `padel-cas-suspects.csv` | cas suspects récents | 90 jours |
| `padel-annulations.csv` | annulations récentes | 14 jours |
| `padel-passages.csv` | passages du bot | 7 jours |
| `padel-reservations.csv` / `.json` | liste brute des réservations de J à J+7 | état courant |
| `padel-journal.json` | données des vues ci-dessus | réécrit à chaque passage |
| `padel-historique-cas-suspects.csv` | **tous** les cas suspects depuis le début | historique permanent |
| `padel-historique-annulations.csv` | **toutes** les annulations depuis le début | historique permanent |
| `historique/padel-evenements-AAAA.jsonl` | journal infalsifiable de chaque événement | `PADEL_HISTORY_YEARS` ans |

Dans les CSV et le rapport, « (ticket) » après la piste indique une réservation faite avec un ticket invitation.

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

## Linux (mini-PC, serveur)

```bash
git clone https://github.com/fabien7474/padel-bot.git && cd padel-bot
./install-linux.sh             # Python, Playwright/Chromium ; tâches cron des relevés et de l'entretien de session
```

Le bot tourne en arrière-plan via cron, sans session ouverte. Les notifications passent par `notify-send`, et ne s'affichent que si une session graphique est ouverte.

**Alertes par e-mail** : le bot envoie un e-mail quand la session ADOC est perdue (avec la marche à suivre), quand les relevés ou les entretiens de session ne tournent plus à l'heure prévue, quand la tâche cron des relevés a disparu, quand un relevé échoue ou quand le bot plante. Un rappel part toutes les 6 heures tant que le problème dure, puis un e-mail « Rétabli ». Les e-mails ne contiennent aucun nom d'adhérent. Réglage dans `.env` (jamais sur GitHub) : `PADEL_ALERTE_EMAIL` et `PADEL_SMTP_PASSWORD`, un [mot de passe d'application Gmail](https://myaccount.google.com/apppasswords). Test : `.venv/bin/python padel_bot.py --test-alerte`. Ces contrôles tournent sur le Beelink : s'il est éteint, si Internet est coupé ou si la crontab est vidée en entier, c'est la **surveillance externe** qui prévient.

**Surveillance externe** : à chaque passage (toutes les 5 à 9 minutes), le bot envoie un signal de vie à un service comme [healthchecks.io](https://healthchecks.io) (gratuit). Si les signaux cessent pendant plus de 25 minutes environ, le service envoie lui-même un e-mail, puis un autre quand le bot repart. Un plantage du bot est signalé tout de suite. Réglage : créer un « check » (période 10 min, délai de grâce 15 min) et coller son adresse dans `.env` (`PADEL_HEALTHCHECK_URL`).

**Connexion ADOC** : sur le bureau du serveur (sur son écran ou par bureau à distance, y compris depuis un téléphone), double-cliquer sur **« Reconnecter le bot ADOC »** (créé par `install-linux.sh` ; sinon `./reconnexion-adoc.sh`). Une fenêtre Chromium normale s'ouvre : on s'y connecte jusqu'à l'accueil ADOC. Le bot détecte la connexion tout seul, ferme la fenêtre, puis fait un relevé de contrôle. Pendant ce temps, la tâche cron attend : elle ne peut pas fermer la fenêtre de connexion.

**Reprendre la session et l'historique d'une autre machine**, par exemple d'un portable Windows (Git Bash, depuis le portable) :

```bash
scp -r /c/work/github/padel-bot/resultats  utilisateur@serveur:~/padel-bot/
scp /c/Users/<moi>/AppData/Local/padel-bot/session.json  utilisateur@serveur:~/.local/share/padel-bot/
```

Arrêter le bot de l'ancienne machine **avant** la copie : sinon deux historiques divergent. La mémoire de travail du bot (les réservations en cours) repart de zéro, et les comparaisons reprennent dès le deuxième passage.

### Consulter le rapport depuis le portable ou le téléphone

Sur le serveur, une seule fois :

```bash
cd ~/padel-bot && ./publier-rapport.sh
```

Le dossier des résultats est alors servi par Tailscale, **uniquement aux appareils de votre réseau Tailscale** : rien n'est publié sur Internet, et le trafic est chiffré par Tailscale. Ça survit aux redémarrages ; `./publier-rapport.sh arret` le désactive.

- Portable ou téléphone : installer l'application Tailscale, se connecter avec le même compte, puis ouvrir `http://fab-beelink/` (le nom de la machine dans Tailscale). Sur le téléphone, « Ajouter à l'écran d'accueil ».
- La page se recharge toutes les 5 minutes. Le bloc **État du bot** donne : actif, en pause nocturne ou arrêté, dernier passage, dernier passage réussi, prochain passage, nombre de cas suspects, fiches lues, intégrité de l'historique et version.
- Si aucun passage n'a eu lieu à l'heure prévue (Beelink éteint, cron arrêté), la page affiche en rouge « Le bot ne tourne plus », même si elle est vieille.
- Le lien **Journal technique** (`bot-log.txt`, sans noms d'adhérents, plus récent en haut) montre chaque passage, y compris les entretiens de session qui échouent et les alertes envoyées.
- Les CSV restent téléchargeables depuis la même adresse (`http://fab-beelink/padel-historique-cas-suspects.csv`, etc.).

Pourquoi pas Dropbox : l'application mobile affiche mal les pages HTML (ni styles ni script), et les noms des adhérents seraient stockés chez un tiers. Dropbox reste une bonne cible pour la **sauvegarde** de l'historique.

## Structure

| Fichier | Rôle |
|---|---|
| `monitor.js` | lecture d'ADOC et détection, exécuté dans la page ADOC |
| `padel_bot.py` | navigateur, session, exports CSV/JSON, notifications, commandes `--login` et `--verifier` |
| `report.py` | rapport HTML autonome |
| `history.py` | historique permanent chaîné |
| `install-windows.ps1` | installation et tâche planifiée Windows |
| `install-linux.sh` | installation et tâche cron Linux |
| `publier-rapport.sh` | rapport consultable à distance via Tailscale |
| `reconnexion-adoc.sh` | reconnexion à ADOC (raccourci de bureau « Reconnecter le bot ADOC ») |
| `connexion-adoc.cmd`, `test-passage.cmd`, `mettre-a-jour.cmd` | raccourcis double-clic |
| `.env.example` | modèle de configuration |
