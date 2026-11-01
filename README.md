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

## Installation (Beelink, Linux)

Le bot tourne uniquement sous Linux, sur le Beelink.

```bash
git clone https://github.com/fabien7474/padel-bot.git && cd padel-bot
./install-linux.sh             # Python, Playwright/Chromium ; tâches cron des relevés et de l'entretien de session
```

L'installateur crée l'environnement Python `.venv`, installe Playwright et son Chromium, écrit les tâches cron, installe la commande `padel` dans `~/.local/bin` et le raccourci de bureau « Reconnecter le bot ADOC ». Il peut être relancé sans risque, par exemple pour revenir au planning par défaut.

## Connexion et captcha

Le bot ne stocke **aucun mot de passe**.

- `padel reconnecter` (ou `./reconnexion-adoc.sh`, ou le raccourci de bureau) ouvre un **Chromium normal**, non piloté, que la page de connexion FFT accepte. On s'y connecte soi-même, captcha compris, jusqu'à l'accueil ADOC. Le bot récupère alors la session.
- La session (profil du navigateur et cookies) est gardée dans `~/.local/share/padel-bot`, en dehors du projet.
- Quand la **session ADOC** expire, le bot la rouvre seul grâce à la connexion FFT, sans captcha.
- Quand la **connexion FFT** expire, le bot ne tente pas de passer le captcha. Il envoie une alerte (e-mail, notification de bureau), se termine avec le code `2`, et reprend dès qu'on s'est reconnecté.

**Durée de la session ADOC** : le serveur ADOC ferme une session restée environ 30 minutes sans activité, et la reconnexion automatique par la FFT est bloquée pour un navigateur piloté. **Le planning est entièrement dans cron** (`crontab -l` pour le voir, `crontab -e` pour le changer) : un relevé complet (`--releve`) toutes les 20 minutes de 7h à 1h et une seule fois la nuit à 3h30, et, jour et nuit, une simple visite de la page d'accueil ADOC (`--entretien`, sans navigateur, quelques Ko) toutes les 7 minutes plus 0 à 2 minutes tirées au hasard (5 à 9 minutes environ), qui garde la session vivante sans rythme trop régulier. Les relevés partent aussi avec 0 à 90 secondes de décalage aléatoire. Le rapport lit la crontab pour afficher le prochain relevé. Si la session est malgré tout perdue, `bot.log` indique sur quelle page la reconnexion a échoué, et le rapport passe en « session expirée ».

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
| `PADEL_MAX_DETAILS` | fiches de réservation lues par passage | `60` |

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

## Utilisation au quotidien

Le bot tourne en arrière-plan via cron, sans session ouverte. Les notifications passent par `notify-send`, et ne s'affichent que si une session graphique est ouverte.

**Commande `padel`** (installée par `install-linux.sh` dans `~/.local/bin`) : les opérations courantes, depuis n'importe quel dossier. `padel` seul affiche l'aide.

| Commande | Rôle |
|---|---|
| `padel statut` | état du bot : connexion ADOC, derniers relevés, dernier contact ADOC, prochain relevé, planning, alertes en cours, e-mail et surveillance externe configurés |
| `padel reconnecter` | se reconnecter à ADOC (depuis le bureau du Beelink, sur place ou par bureau à distance) |
| `padel releve` | relevé immédiat (attend la fin d'un passage en cours) |
| `padel entretien` | visite d'entretien de la session ADOC |
| `padel cas [-j JOURS]` | cas suspects détaillés (7 derniers jours par défaut, 90 au plus) |
| `padel annulations [-j JOURS]` | annulations (7 jours par défaut, 14 au plus) |
| `padel reservations [JOUR]` | réservations suivies : aujourd'hui par défaut, `demain`, `tout`, `AAAA-MM-JJ` ou `JJ/MM` |
| `padel membre TERMES [--frais]` | la personne est-elle adhérente padel cette saison ? Prénom, nom et/ou téléphone, même partiels (`padel membre Jean 06 12 34 56 78`, `padel membre dupont`, `padel membre 5678`) ; tolère une faute de frappe. Sans terme : nombre d'adhérents et offres retenues. `--frais` relit d'abord la liste dans ADOC (~30 s) |
| `padel planning` | planning cron et prochains relevés |
| `padel journal [-n N] [-f]` | journal technique, erreurs en rouge (`-f` : suivre en direct) |
| `padel rapport` | ouvre le rapport HTML |
| `padel alerte-test` | envoie un e-mail de test |
| `padel verifier` | intégrité de l'historique permanent |
| `padel maj` | mise à jour du bot (`git pull` + dépendances) |

Le planning se change avec `crontab -e` (ou en relançant `./install-linux.sh` pour revenir au planning par défaut).

**Liste des adhérents padel** (`padel membre`) : cron relit la liste dans ADOC à 3h45 et 13h45 (`padel_bot.py --adherents`, sans navigateur, environ 30 s) : recherche sur l'année d'adhésion la plus récente et les offres padel (les 9 offres indiquées par le club, plus les autres offres dont le libellé parle de padel, sauf les invitations, signalées « hors liste du club »), puis export Excel d'ADOC. La recherche dans cette copie est instantanée ; si la copie a plus de 36 heures, `padel membre` la relit d'abord. Cette copie contient des **données personnelles** (nom, prénom, téléphones, offres) : elle est rangée dans `~/.local/share/padel-bot/adherents.json`, lisible par le seul utilisateur, jamais dans `resultats/` (publié), dans `bot.log` ni sur GitHub. La liste des offres du club est dans `adherents.py` (`OFFRES_CLUB`).

Attention à `crontab <fichier>` : la commande **remplace** toute la crontab par le contenu du fichier, et un fichier vide efface les tâches du bot. Pour sauvegarder puis restaurer : `crontab -l > ~/cron.bak` puis `crontab ~/cron.bak`, après avoir vérifié que `~/cron.bak` n'est pas vide.

**Alertes par e-mail** : le bot envoie un e-mail quand la session ADOC est perdue (avec la marche à suivre), quand les relevés ou les entretiens de session ne tournent plus à l'heure prévue, quand la tâche cron des relevés a disparu, quand un relevé échoue ou quand le bot plante. Un rappel part toutes les 6 heures tant que le problème dure, puis un e-mail « Rétabli ». Les e-mails ne contiennent aucun nom d'adhérent. Réglage dans `.env` (jamais sur GitHub) : `PADEL_ALERTE_EMAIL` et `PADEL_SMTP_PASSWORD`, un [mot de passe d'application Gmail](https://myaccount.google.com/apppasswords). Test : `.venv/bin/python padel_bot.py --test-alerte`. Ces contrôles tournent sur le Beelink : s'il est éteint, si Internet est coupé ou si la crontab est vidée en entier, c'est la **surveillance externe** qui prévient.

**Surveillance externe** : à chaque passage (toutes les 5 à 9 minutes), le bot envoie un signal de vie à un service comme [healthchecks.io](https://healthchecks.io) (gratuit). Si les signaux cessent pendant plus de 25 minutes environ, le service envoie lui-même un e-mail, puis un autre quand le bot repart. Un plantage du bot est signalé tout de suite. Réglage : créer un « check » (période 10 min, délai de grâce 15 min) et coller son adresse dans `.env` (`PADEL_HEALTHCHECK_URL`).

**Connexion ADOC** : sur le bureau du serveur (sur son écran ou par bureau à distance, y compris depuis un téléphone), double-cliquer sur **« Reconnecter le bot ADOC »** (créé par `install-linux.sh` ; sinon `./reconnexion-adoc.sh`). Une fenêtre Chromium normale s'ouvre : on s'y connecte jusqu'à l'accueil ADOC. Le bot détecte la connexion tout seul, ferme la fenêtre, puis fait un relevé de contrôle. Pendant ce temps, la tâche cron attend : elle ne peut pas fermer la fenêtre de connexion.

### Consulter le rapport depuis le portable ou le téléphone

Sur le serveur, une seule fois :

```bash
cd ~/padel-bot && ./publier-rapport.sh
```

Le dossier des résultats est alors servi par Tailscale, **uniquement aux appareils de votre réseau Tailscale** : rien n'est publié sur Internet, et le trafic est chiffré par Tailscale. Ça survit aux redémarrages ; `./publier-rapport.sh arret` le désactive.

- Portable ou téléphone : installer l'application Tailscale, se connecter avec le même compte, puis ouvrir `http://fab-beelink/` (le nom de la machine dans Tailscale). Sur le téléphone, « Ajouter à l'écran d'accueil ».
- La page se recharge toutes les 5 minutes. Le bloc **État du bot** donne : actif ou arrêté, dernier passage, dernier passage réussi, prochain relevé, planning des relevés lu dans cron, nombre de cas suspects, fiches lues, intégrité de l'historique et version.
- Si aucun passage n'a eu lieu à l'heure prévue (Beelink éteint, cron arrêté), la page affiche en rouge « Le bot ne tourne plus », même si elle est vieille.
- Le lien **Journal technique** (`bot-log.txt`, sans noms d'adhérents, plus récent en haut) montre chaque passage, y compris les entretiens de session qui échouent et les alertes envoyées.
- Les CSV restent téléchargeables depuis la même adresse (`http://fab-beelink/padel-historique-cas-suspects.csv`, etc.).

Pourquoi pas Dropbox : l'application mobile affiche mal les pages HTML (ni styles ni script), et les noms des adhérents seraient stockés chez un tiers. Dropbox reste une bonne cible pour la **sauvegarde** de l'historique.

### Demander les disponibilités à Claude (même à la voix)

Le connecteur `padel_mcp.py` permet de demander à Claude, depuis l'application (iPhone compris, aussi en mode vocal) :
« Quelles pistes de padel sont libres mercredi à 18h45 ? », « Quels créneaux libres demain ? », « Est-ce que le bot padel tourne ? »,
« Est-ce que le 06 12 34 56 78 est adhérent padel ? », « Jean Dupont est-il adhérent ? ».

- Il lit **en direct** le « Tableau de réservation » d'ADOC avec la session du bot (navigateur séparé, environ 5 secondes par question).
- Il ne renvoie que des pistes, des horaires et des types d'occupation (réservé, en ligne, cours, entretien, tournoi) : **aucun nom ni e-mail**.
- Les 5 pistes (Padel 1 à 5) ont des créneaux de 1h15, de 7h30 à 22h30.
- **Adhérents** (outil `padel_adherent`, copie locale de `padel membre`) : il faut un numéro d'au moins 8 chiffres, le prénom et le nom, ou un nom de famille d'au moins 4 lettres. La réponse se limite au **prénom, au nom et à l'offre padel** des personnes trouvées (5 au plus) : jamais de téléphone ni d'e-mail, et pas de liste complète. `bot.log` note seulement le type de recherche et le nombre de résultats. Ces réponses passent par Claude, comme toute conversation.

Installation sur le Beelink :

```bash
cd ~/padel-bot && git pull
./install-mcp.sh
```

Le script installe un service permanent (`systemctl --user status padel-mcp`), crée une clé secrète dans `.env` et ouvre l'accès HTTPS par **Tailscale Funnel**. Au premier lancement, Tailscale peut afficher un lien pour autoriser Funnel sur votre réseau. À la fin, il affiche l'adresse `https://fab-beelink.….ts.net/<clé>/mcp`.

Dans Claude (sur claude.ai, depuis un ordinateur) : **Customize → Connectors → + Add → custom connector**. Donnez un nom (« Padel »), collez l'adresse et choisissez **No sign in** (la clé est dans l'adresse). Dans une conversation, activez-le avec **+ → Connectors**. L'adresse vaut mot de passe : ne la partagez pas. Pour changer la clé, supprimez la ligne `PADEL_MCP_TOKEN` de `.env` et relancez `./install-mcp.sh`. `./install-mcp.sh arret` coupe tout.

Test sans Claude : `.venv/bin/python dispo.py mercredi 18h45`.

### Après un redémarrage du Beelink

Tout repart seul : cron (relevés et entretien de session), le connecteur Claude (service systemd utilisateur, actif sans ouvrir de session grâce à `loginctl enable-linger`), Tailscale, la publication du rapport et Funnel. Pour le vérifier :

```bash
cd ~/padel-bot && ./verifier-beelink.sh
```

Seule la **session ADOC** peut ne pas survivre : si le Beelink est resté éteint plus d'une demi-heure environ, ADOC l'a fermée. Le rapport passe alors en « session expirée » et il faut lancer `padel reconnecter` sur le bureau du Beelink, sur place ou par bureau à distance.

## Structure

| Fichier | Rôle |
|---|---|
| `monitor.js` | lecture d'ADOC et détection, exécuté dans la page ADOC |
| `padel_bot.py` | navigateur, session, exports CSV/JSON, notifications, commandes `--login` et `--verifier` |
| `report.py` | rapport HTML autonome |
| `history.py` | historique permanent chaîné |
| `install-linux.sh` | installation, tâches cron et commande `padel` |
| `padel`, `padel_cli.py` | commande `padel` |
| `adherents.py` | liste des adhérents padel (export ADOC) et recherche `padel membre` |
| `publier-rapport.sh` | rapport consultable à distance via Tailscale |
| `dispo.py`, `padel_mcp.py`, `install-mcp.sh` | disponibilités des pistes en direct et connecteur Claude |
| `verifier-beelink.sh` | contrôle après redémarrage : services, cron, Tailscale, état du bot |
| `reconnexion-adoc.sh` | reconnexion à ADOC (raccourci de bureau « Reconnecter le bot ADOC ») |
| `.env.example` | modèle de configuration |
