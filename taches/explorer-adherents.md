# Tâche : explorer la recherche et l'export des adhérents dans ADOC (lecture seule)

But : savoir comment un programme, avec la session du bot, peut obtenir la liste des adhérents de la saison
en cours qui ont une **adhésion padel**, avec nom, prénom et numéros de téléphone, pour répondre à
« telle personne (prénom, nom, téléphone, éventuellement partiels) est-elle adhérente padel ? ».

Règles :
- Lecture seule : aucune modification, aucun envoi de mail/SMS, aucun clic sur enregistrer / supprimer / valider.
- Ne saisis aucun identifiant ADOC/FFT et ne contourne aucun captcha.
- Ne modifie pas le dépôt ~/padel-bot (sauf le fichier de notes) et ne touche pas à session.json.
- AUCUNE donnée personnelle dans les notes : remplace noms, prénoms, téléphones, e-mails, adresses par "X".
  Supprime les réponses brutes et exports téléchargés une fois l'analyse terminée.

Étapes :
1. Script Python Playwright dans /tmp, exécuté avec ~/padel-bot/.venv/bin/python et lancé via
   flock -n /tmp/padel-bot.lock : Chromium headless, ignore_default_args=["--enable-automation"],
   args=["--disable-blink-features=AutomationControlled"], cookies de ~/.local/share/padel-bot/session.json.
   Vérifie la connexion sur https://adoc.app.fft.fr/adoc/accueil.do?method=read (lien contenant "logout").
2. Trouve dans le menu la gestion des adhérents (« Adhérents › Gestion », « adhérents en cours »...).
   Note l'URL, le formulaire de recherche (champs, valeurs possibles des listes déroulantes : saison/année
   d'adhésion, TYPE D'ADHÉSION / formule / activité), et comment les résultats arrivent (HTML, DWR, JSON),
   avec la pagination éventuelle.
3. Liste les libellés exacts des types d'adhésion existants et repère ceux qui concernent le PADEL
   (adhésion padel seule, tennis + padel, jeunes, etc.).
4. Fais une recherche « saison en cours + adhésion padel » si le filtre existe ; note le nombre de résultats
   et la requête exacte (méthode, URL, paramètres).
5. Repère le bouton « Exporter » : requête déclenchée, format du fichier (xls réel ou HTML/texte nommé .xls),
   feuilles et noms des colonnes (en particulier nom, prénom, téléphones, type d'adhésion, saison).
   Indique si le type d'adhésion figure dans l'export.
6. Regarde s'il existe un moyen plus direct (DWR, JSON) d'obtenir nom, prénom, téléphones et type d'adhésion.
7. Écris tout dans ~/padel-bot/resultats/padel-adherents-notes.md (sans aucune donnée personnelle) et affiche-le.
