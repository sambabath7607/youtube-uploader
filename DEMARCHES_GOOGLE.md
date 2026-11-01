# Démarches Google à faire par Samba (A6) — avant d'ouvrir la plateforme au public

Pourquoi : en mode « Test », 100 testeurs au maximum et connexion YouTube qui expire tous les 7 jours ;
une application non vérifiée affiche un avertissement et ne peut avoir que 100 utilisateurs pour toute sa vie.
Sources : support.google.com/cloud (13463073, 13464321, 13461325, 15549945), developers.google.com/youtube.

| N° | Où | Quoi | Prêt côté site ? |
|---|---|---|---|
| 1 | https://search.google.com/search-console | Ajouter et **vérifier le domaine** `batchcodeia.com` (enregistrement DNS TXT chez Hostinger) | — |
| 2 | Google Cloud → APIs & Services → OAuth consent screen (Branding) | Page d'accueil : `https://api.batchcodeia.com/` ; confidentialité : `https://api.batchcodeia.com/confidentialite/` ; conditions : `https://api.batchcodeia.com/conditions/` ; domaine autorisé : `batchcodeia.com` | ✅ pages publiques en ligne |
| 3 | Même écran (Data access) | Droit demandé : `https://www.googleapis.com/auth/youtube.upload` seulement ; justification : « publier sur la chaîne de l'utilisateur les vidéos qu'il demande d'envoyer » | ✅ |
| 4 | Ton PC | **Vidéo de démonstration** (en anglais, sur YouTube en non répertoriée) : connexion au site → « Connecter ma chaîne YouTube » → écran de consentement Google complet → envoi d'une vidéo → vidéo visible dans YouTube Studio | à enregistrer |
| 5 | OAuth consent screen (Audience) | **Publish app** (passer en Production), puis **Prepare for verification** → envoyer la justification et le lien de la vidéo | — |
| 6 | https://support.google.com/youtube/contact/yt_api_form | Seulement si 100 envois par jour ne suffisent plus : audit et augmentation du quota | — |
| 7 | https://myaccount.google.com/permissions | (A7) Retirer l'ancien accès lié à `token.json`, s'il apparaît encore | — |

Garde aussi en lieu sûr (gestionnaire de mots de passe) une copie de `TOKEN_ENCRYPTION_KEY` du fichier .env du
serveur : sans elle, tous les utilisateurs devraient reconnecter leur chaîne.
