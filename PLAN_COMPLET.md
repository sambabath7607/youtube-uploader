# PLAN COMPLET — YouTube Uploader (Batch Code IA)

Rédigé le 13 novembre 2026, à partir du code réel (lecture seule) de trois projets :
le service `Nouveau dossier\src` (api.batchcodeia.com), la fabrication Remotion `Bureau\video-batchcodeia`,
et le site vitrine `Bureau\batch-code-ia`. **Rien n'est construit tant que ce document n'est pas validé par Samba.**

**But** : le client demande une vidéo à son agent IA (Claude, ChatGPT…, même sur téléphone) → le script, la voix et la
vidéo sont fabriqués **sur nos serveurs** → la vidéo arrive sur **sa** chaîne YouTube en quelques minutes.
Il n'installe rien, son ordinateur ne calcule rien.

Légende : 🟢 = solution retenue (la plus rapide pour le client) · ⚪ = écartée · **Claude** = code · **Samba** = comptes,
clés, démarches, commandes sur le serveur (tapées par lui-même, une par une).

---

## 1. Où on en est (preuves dans le code)

| Sujet | Aujourd'hui | Preuve |
|---|---|---|
| Voix | ✅ sur Modal (GPU T4, 10 en parallèle) : 352 mots en 91 s | `voix_modal/service.py` (`lire_parallele`), `youtube_uploader/voix.py` |
| Rendu vidéo | ❌ sur l'ordinateur du client (4 à 5 fois la durée de la vidéo) | `mcp_server.py:317-321`, `CLAUDE.md:130`, `guide_claude.html:45-48, 78-82, 103-141` |
| Transfert | ❌ du PC vers le serveur par `curl` (adresse de dépôt) | `preparer_envoi` (`mcp_server.py:343-366`), `youtube_uploader/depot.py` |
| Envoi YouTube | ✅ par le worker du serveur, par morceaux (`resumable=True`) | `youtube_uploader/envois.py`, `upload.py:30`, commande `traiter_envois` |
| Modèles de vidéos | ❌ chaque vidéo est codée à la main (TSX) | `video-batchcodeia/src/Root.tsx` (compositions propres à Samba) |
| `envoyer_video` (lien public) | ⚠️ bug noté au journal le 31/10 (« bytes-like object… »), jamais marqué corrigé | `video-batchcodeia/JOURNAL.md` |
| Courriel à l'inscription | ❌ non demandé (formulaire Django par défaut : nom + mot de passe) | `accounts/forms.py` |
| Mot de passe oublié | ❌ absent | `accounts/urls.py` |
| Contact / support | ❌ seulement un courriel personnel dans les pages légales | `conditions.html:71`, `confidentialite.html:12,80` |
| Offres / paiement dans le service | ❌ ; seul un quota de voix réglable à la main (`quota_secondes`) | `youtube_uploader/models.py` |
| Site vitrine | Stripe branché (commandes, abonnements, factures, taxes) ; plan « Créateur » 19 $/mois lié au produit ; produit en statut **« Disponible »** ; **aucun pont** vers le service | `billing/services.py:193` (`apply_stripe_subscription`), `core/management/commands/seed_plateforme.py:46,157` |
| Google | Application non vérifiée : avertissement, 100 utilisateurs à vie | `DEMARCHES_GOOGLE.md` |
| Sauvegardes | ✅ quotidiennes, mais **sur le même serveur** (`~/sauvegardes_youtube`) | `envois.py` (`sauvegarder_base`) |
| Surveillance | ❌ aucune alerte (panne du worker, de Modal, coûts) | — |
| Tests | 120 OK (9 sautés sans le paquet `mcp`) | `JOURNAL.md` |

---

## 2. Le nouveau parcours (cible)

```
Client (claude.ai, téléphone, ChatGPT…)
  └─ outil MCP fabriquer_video(modele, script, voix, titre, réponses YouTube)
       └─ API du site : POST /youtube/api/v1/fabrications/  → Video « fabrication »
            └─ Modal : fonction fabriquer (sans GPU, chef d'orchestre)
                 1. préchauffe les machines de rendu PENDANT la voix
                 2. voix (lire_parallele, déjà en place)            ~1 à 2 min
                 3. rendu Remotion découpé en N morceaux en parallèle
                 4. assemblage ffmpeg (copie sans réencodage) + son
                 5. vidéo rangée dans un volume Modal privé
            └─ worker du serveur : récupère la vidéo chez Modal → YouTube (par morceaux) → efface partout
  └─ etat_video : étape en cours (voix, rendu 7/12, envoi YouTube) puis lien youtu.be
```

Objectif mesuré (à confirmer au lot 1) : **vidéo de 2 min sur YouTube en moins de 4 min** après la validation du script.

---

## 3. Manques et solutions, par domaine

### 3.1 Fabrication de la vidéo sur Modal (rendu Remotion)

| Choix | Option | Vitesse pour le client | Retenu |
|---|---|---|---|
| Où rendre | PC du client | 4 à 5 fois la durée de la vidéo, installation de Node/Remotion | ⚪ |
| | Serveur DigitalOcean (droplet) | 1 seule machine, bloque le site pendant le rendu | ⚪ |
| | Remotion Lambda (AWS) | rapide, mais nouveau compte AWS, nouvelle facturation | ⚪ |
| | **Modal, rendu découpé en morceaux parallèles** (compte déjà utilisé pour la voix) | N machines en même temps ; durée ≈ durée d'un morceau | 🟢 |
| Préparation du projet | `remotion bundle` à chaque vidéo (9 s mesurées) | +9 s par vidéo | ⚪ |
| | **Bundle fait une fois, à la construction de l'image Modal** | 0 s | 🟢 |
| Démarrage des machines | à froid à chaque vidéo | +temps de démarrage (à mesurer) | ⚪ |
| | **Préchauffage lancé pendant la voix** (`prechauffer.spawn()` × N) | gratuit en temps : la voix dure déjà ~90 s | 🟢 |
| | Machine toujours allumée (`min_containers=1`) | le plus rapide, mais payé 24 h/24 | décision D7 |
| Son | rendu dans chaque morceau | risque de petits « clics » aux raccords | ⚪ |
| | **Morceaux d'image muets + piste son rendue une fois en parallèle, puis réunies par ffmpeg** | aucun raccord audible | 🟢 |

Tâches :

- [ ] **F1 — Service Modal de rendu** (Claude). ⏳ *Code prêt et testé sur le PC (14/11) ; reste l'essai réel sur Modal par Samba (JOURNAL.md, « Commandes pour Samba »).* Nouveau dossier `fabrication_modal/` dans le service :
  `service.py` (app `batchcodeia-video`), image Debian + Node + `chrome-headless-shell` (`npx remotion browser ensure`)
  + dépendances, `remotion bundle` fait à la construction. Fonctions :
  `prechauffer()`, `rendre_morceau(debut, fin, props)` (`renderMedia` avec `frameRange`, `muted`, `concurrency` = cœurs),
  `rendre_son(props)`, `assembler(...)` (ffmpeg `concat -c copy` + son), `fabriquer(donnees)` (chef d'orchestre,
  `rendre_morceau.map`), `telecharger_video(jeton)` (lien secret), `nettoyer()` (toutes les 6 h, comme la voix).
  Taille des morceaux : ~200 images, au plus 30 morceaux (à régler selon la mesure).
  *Fini quand* : `modal run` sur une vidéo test de 30 s produit un mp4 lisible, son calé, sans raccord visible.
- [ ] **F2 — Lecture de la voix sans transfert** (Claude). ⏳ *Code prêt et testé sur le PC (14/11) ; reste l'essai réel sur Modal par Samba (JOURNAL.md, « Commandes pour Samba »).* Le rendu monte le volume `batchcodeia-voix-audio` en lecture :
  l'audio ne sort jamais de Modal. `lire_parallele` renvoie aussi le `jeton` (pas seulement l'URL).
  *Fini quand* : test F1 avec voix réelle, aucun téléchargement de wav.
- [x] **F3 — Progression** (Claude). `modal.Dict` « progression » : étape (voix / rendu x sur N / assemblage / prête).
  *Fini quand* : `etat_video` affiche l'étape en cours pendant le test.
- [ ] **F4 — Mesures** (Claude, Samba regarde). ⏳ *Code prêt et testé sur le PC (14/11) ; reste l'essai réel sur Modal par Samba (JOURNAL.md, « Commandes pour Samba »).* Vidéos de 30 s, 2 min, 6 min : temps total, temps par étape, coût Modal
  (tableau de bord Modal). Résultat écrit dans `JOURNAL.md`. *Fini quand* : tableau des mesures rempli.
- [x] **F5 — Limites de sécurité** (Claude). Une fabrication à la fois par client, nombre total de machines plafonné
  (`max_containers`), durée maximale par vidéo selon l'offre, délai maximal (`timeout`), échec → quota rendu au client.
  *Fini quand* : tests Django (Modal simulé) des 4 cas.

### 3.2 Modèles de vidéos prêts (le client ne code rien)

| Option | Pour le client | Retenu |
|---|---|---|
| L'agent IA écrit du code TSX envoyé au serveur | lent (erreurs de code), risqué (code inconnu exécuté) | ⚪ (plus tard, peut-être) |
| **Modèles prêts : l'agent remplit seulement des champs (JSON)** | rapide, fiable, même sur téléphone | 🟢 |

- [x] **M1 — Projet Remotion des modèles** (Claude) : `fabrication_modal/remotion/` (package.json figé sur Remotion
  **4.0.300**, la version du Bureau), en reprenant `components.tsx`, `theme.ts`, `fonts.ts`, `Track.tsx` de
  `video-batchcodeia`. Le projet du Bureau reste intact (vidéos marketing de Samba).
- [x] **M2 — 4 modèles de départ** (Claude) : `lecon` (titre, points, bloc de code, 16:9), `astuces` (liste numérotée),
  `presentation` (produit / service), `short` (vertical 9:16, 60 s max). Une scène = un paragraphe du script,
  durée calée sur le `minutage` de la voix. Champs communs : titre, scènes (type, texte, points, code, langage),
  couleur d'accent, musique (`calme` / `energique` / `aucune`), format.
- [x] **M3 — Validation des champs côté serveur** (Claude) : serializer Django (nombre de scènes, longueur des textes,
  type de scène connu) ; message d'erreur clair pour l'agent. *Fini quand* : tests des champs invalides.
- [x] **M4 — Page « Modèles » sur le site du service** (Claude) : aperçu (courte vidéo) de chaque modèle, champs expliqués.
- [x] **M5 — Musiques et polices sous licence** (Samba vérifie, Claude remplace) : `musique.wav` et
  `musique-services.wav` ont une origine inconnue → licence commerciale prouvée ou remplacement par des musiques libres
  de droits. Polices Inter et Poppins : licence libre (OFL), à garder.
  *Fini quand* : chaque fichier a sa source et sa licence notées dans `fabrication_modal/remotion/LICENCES.md`.

### 3.3 Transfert et envoi sur YouTube (sans PC)

| Option | Retenu |
|---|---|
| Vidéo renvoyée au PC du client puis `curl` | ⚪ (supprimé) |
| Modal envoie lui-même sur YouTube (jeton Google transmis à Modal) | ⚪ gain de quelques secondes seulement, jeton Google hors de notre serveur (règle `CLAUDE.md` : jetons uniquement en base) |
| **Le worker du serveur récupère la vidéo chez Modal (centre de données → centre de données) puis l'envoie à YouTube par morceaux (code déjà éprouvé)** | 🟢 |

- [x] **T1 — Modèle `Video`** (Claude) : nouveaux états `fabrication` et `fabrication_echouee`, champs `modele`,
  `donnees_modele` (JSON), `appel_modal`, `etape`, `duree_secondes`. Migration (décision D3).
- [x] **T2 — Worker** (Claude) : `traiter_envois` surveille aussi les fabrications (toutes les 5 s, comme l'état de la
  voix) ; vidéo prête → téléchargement depuis `telecharger_video` (lien secret, à usage unique) → `en_attente` →
  envoi existant. Fichier effacé chez Modal **et** sur le serveur dès la fin, réussi ou non (règle existante).
  *Fini quand* : test avec Modal simulé + test réel lot 6.
- [x] **T3 — Corriger `envoyer_video` par lien public** (Claude) : reproduire le bug du 31/10, le corriger, ajouter un test.
- [ ] **T4 — Mesurer le temps Modal → serveur → YouTube** (Claude) ⏳ *Code prêt et testé sur le PC (14/11) ; reste l'essai réel sur Modal par Samba (JOURNAL.md, « Commandes pour Samba »).* ; s'il dépasse 30 s pour 50 Mo, revoir l'option
  « envoi direct depuis Modal » (décision D8).

### 3.4 Connecteur MCP et consignes « ordinateur »

- [x] **C1 — API** (Claude) : `POST /youtube/api/v1/fabrications/` (202 + `id`), mêmes vérifications que l'envoi
  (chaîne connectée, limite du jour, « pour les enfants » obligatoire, doublon), plus quota de l'offre.
  Documentée dans `guide_api.html` et `CLAUDE.md` (section API).
- [x] **C2 — Outil `fabriquer_video`** (Claude) dans `mcp_server.py` : `fabriquer_video(modele, script, scenes, titre,
  pour_enfants, contenu_ia, avec_ma_voix, visibilite, description)`. Règles : lire `mon_compte` (préférences) ; poser les
  2 questions YouTube si non enregistrées ; voix clonée → `contenu_ia = true` ; suivi avec `etat_video`.
- [x] **C3 — Outil `modeles_video`** (Claude) : liste des modèles et de leurs champs (l'agent sait quoi remplir).
- [x] **C4 — Supprimer toute consigne « sur ton ordinateur »** (Claude) :
  `mcp_server.py:235, 314-321, 345-359` ; `CLAUDE.md:128-134` (section « Créer et publier une vidéo ») ;
  `template/accounts/guide_claude.html:7, 39-48, 78-82, 90, 103-141` ; `accueil.html:36-40` ;
  `presentation.html:2-19` (« avec Claude Code » → « avec ton agent IA ») ; `README.md:12-15`.
  Le tableau des agents devient : **tous** les agents MCP (claude.ai, téléphone, ChatGPT, Claude Code…) fabriquent et publient.
- [x] **C5 — Sort de `preparer_envoi`** (décision D5) : 🟢 le retirer de la liste des outils (le dépôt `curl` reste dans
  l'API pour les développeurs, documenté seulement dans le guide de l'API).
- [x] **C6 — Test d'ordre du fichier** (Claude) : `OrdreDuFichierTests` passe à 8 outils (7 − 1 + 2), tous déclarés avant
  le démarrage. Après mise en ligne : `sudo systemctl restart youtube-mcp` (Samba) puis vérification `tools/list`.
  *Fini quand* : `rg -i "ordinateur|npx remotion|--concurrency" template mcp_server.py CLAUDE.md README.md` ne trouve
  plus aucune consigne de fabrication locale.

### 3.5 Comptes

- [x] **A1 — Courriel obligatoire et unique à l'inscription** (Claude) : `accounts/forms.py` ; les comptes existants sans
  courriel sont invités à l'ajouter à la connexion (page « Mon compte »). Indispensable pour le mot de passe oublié,
  les avis « vidéo en ligne » et le pont de paiement. Migration éventuelle (décision D3).
- [x] **A2 — Mot de passe oublié** (Claude) : vues intégrées de Django (`PasswordResetView` et suivantes), 4 templates
  au design du site, lien sur la page de connexion. Aucun nouveau paquet. *Fini quand* : test (courriel reçu, lien
  valable une fois, nouveau mot de passe accepté).
- [ ] **A3 — Courriels réellement envoyés** (Samba) : compte SMTP (Brevo est déjà prévu dans `.env.example` — offre
  gratuite limitée, **prix à vérifier** sur brevo.com) ; renseigner `EMAIL_HOST…` dans le `.env` du serveur ;
  enregistrements SPF/DKIM chez Hostinger. *Fini quand* : courriel de test reçu dans une boîte Gmail (pas en indésirables).
- [x] **A4 — Liste d'attente avant 100 utilisateurs** (Claude) : tant que Google n'a pas vérifié l'application, compteur
  des chaînes connectées ; à 90, le bouton « Connecter ma chaîne » propose une liste d'attente (courriel), et Samba est
  prévenu. Évite de bloquer à vie la 101ᵉ personne. *Fini quand* : test du seuil.

### 3.6 Pages obligatoires, contact et support

- [x] **P1 — Page Contact** (Claude) : formulaire (sujet, message, courriel) → courriel à l'adresse de support ;
  lien dans le pied de page ; anti-abus (limite par heure). Option : relier au support du site vitrine (`support.SupportTicket`) plus tard.
- [ ] **P2 — Adresse de support professionnelle** (Samba) : `support@batchcodeia.com` (boîte chez Hostinger ou
  redirection — **prix à vérifier**) ; Claude remplace l'adresse personnelle dans `conditions.html` et `confidentialite.html`.
- [x] **P3 — Politique de confidentialité à jour** (Claude rédige, Samba valide — *rédigé au lot 3, à valider*) : sous-traitants Modal (voix **et**
  vidéo, États-Unis), Stripe (paiement, via le site vitrine), Brevo (courriels), DigitalOcean ; transferts hors du Québec
  (Loi 25 : évaluation des facteurs relatifs à la vie privée avant de communiquer des renseignements hors Québec) ;
  durées de conservation (vidéo effacée après envoi, audio 24 h). Corriger « Batch Code AI » → « Batch Code IA ».
- [x] **P4 — Conditions d'utilisation** (Claude rédige, Samba valide — *rédigé au lot 3, à valider*) : offres, renouvellement, annulation, remboursement,
  statut Bêta, limites (quotas, YouTube), responsabilité du contenu.
- [x] **P5 — Page Tarifs du service** (Claude) : courte page « Gratuit / Pro » qui renvoie au paiement sur le site
  vitrine (voir 3.7) ; page « Mon offre » (offre, quotas restants, lien « Gérer mon abonnement »).

### 3.7 Offres, paiement et accès automatique

| Option | Pour le client | Retenu |
|---|---|---|
| Brancher un 2ᵉ Stripe dans le service | double travail, deux factures, deux comptes Stripe à suivre | ⚪ |
| **Paiement sur le site vitrine (Stripe déjà branché, plan « Créateur » déjà créé) + pont signé vers le service** | accès donné en quelques secondes après le paiement | 🟢 |
| Connexion unique (même compte sur les deux sites) | idéal, mais long à construire | ⚪ plus tard |

Offres proposées (chiffres à décider par Samba après les mesures de coûts F4 — décision D1) :

| | Gratuit | Pro (plan « Créateur » du vitrine) |
|---|---|---|
| Vidéos fabriquées | ex. 3 par mois, 1 min max | ex. 60 min de vidéo par mois |
| Voix clonée | ex. 2 min par mois (aujourd'hui 10 min) | ex. 60 min |
| Modèles | 2 | tous |
| Envois par jour | 2 | 5 (limite actuelle) |
| Prix | 0 $ | 19 $/mois proposé dans `seed_plateforme.py` — **à valider** |

- [x] **O1 — Offres dans le service** (Claude) : modèle `Abonnement` (user, courriel, offre `gratuit`/`pro`, actif,
  fin de période, identifiant de l'événement reçu) et une seule fonction `limites(user)` utilisée par la voix, la
  fabrication et l'envoi (remplace `QUOTA_GRATUIT_SECONDES`, `LIMITE_ENVOIS_PAR_JOUR`). Migration (décision D3).
- [x] **O2 — Point d'entrée du pont dans le service** (Claude) : `POST /youtube/api/v1/interne/abonnements/`, signé
  HMAC-SHA256 avec un secret partagé (`PONT_SECRET`), horodaté (refus après 5 min), sans effet en double (même
  événement reçu deux fois = une seule action). Courriel connu → accès changé ; courriel inconnu → compte créé sans
  mot de passe + courriel « Choisis ton mot de passe » (même mécanisme que A2) : le client a accès tout de suite.
  *Fini quand* : tests (signature fausse, trop vieille, doublon, compte nouveau, annulation).
- [x] **O3 — Envoi du pont depuis le site vitrine** (Claude) : nouveau fichier `billing/ponts.py`, appelé à la fin de
  `apply_stripe_subscription` (`billing/services.py:193`) seulement pour les plans liés au produit `youtube-uploader` ;
  tâche Celery avec nouvelles tentatives. Paiement actif ou en essai → Pro ; annulé, impayé, fin de période → Gratuit.
  *Fini quand* : test du vitrine (appel simulé) + essai Stripe en mode test (lot 6).
- [x] **O4 — Rattrapage quotidien** (Claude) : commande du vitrine qui renvoie l'état de tous les abonnements
  YouTube Uploader (si un appel s'est perdu, il est corrigé en 24 h au plus).
- [ ] **O5 — Secrets du pont** (Samba) : créer `PONT_SECRET` (même valeur dans les deux `.env`) et l'adresse du pont dans
  le `.env` du vitrine. Modifie les `settings.py` des deux projets (décision D4).
- [ ] **O6 — Stripe** (Samba) : vérifier que le plan « Créateur » a un prix dans Stripe (mode test puis réel) et que le
  webhook du vitrine reçoit `customer.subscription.*`. Frais Stripe : **prix à vérifier** sur stripe.com/fr-ca/pricing.

### 3.8 Site vitrine (Batch Code IA)

- [x] **V1 — Statut « Bêta »** (Samba dans l'administration, ou Claude dans `seed_plateforme.py`) : produit
  `youtube-uploader` → `beta` (le badge « Bêta » existe déjà dans `templates/catalog/product_detail.html:22`).
- [x] **V2 — Texte de la fiche produit** (Claude) : nouveau parcours (« sans rien installer, depuis ton téléphone »),
  places limitées pendant la vérification Google, lien « Commencer gratuitement » → inscription du service,
  bouton « Passer à Pro » → abonnement Stripe.
- [x] **V3 — Page tarifs** (`solutions:pricing`, existe déjà) : affiche l'offre Gratuit + Créateur (Claude, si besoin).
- [x] **V4 — Retour après paiement** (Claude) : page de succès du vitrine → « Ton accès Pro est actif » + lien vers
  api.batchcodeia.com (et « Choisis ton mot de passe » si le compte vient d'être créé).

### 3.9 Conformité Google / YouTube

- [ ] **G1 — Passer l'application en « Production » tout de suite** (Samba, `DEMARCHES_GOOGLE.md` étape 5, 1ʳᵉ partie).
  En mode « Test », chaque client doit être ajouté à la main et reconnecter sa chaîne tous les 7 jours : impossible à
  vendre. En Production non vérifiée : avertissement Google, plafond de 100 utilisateurs (à confirmer sur les pages
  d'aide citées dans `DEMARCHES_GOOGLE.md`).
- [ ] **G2 — Domaine dans Search Console** (Samba, étape 1).
- [ ] **G3 — Vidéo de démonstration** (Samba, étape 4) — **après le lot 3**, pour montrer le nouveau parcours
  (demande dans l'agent IA → vidéo fabriquée sur nos serveurs → visible dans YouTube Studio).
- [ ] **G4 — Demande de vérification** (Samba, étape 5, 2ᵉ partie) avec la justification du droit `youtube.upload`.
- [ ] **G5 — Audit de l'API YouTube** (Samba, étape 6, `yt_api_form`) : à vérifier — les vidéos envoyées par un projet
  non audité peuvent être bloquées en « privé » par YouTube ; et le quota de 100 envois par jour pour tout le service
  deviendra trop petit dès ~20 clients actifs. Délai inconnu : à lancer tôt.
- [ ] **G6 — Retirer l'ancien accès `token.json`** (Samba, étape 7).

### 3.10 Licences et coûts

- [ ] **L1 — Licence Remotion** (Samba, avant de vendre) : Remotion est gratuit pour les particuliers et les petites
  équipes, mais une **licence d'entreprise** est demandée dans certains cas, et le rendu sur serveur pour des clients
  (« automatisation ») a ses propres conditions. **Prix et conditions à vérifier** sur remotion.pro/license et
  remotion.dev/docs/license avant la mise en vente du lot 1.
- [ ] **L2 — Coûts Modal** (Samba) : **prix à vérifier** sur modal.com/pricing (GPU T4 à la seconde pour la voix,
  CPU et mémoire à la seconde pour le rendu, crédit gratuit mensuel éventuel). Coût réel par minute de vidéo mesuré en F4.
- [ ] **L3 — Plafond de dépenses Modal** (Samba) — *côté code fait au lot 5 (`BUDGET_MODAL_MENSUEL`, à décider par Samba)* : limite mensuelle dans le tableau de bord Modal + alerte par courriel.
- [x] **L4 — Tableau des coûts par client** (Claude) : dans l'administration du service, minutes de voix et de vidéo par
  mois et par client, coût estimé (tarif Modal saisi par Samba).

### 3.11 Exploitation : surveillance et sauvegardes

- [x] **E1 — Page de santé** (Claude) : `/sante/` (base lisible, worker vivant depuis moins de 2 min — le worker écrit
  un « battement » —, Modal joignable). Aucune donnée personnelle affichée.
- [ ] **E2 — Alerte de disponibilité** (Samba) : surveillance externe de `/sante/` toutes les 5 min avec alerte par
  courriel (ex. UptimeRobot, offre gratuite — **prix à vérifier**).
- [x] **E3 — Alertes d'erreurs** (Claude) : courriel à Samba (`ADMINS`) quand une fabrication ou un envoi échoue pour une
  cause du service (pas pour une erreur du client), et quand le quota YouTube est atteint. Modifie `settings.py` (D4).
- [x] **E4 — Sauvegarde hors du serveur** (Claude code, Samba choisit le lieu) — *code fait au lot 5 (volume Modal privé, chiffrée, 14 copies, vérifiée chaque jour) ; Samba active `SAUVEGARDE_HORS_SERVEUR=modal`* : copie quotidienne chiffrée de la base vers
  un volume Modal privé (déjà payé) ou un stockage objet (**prix à vérifier**). Garder 14 copies.
  Samba garde `TOKEN_ENCRYPTION_KEY` et `PONT_SECRET` dans un gestionnaire de mots de passe.
- [ ] **E5 — Essai de restauration** (Samba, guidé) — *commande `verifier_sauvegarde` prête (JOURNAL.md, « Mise en ligne — commandes pour Samba », étape 7)* : restaurer une copie sur le PC et vérifier que le site démarre.
- [ ] **E6 — Mise à jour en ligne** (Samba) — *toutes les commandes dans JOURNAL.md, « Mise en ligne — commandes pour Samba »* : `git pull`, `migrate`, `modal deploy fabrication_modal/service.py`,
  redémarrer `youtube-uploader`, `youtube-worker`, `youtube-mcp` (commandes données une par une à chaque lot).

### 3.12 Tests de bout en bout

- [x] **B1 — Tests Django** (Claude) : fabrication avec Modal simulé (réussite, échec, quota, doublon), pont, offres,
  mot de passe oublié, contact, liste d'attente. Objectif : 120 tests actuels + nouveaux, tous OK ; `manage.py check`.
- [ ] **B2 — Test Modal réel** (Claude) ⏳ *Code prêt et testé sur le PC (14/11) ; reste l'essai réel sur Modal par Samba (JOURNAL.md, « Commandes pour Samba »).* : `modal run` d'une vidéo de 30 s avec chaque modèle.
- [ ] **B3 — Scénario complet sur téléphone** (Samba) — *parcours simulé de bout en bout testé au lot 6 (`tests_bout_en_bout.py`) ; reste l'essai réel* : compte test → connecter la chaîne → claude.ai sur téléphone :
  « Fais une vidéo de 1 min sur les listes Python avec ma voix » → lien youtu.be reçu. Chronomètre noté au journal.
- [ ] **B4 — Scénario paiement** (Samba, Stripe en mode test) — *côté service testé au lot 6 (pont → Pro → annulation) ; reste l'essai Stripe* : achat du plan « Créateur » sur le vitrine → accès Pro dans
  le service en moins d'1 min → annulation → retour à Gratuit à la fin de la période (ou tout de suite si annulation immédiate).
- [ ] **B5 — Scénario d'erreur** (Claude + Samba) — *partie Claude faite au lot 6 (4 pannes simulées) ; reste l'essai réel* : chaîne déconnectée, quota atteint, Modal en panne → message clair,
  aucun envoi en boucle, quota rendu.

### 3.13 Autres manques trouvés

- [x] **X1 — Fichier vide `file`** à la racine du service (non suivi par git) : à supprimer (décision D6). *Cause trouvée et corrigée au lot 5 (la sauvegarde pendant les tests le recréait) ; le fichier reste à supprimer par Samba.*
- [x] **X2 — `JOURNAL.md`** (Claude) : une section par lot, mise à jour à chaque étape.
- [x] **X3 — Envois du jour comptés pour tout le service** (Claude) : avec le quota YouTube partagé (G5), plafond global
  quotidien et message « réessaie demain » avant d'atteindre la limite de Google.
- [ ] **X4 — Miniature de la vidéo** (plus tard) : image de couverture tirée du modèle ; droit Google et conditions
  (chaîne vérifiée) **à vérifier** avant de la promettre.
- [ ] **X5 — Voix standard pour les clients sans voix enregistrée** (décision D9) : sans elle, un nouveau client doit
  enregistrer sa voix avant sa 1ʳᵉ vidéo (ou faire une vidéo muette). Une voix de référence sous licence ferait gagner
  cette étape.
- [ ] **X6 — Annuaire officiel des connecteurs Anthropic** (plus tard, déjà noté C10 au journal).

---

## 4. Décisions oui / non à demander à Samba

| N° | Décision | Proposition 🟢 |
|---|---|---|
| D1 | Chiffres des offres Gratuit / Pro et prix (19 $/mois proposé) | décider après la mesure des coûts (F4) |
| D2 | Dépenses : Modal (rendu en plus de la voix), licence Remotion, SMTP, adresse de support, surveillance | oui, avec plafond Modal (L3) ; prix à vérifier avant |
| D3 | Migrations : `Video` (fabrication), `Abonnement`, courriel unique | oui, une par lot |
| D4 | Modifier `settings.py` du service (courriel, `ADMINS`, `PONT_SECRET`) et du vitrine (adresse et secret du pont) | oui |
| D5 | Retirer `preparer_envoi` de la liste des outils du connecteur | oui (dépôt gardé dans l'API) |
| D6 | Supprimer le fichier vide `file` | oui |
| D7 | Une machine de rendu toujours allumée (`min_containers=1`), payée en permanence | non au départ ; préchauffage pendant la voix |
| D8 | Envoi direct Modal → YouTube (jeton d'accès Google de 1 h transmis à Modal) | non, sauf si T4 montre plus de 30 s perdues |
| D9 | Voix standard sous licence pour les clients sans voix | à décider (prix et licence à vérifier) |
| D10 | Nouveaux paquets : seulement dans l'image Modal (`@remotion/renderer`, `@remotion/bundler` 4.0.300) ; aucun dans Django | oui |
| D11 | Produit en « Bêta » sur le vitrine jusqu'à la vérification Google | oui |

**Réponses de Samba (13-14 nov. 2026)** : D3 migrations ✅ oui · D4 settings.py ✅ oui · D10 paquets ✅ oui · rendu sur Modal ✅ oui ·
D5 retrait de preparer_envoi ✅ oui (Samba : « supprimer toutes les options qui fabriquent la vidéo sur un ordinateur ») ·
D6 fichier `file` ✅ supprimé · D7 machine toujours allumée ❌ non (préchauffage) · D8 envoi direct Modal → YouTube ❌ non (via le serveur) ·
D11 Bêta ✅ oui · D1, D2, D9 (prix, dépenses précises, voix standard) : après la mesure des coûts du lot 1.

---

## 5. Ordre de construction (chaque lot se termine par ses tests)

| Lot | Contenu | Qui | Fin du lot |
|---|---|---|---|
| **0 — Démarches, tout de suite et en parallèle** | G1, G2, G6, L1, L2, L3, A3, P2, O6, D1-D11 | Samba | décisions répondues, application Google en Production |
| **1 — Rendu sur Modal** | M1, M2, M5, F1, F2, F3, F5, B2, F4 | Claude (+ `modal deploy` par Samba) | vidéo de 30 s et de 2 min rendues sur Modal ; mesures et coûts au journal |
| **2 — Parcours complet sans PC** | T1, T2, T3, T4, C1, C2, C3, C4, C5, C6, M3, M4, X3 | Claude ; mise en ligne E6 par Samba | `fabriquer_video` publie sur YouTube ; aucune consigne « ordinateur » ; tests OK |
| **3 — Comptes et pages** | A1, A2, A4, P1, P3, P4 | Claude ; Samba valide les textes | mot de passe oublié et contact testés ; puis **G3** (vidéo de démonstration) et **G4**, **G5** par Samba |
| **4 — Offres et pont de paiement** | O1, O2, O3, O4, O5, P5, V1, V2, V3, V4, L4 | Claude (2 projets) ; secrets par Samba | B4 réussi en mode test Stripe |
| **5 — Exploitation** | E1, E2, E3, E4, E5 | Claude + Samba | alerte reçue lors d'une panne simulée ; restauration réussie |
| **6 — Bout en bout et ouverture Bêta** | B1, B3, B4, B5, X2, mise en ligne finale | Samba + Claude | Définition de terminé ci-dessous, toutes les cases cochées |

Plus tard : X4, X5 (si non), X6, connexion unique entre les deux sites, modèles supplémentaires.

---

## 6. Définition de terminé

Le service est terminé (ouverture Bêta) quand **toutes** ces conditions sont vraies et vérifiées :

- [ ] Depuis claude.ai **sur téléphone**, une demande de vidéo de 2 min avec la voix du client aboutit à un lien
  youtu.be, sans aucune commande ni installation chez le client ; temps mesuré et noté au journal (objectif : moins de 4 min).
- [x] Aucune page, aucun outil MCP, aucun guide ne demande d'utiliser l'ordinateur du client pour fabriquer ou déposer une vidéo.
- [x] Au moins 4 modèles sont utilisables par simples champs ; leurs musiques et polices ont une licence notée.
- [ ] Le fichier vidéo et l'audio sont effacés chez Modal et sur le serveur après l'envoi (réussi ou non).
- [ ] Inscription avec courriel, mot de passe oublié, page contact et adresse de support professionnelle fonctionnent.
- [ ] Paiement sur le site vitrine → accès Pro automatique en moins d'1 min ; annulation → retour à Gratuit ; testé en mode Stripe test puis une fois en réel.
- [ ] Le produit est affiché « Bêta » sur le vitrine ; la liste d'attente s'active avant 100 utilisateurs Google.
- [ ] Application Google en Production ; demande de vérification envoyée ; licence Remotion réglée ; plafond de dépenses Modal en place.
- [ ] Coût Modal par minute de vidéo connu, et prix de l'offre Pro supérieur à ce coût.
- [ ] Page de santé surveillée de l'extérieur ; alertes par courriel reçues lors d'un essai ; sauvegarde hors serveur restaurée avec succès.
- [ ] Politique de confidentialité et conditions à jour (Modal, Stripe, Brevo, offres, annulation), validées par Samba.
- [ ] Tous les tests Django OK (aucun échec), `manage.py check` sans erreur, tests B2 à B5 notés au journal.
- [x] `JOURNAL.md` à jour pour chaque lot.
