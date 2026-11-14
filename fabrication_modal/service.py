"""Service de fabrication des vidéos sur Modal (ne tourne PAS sur le serveur du site).

Parcours d'une vidéo (fonction « fabriquer », chef d'orchestre sans carte graphique) :
1. préchauffe les machines de rendu PENDANT la voix (aucune machine allumée en permanence : décision D7) ;
2. voix : appelle lire_parallele du service batchcodeia-voix ; l'audio reste dans le volume Modal (jamais téléchargé) ;
3. rendu Remotion découpé en morceaux d'images muets, rendus en parallèle sur plusieurs machines ;
4. piste son (voix + musique) fabriquée une seule fois par ffmpeg, pendant le rendu ;
5. assemblage ffmpeg (copie des images sans réencodage + son) ; la vidéo est rangée dans un volume Modal privé.
Le worker du serveur la récupère ensuite avec le client Modal (centre de données → centre de données), l'envoie
sur YouTube puis l'efface ici (décision D8 : aucun jeton Google chez Modal).

Mise en ligne (depuis le dossier src) :  modal deploy fabrication_modal/service.py
Essai réel (30 s par modèle) :           modal run fabrication_modal/service.py
"""
import json
import secrets
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import modal

from modeles import FPS, MODELES, decouper, duree_estimee, minutage_estime, paragraphes, props_remotion

app = modal.App("batchcodeia-video")
volume_videos = modal.Volume.from_name("batchcodeia-video-fichiers", create_if_missing=True)
volume_voix = modal.Volume.from_name("batchcodeia-voix-audio", create_if_missing=True)
progression = modal.Dict.from_name("batchcodeia-video-progression", create_if_missing=True)

DOSSIER_VIDEOS, DOSSIER_AUDIO = Path("/videos"), Path("/audio")
DOSSIER_REMOTION = Path(__file__).parent / "remotion"
APP_VOIX = "batchcodeia-voix"

CPU_PAR_MACHINE = 4            # cœurs de chaque machine de rendu (concurrency de Remotion)
MAX_MACHINES = 30              # plafond de machines de rendu pour TOUT le service (limite de dépense)
ATTENTE_PRECHAUFFAGE = 20      # s : garde chaque machine occupée le temps que les N machines démarrent
DELAI_MAX = 30 * 60            # une fabrication ne dure jamais plus de 30 min
CONSERVATION_VIDEO = 2 * 3600  # une vidéo non récupérée est effacée après 2 h
VOLUME_MUSIQUE = {"avec_voix": 0.15, "sans_voix": 1.0}

# Image : Node + navigateur chrome-headless-shell + ffmpeg ; le projet Remotion est préparé (« bundle »)
# UNE fois, à la construction de l'image : 0 s de préparation par vidéo.
image_rendu = (
    modal.Image.from_registry("node:20-bookworm-slim", add_python="3.11")
    .apt_install("ffmpeg", "fonts-dejavu-core", "libnss3", "libdbus-1-3", "libatk1.0-0", "libgbm-dev", "libasound2",
                 "libxrandr2", "libxkbcommon-dev", "libxfixes3", "libxcomposite1", "libxdamage1",
                 "libatk-bridge2.0-0", "libpango-1.0-0", "libcairo2", "libcups2")
    .add_local_dir(DOSSIER_REMOTION, "/remotion", copy=True, ignore=["node_modules", "build", "out"])
    .run_commands(
        "cd /remotion && npm install --no-audit --no-fund",
        "cd /remotion && npx remotion browser ensure",
        "cd /remotion && npx remotion bundle src/index.ts --out-dir build",
    )
    .add_local_python_source("modeles")
)


def marquer(cle, etape, fait=0, total=0):
    """Progression lue par le site (etat_video) : voix, rendu x/N, assemblage, prête."""
    try:
        progression[cle] = {"etape": etape, "fait": fait, "total": total, "le": time.time()}
    except Exception:   # la progression n'est qu'une information : elle ne bloque jamais la fabrication
        pass


@app.cls(image=image_rendu, cpu=CPU_PAR_MACHINE, memory=4096, max_containers=MAX_MACHINES, scaledown_window=120,
         timeout=15 * 60)
class Rendu:
    @modal.enter()
    def demarrer(self):
        # Le serveur Node ouvre le navigateur et charge le projet une fois pour toutes (préchauffage)
        self.serveur = subprocess.Popen(["node", "/remotion/serveur.mjs"], cwd="/remotion")
        limite = time.time() + 120
        while time.time() < limite:
            try:
                urllib.request.urlopen("http://127.0.0.1:3100/", timeout=2).read()
                return
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                time.sleep(0.3)
        raise RuntimeError("Le serveur de rendu n'a pas démarré.")

    @modal.exit()
    def arreter(self):
        self.serveur.terminate()

    @modal.method()
    def prechauffer(self, attente: float = ATTENTE_PRECHAUFFAGE) -> bool:
        time.sleep(attente)
        return True

    @modal.method()
    def rendre_morceau(self, numero: int, debut: int, fin: int, composition: str, props: dict) -> tuple:
        sortie = Path(tempfile.gettempdir()) / f"morceau_{numero}_{secrets.token_hex(4)}.mp4"
        demande = json.dumps({"composition": composition, "props": props, "debut": debut, "fin": fin,
                              "sortie": str(sortie), "concurrency": CPU_PAR_MACHINE}).encode()
        requete = urllib.request.Request("http://127.0.0.1:3100/rendre", data=demande,
                                         headers={"content-type": "application/json"})
        try:
            urllib.request.urlopen(requete, timeout=14 * 60).read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Rendu du morceau {numero} impossible : {e.read()[:500].decode(errors='replace')}")
        try:
            return numero, sortie.read_bytes()
        finally:
            sortie.unlink(missing_ok=True)


def expression_musique(style):
    """Musique originale générée par une formule ffmpeg (aucun fichier, aucune licence à payer : voir LICENCES.md).
    Accords lents (A, F#, D, E), avec une enveloppe qui retombe à zéro à chaque changement : aucun clic."""
    duree = 4 if style == "calme" else 2
    racine = (f"220*pow(2,(-3*eq(mod(floor(t/{duree}),4),1)-7*eq(mod(floor(t/{duree}),4),2)"
              f"-5*eq(mod(floor(t/{duree}),4),3))/12)")
    accord = f"(sin(2*PI*{racine}*t)+0.5*sin(3*PI*{racine}*t)+0.3*sin(4*PI*{racine}*t))"
    enveloppe = f"pow(sin(PI*mod(t,{duree})/{duree}),0.5)"
    if style == "energique":
        enveloppe += "*(0.55+0.45*pow(cos(PI*4*t),2))"
    return f"0.25*{accord}*{enveloppe}"


def rendre_son(sortie, duree, musique, voix=None):
    """Piste son de toute la vidéo, fabriquée une seule fois : voix (si présente) + musique plus basse."""
    commande = ["ffmpeg", "-v", "error", "-y"]
    if voix:
        commande += ["-i", str(voix)]
    if musique in ("calme", "energique"):
        commande += ["-f", "lavfi", "-i", f"aevalsrc='{expression_musique(musique)}':s=44100:d={duree:.2f}"]
    else:
        commande += ["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono:d={duree:.2f}"]
    volume = VOLUME_MUSIQUE["avec_voix" if voix else "sans_voix"] if musique != "aucune" else 1.0
    fondu = max(0.0, duree - 2)
    if voix:
        filtre = (f"[1:a]volume={volume},afade=t=out:st={fondu:.2f}:d=2[m];[0:a]aresample=44100,apad[v];"
                  "[v][m]amix=inputs=2:duration=shortest:normalize=0[a]")
    else:
        filtre = f"[0:a]volume={volume},afade=t=out:st={fondu:.2f}:d=2[a]"
    commande += ["-filter_complex", filtre, "-map", "[a]", "-t", f"{duree:.2f}", "-ac", "2", "-c:a", "aac",
                 "-b:a", "192k", str(sortie)]
    subprocess.run(commande, check=True)


def assembler(morceaux, son, sortie):
    """Morceaux d'images mis bout à bout sans réencodage (-c copy), puis la piste son."""
    liste = Path(sortie).with_suffix(".txt")
    liste.write_text("".join(f"file '{m}'\n" for m in morceaux))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(liste), "-i", str(son),
                    "-map", "0:v", "-map", "1:a", "-c", "copy", "-shortest", "-movflags", "+faststart", str(sortie)],
                   check=True)
    liste.unlink()


@app.function(image=image_rendu, volumes={str(DOSSIER_VIDEOS): volume_videos, str(DOSSIER_AUDIO): volume_voix},
              cpu=2, timeout=DELAI_MAX, max_containers=20)
def fabriquer(donnees: dict) -> dict:
    """Chef d'orchestre. donnees : cle, modele, titre, accent, musique, script, scenes, voix ({reference, debut} ou None).
    Renvoie le nom du fichier dans le volume, la durée, la taille et le temps de chaque étape (mesures F4)."""
    cle, modele, scenes = donnees["cle"], donnees["modele"], donnees["scenes"]
    debut_total, mesures = time.time(), {}
    jeton_voix = None
    try:
        marquer(cle, "preparation")
        estimation = round(duree_estimee(donnees["script"]) * FPS)
        if donnees.get("voix"):
            # Préchauffage : les machines de rendu démarrent PENDANT que la voix se fabrique (~1 à 2 min)
            rendu = Rendu()
            for _ in range(len(decouper(estimation))):
                rendu.prechauffer.spawn()
            marquer(cle, "voix")
            t = time.time()
            lire = modal.Function.from_name(APP_VOIX, "lire_parallele")
            voix = lire.remote(donnees["script"], donnees["voix"]["reference"], donnees["voix"].get("debut", 0.0))
            mesures["voix"] = round(time.time() - t, 1)
            jeton_voix, minutage = voix["jeton"], voix["minutage"]
        else:
            minutage = minutage_estime(donnees["script"])

        props = props_remotion(modele, donnees["titre"], scenes, donnees["accent"], minutage)
        total = props["duree"]
        duree = total / FPS
        morceaux = decouper(total)

        with tempfile.TemporaryDirectory() as dossier:
            dossier = Path(dossier)
            # Piste son pendant le rendu des images (en parallèle, sur cette machine)
            son, erreur_son = dossier / "son.m4a", []

            def piste():
                try:
                    if jeton_voix:
                        volume_voix.reload()
                    rendre_son(son, duree, donnees.get("musique", "calme"),
                               DOSSIER_AUDIO / f"{jeton_voix}.wav" if jeton_voix else None)
                except Exception as e:
                    erreur_son.append(e)

            fil = threading.Thread(target=piste)
            fil.start()

            marquer(cle, "rendu", 0, len(morceaux))
            t = time.time()
            fichiers = {}
            appels = [(i, debut, fin, modele, props) for i, (debut, fin) in enumerate(morceaux)]
            for numero, contenu in Rendu().rendre_morceau.starmap(appels, order_outputs=False):
                fichiers[numero] = dossier / f"m_{numero:03d}.mp4"
                fichiers[numero].write_bytes(contenu)
                marquer(cle, "rendu", len(fichiers), len(morceaux))
            mesures["rendu"] = round(time.time() - t, 1)
            fil.join()
            if erreur_son:
                raise erreur_son[0]

            marquer(cle, "assemblage")
            t = time.time()
            nom = f"{cle}.mp4"
            assembler([fichiers[i] for i in sorted(fichiers)], son, DOSSIER_VIDEOS / nom)
            volume_videos.commit()
            mesures["assemblage"] = round(time.time() - t, 1)

        mesures["total"] = round(time.time() - debut_total, 1)
        mesures["morceaux"] = len(morceaux)
        marquer(cle, "prete")
        return {"fichier": nom, "duree": round(duree, 1), "taille": (DOSSIER_VIDEOS / nom).stat().st_size,
                "mesures": mesures}
    finally:
        if jeton_voix:   # l'audio de la voix n'est plus utile : effacé tout de suite (vie privée)
            try:
                (DOSSIER_AUDIO / f"{jeton_voix}.wav").unlink(missing_ok=True)
                volume_voix.commit()
            except Exception:
                pass


@app.function(image=modal.Image.debian_slim(python_version="3.11"), volumes={str(DOSSIER_VIDEOS): volume_videos},
              schedule=modal.Period(hours=1))
def nettoyer():
    """Efface les vidéos non récupérées après 2 h (le worker efface normalement chaque vidéo dès sa récupération)."""
    volume_videos.reload()
    limite = time.time() - CONSERVATION_VIDEO
    for fichier in DOSSIER_VIDEOS.glob("*.mp4"):
        if fichier.stat().st_mtime < limite:
            fichier.unlink()
    volume_videos.commit()


@app.local_entrypoint()
def main(modele: str = "", voix: str = ""):
    """Essai réel (B2) : une vidéo d'exemple par modèle, enregistrée dans le dossier « essais_rendu ».
    modal run fabrication_modal/service.py                       (4 modèles, sans voix)
    modal run fabrication_modal/service.py --modele lecon --voix chemin/extrait.webm   (avec une voix)"""
    dossier = Path("essais_rendu")
    dossier.mkdir(exist_ok=True)
    reference = Path(voix).read_bytes() if voix else None
    for nom in ([modele] if modele else list(MODELES)):
        exemple = MODELES[nom]["exemple"]
        cle = f"essai-{nom}-{secrets.token_hex(4)}"
        debut = time.time()
        resultat = fabriquer.remote({
            "cle": cle, "modele": nom, "titre": exemple["titre"], "accent": "#3B8BFF", "musique": "calme",
            "script": exemple["script"], "scenes": exemple["scenes"],
            "voix": {"reference": reference, "debut": 0.0} if reference else None,
        })
        cible = dossier / f"{nom}.mp4"
        with open(cible, "wb") as f:
            for morceau in volume_videos.read_file(resultat["fichier"]):
                f.write(morceau)
        volume_videos.remove_file(resultat["fichier"])
        print(f"{nom} : {resultat['duree']} s de vidéo en {time.time() - debut:.0f} s "
              f"({len(paragraphes(exemple['script']))} scènes) → {cible} ; étapes : {resultat['mesures']}")
