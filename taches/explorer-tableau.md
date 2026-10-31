# Tâche : explorer la page « tableau de réservation » d'ADOC (lecture seule)

But : savoir comment la page ADOC « tableau de réservation » (planning des courts) charge ses données,
pour qu'un programme puisse dire quelles pistes de PADEL sont libres à une date et une heure données.

Règles :
- Lecture seule : aucune réservation, aucun clic sur réserver / modifier / supprimer / valider.
- Ne saisis aucun identifiant ADOC/FFT et ne contourne aucun captcha.
- Ne modifie pas le dépôt ~/padel-bot (sauf ce fichier de notes) et ne touche pas à session.json.
- Aucun nom d'adhérent dans les notes : remplace tout nom par "X".

Étapes :
1. Écris un script Python Playwright dans /tmp (pas dans le dépôt), exécuté avec ~/padel-bot/.venv/bin/python :
   Chromium headless avec ignore_default_args=["--enable-automation"] et
   args=["--disable-blink-features=AutomationControlled"], cookies chargés depuis
   ~/.local/share/padel-bot/session.json (context.add_cookies). Ouvre
   https://adoc.app.fft.fr/adoc/accueil.do?method=read et vérifie la connexion (lien contenant "logout").
   Si non connecté : arrête-toi et dis-le.
   Lance-le avec : flock -n /tmp/padel-bot.lock <commande>  (pour ne pas gêner un passage du bot).
2. Trouve le lien du menu vers le « tableau de réservation » / planning, ouvre-le, et enregistre toutes les
   requêtes réseau (URL, méthode, paramètres POST, type de réponse : HTML, JSON, DWR...).
3. Change de date dans le tableau via l'interface et note la requête déclenchée et ses paramètres.
4. Décris : la liste exacte des pistes (noms ; lesquelles sont du padel), l'heure d'ouverture et de fermeture,
   la durée d'un créneau, et comment distinguer dans la réponse une case libre d'une case occupée
   (classes CSS, attributs, champs JSON), y compris le type de l'occupation (joueur, cours, blocage...).
   Donne un extrait de réponse ANONYMISÉ.
5. Écris tout cela dans ~/padel-tableau-notes.md et affiche le fichier.
