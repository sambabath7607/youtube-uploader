"""Catalogue des modèles de vidéos et calculs communs (Python pur, sans Django ni Modal).

Utilisé à deux endroits :
- par le site (youtube_uploader) : liste des modèles, vérification des champs, durée estimée ;
- par le service de rendu sur Modal (fabrication_modal/service.py) : minutage des scènes, découpage en morceaux.
L'agent IA ne code rien : il remplit seulement les champs d'un modèle (JSON).
"""
import math
import re

FPS = 30
MOTS_PAR_SECONDE = 2.5        # même débit que l'estimation de la voix (youtube_uploader/voix.py)
PAUSE_PARAGRAPHE = 0.7        # secondes, comme dans voix_modal/service.py
FIN_VIDEO = 1.5               # secondes ajoutées après la dernière phrase
DUREE_MIN_SCENE = 2.5         # secondes
TAILLE_MORCEAU = 200          # images par morceau de rendu (≈ 6,7 s de vidéo)
MAX_MORCEAUX = 30             # au plus 30 machines de rendu pour une vidéo
MAX_SCENES = 30

FORMATS = {"16:9": (1920, 1080), "9:16": (1080, 1920)}
MUSIQUES = {"calme": "Musique douce (accords lents)", "energique": "Musique rythmée",
            "aucune": "Pas de musique"}

TYPES_SCENE = {
    "titre": "Grand titre (première scène en général). Champ : texte.",
    "texte": "Une phrase mise en valeur, mot par mot. Champ : texte.",
    "points": "Un titre et une liste de 1 à 6 points cochés. Champs : texte, points.",
    "code": "Un titre et un bloc de code (20 lignes max). Champs : texte, code, langage.",
    "fin": "Dernière scène : message de fin et titre de la vidéo. Champ : texte.",
}

MODELES = {
    "lecon": {
        "nom": "Leçon",
        "description": "Cours expliqué pas à pas : titre, notions numérotées, exemples de code, conclusion.",
        "format": "16:9",
        "duree_max": 600,
        "types": ["titre", "texte", "points", "code", "fin"],
        "exemple": {
            "titre": "Les listes en Python",
            "script": "Aujourd'hui, on découvre les listes en Python.\n\n"
                      "Une liste est ordonnée, modifiable, et s'écrit entre crochets.\n\n"
                      "Pour ajouter un élément, on utilise la méthode append.\n\n"
                      "Merci d'avoir regardé, à bientôt pour la suite !",
            "scenes": [
                {"type": "titre", "texte": "Les listes en Python"},
                {"type": "points", "texte": "Une liste, c'est :", "points": ["ordonnée", "modifiable", "entre crochets"]},
                {"type": "code", "texte": "Ajouter un élément", "langage": "python",
                 "code": "fruits = [\"pomme\"]\nfruits.append(\"kiwi\")\nprint(fruits)  # ['pomme', 'kiwi']"},
                {"type": "fin", "texte": "Merci d'avoir regardé !"},
            ],
        },
    },
    "astuces": {
        "nom": "Astuces",
        "description": "Liste numérotée d'astuces (« 5 astuces pour… ») : une astuce par scène.",
        "format": "16:9",
        "duree_max": 600,
        "types": ["titre", "texte", "points", "code", "fin"],
        "exemple": {
            "titre": "3 astuces Python",
            "script": "Voici trois astuces Python qui vont te faire gagner du temps.\n\n"
                      "Première astuce : inverse une liste avec deux points deux points moins un.\n\n"
                      "Deuxième astuce : échange deux variables sur une seule ligne.\n\n"
                      "Troisième astuce : utilise enumerate pour avoir l'indice et la valeur.\n\n"
                      "Abonne-toi pour d'autres astuces !",
            "scenes": [
                {"type": "titre", "texte": "3 astuces Python"},
                {"type": "code", "texte": "Inverser une liste", "langage": "python", "code": "nombres[::-1]"},
                {"type": "code", "texte": "Échanger deux variables", "langage": "python", "code": "a, b = b, a"},
                {"type": "code", "texte": "L'indice et la valeur", "langage": "python",
                 "code": "for i, fruit in enumerate(fruits):\n    print(i, fruit)"},
                {"type": "fin", "texte": "Abonne-toi pour d'autres astuces !"},
            ],
        },
    },
    "presentation": {
        "nom": "Présentation",
        "description": "Présenter un produit ou un service : promesse, avantages, appel à l'action.",
        "format": "16:9",
        "duree_max": 300,
        "types": ["titre", "texte", "points", "fin"],
        "exemple": {
            "titre": "Batch Code IA",
            "script": "Batch Code IA crée tes vidéos YouTube avec ta propre voix.\n\n"
                      "Tu demandes, l'agent écrit le script, et la vidéo est fabriquée pour toi.\n\n"
                      "Essaie gratuitement dès aujourd'hui.",
            "scenes": [
                {"type": "titre", "texte": "Tes vidéos, avec ta voix"},
                {"type": "points", "texte": "Sans rien installer",
                 "points": ["Script écrit par l'IA", "Ta voix clonée", "Publié sur ta chaîne"]},
                {"type": "fin", "texte": "Essaie gratuitement"},
            ],
        },
    },
    "short": {
        "nom": "Short (vertical)",
        "description": "Vidéo verticale 9:16 pour YouTube Shorts : 60 secondes maximum, phrases courtes.",
        "format": "9:16",
        "duree_max": 60,
        "max_scenes": 8,
        "types": ["titre", "texte", "points", "code", "fin"],
        "exemple": {
            "titre": "Une astuce Python en 20 secondes",
            "script": "Une astuce Python en vingt secondes.\n\n"
                      "Pour inverser une liste, écris simplement deux points deux points moins un.\n\n"
                      "Abonne-toi pour la suite !",
            "scenes": [
                {"type": "titre", "texte": "Astuce Python"},
                {"type": "code", "texte": "Inverser une liste", "langage": "python", "code": "nombres[::-1]"},
                {"type": "fin", "texte": "Abonne-toi !"},
            ],
        },
    },
}


def paragraphes(script):
    """Une scène = un paragraphe du script (paragraphes séparés par une ligne vide)."""
    return [p.strip() for p in re.split(r"\n\s*\n", script or "") if p.strip()]


def secondes_paragraphe(texte):
    return max(DUREE_MIN_SCENE, len(texte.split()) / MOTS_PAR_SECONDE)


def minutage_estime(script):
    """Minutage sans voix (ou avant la voix) : début et durée de chaque paragraphe, en secondes."""
    minutage, position = [], 0.0
    for i, texte in enumerate(paragraphes(script), 1):
        duree = secondes_paragraphe(texte)
        minutage.append({"paragraphe": i, "debut": round(position, 2), "duree": round(duree, 2)})
        position += duree + PAUSE_PARAGRAPHE
    return minutage


def duree_estimee(script):
    """Durée de la vidéo en secondes, estimée à partir du nombre de mots."""
    minutage = minutage_estime(script)
    if not minutage:
        return 0.0
    return minutage[-1]["debut"] + minutage[-1]["duree"] + FIN_VIDEO


def images_des_scenes(minutage, nb_scenes):
    """(début, durée) en images pour chaque scène, d'après le minutage de la voix, et la durée totale.
    Chaque scène commence avec son paragraphe et dure jusqu'au paragraphe suivant (la 1re commence à 0)."""
    debuts = [0] + [round(m["debut"] * FPS) for m in minutage[1:nb_scenes]]
    fin = round((minutage[nb_scenes - 1]["debut"] + minutage[nb_scenes - 1]["duree"] + FIN_VIDEO) * FPS)
    bornes = debuts + [fin]
    scenes = []
    for i in range(nb_scenes):
        duree = max(round(DUREE_MIN_SCENE * FPS) if i == nb_scenes - 1 else 1, bornes[i + 1] - bornes[i])
        scenes.append((bornes[i], duree))
    total = scenes[-1][0] + scenes[-1][1]
    return scenes, total


def decouper(total, taille=TAILLE_MORCEAU, maximum=MAX_MORCEAUX):
    """Morceaux [début, fin] (images incluses) rendus en parallèle : ~200 images, au plus 30 morceaux."""
    taille = max(taille, math.ceil(total / maximum))
    return [(debut, min(debut + taille, total) - 1) for debut in range(0, total, taille)]


def numeros(modele, scenes):
    """Numéro affiché sur chaque scène (« Astuce 2 ») : les scènes autres que titre et fin, dans l'ordre."""
    n, resultat = 0, []
    for scene in scenes:
        if scene["type"] in ("titre", "fin") or modele == "presentation":
            resultat.append(0)
        else:
            n += 1
            resultat.append(n)
    return resultat


def props_remotion(modele, titre, scenes, accent, minutage):
    """Données envoyées au projet Remotion (fabrication_modal/remotion/src/types.ts)."""
    largeur, hauteur = FORMATS[MODELES[modele]["format"]]
    images, total = images_des_scenes(minutage, len(scenes))
    nums = numeros(modele, scenes)
    return {
        "modele": modele, "titre": titre, "accent": accent, "largeur": largeur, "hauteur": hauteur, "duree": total,
        "scenes": [
            {"type": s["type"], "texte": s.get("texte", ""), "points": list(s.get("points") or []),
             "code": s.get("code", ""), "langage": s.get("langage", ""), "numero": num, "debut": debut, "duree": duree}
            for s, num, (debut, duree) in zip(scenes, nums, images)
        ],
    }
