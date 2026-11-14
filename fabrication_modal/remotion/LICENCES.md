# Licences des fichiers des modèles de vidéos

Chaque fichier utilisé dans les vidéos fabriquées pour les clients a sa source et sa licence ici (tâche M5).

| Fichier | Source | Licence | Usage commercial |
|---|---|---|---|
| `public/inter-latin-400-normal.woff2`, `-500-`, `-600-` | Police **Inter** (Rasmus Andersson), fichiers au nommage du paquet `@fontsource/inter`, copiés du projet `video-batchcodeia` | SIL Open Font License 1.1 | oui |
| `public/poppins-latin-600-normal.woff2`, `-700-`, `-800-` | Police **Poppins** (Indian Type Foundry), fichiers au nommage du paquet `@fontsource/poppins`, copiés du projet `video-batchcodeia` | SIL Open Font License 1.1 | oui |
| Police du code (`DejaVu Sans Mono`) | paquet Debian `fonts-dejavu-core`, installé dans l'image Modal | licence libre DejaVu (dérivée de Bitstream Vera) | oui |
| Musiques « calme » et « energique » | **générées** à chaque vidéo par une formule ffmpeg (`expression_musique` dans `fabrication_modal/service.py`) : accords simples, aucun enregistrement ni échantillon | création originale de Batch Code IA | oui |
| Fond animé, cadres, icônes | dessinés en code (`src/components.tsx`, repris de `video-batchcodeia`) | création originale de Batch Code IA | oui |
| Bibliothèque Remotion 4.0.300 | remotion.dev | **licence Remotion** : gratuite pour les particuliers et petites équipes, licence d'entreprise dans certains cas — **à vérifier par Samba avant la vente (tâche L1)** | à vérifier |

## Fichiers volontairement NON repris

- `musique.wav` et `musique-services.wav` du projet `video-batchcodeia` : origine inconnue. Ils ne sont pas copiés ici
  et ne servent jamais dans les vidéos des clients. Si Samba retrouve leur licence commerciale, on pourra les ajouter
  comme musique supplémentaire (ligne à ajouter dans ce tableau).
- `logo.svg` : pas utilisé par les modèles (les vidéos sont celles des clients, pas celles de Batch Code IA).
