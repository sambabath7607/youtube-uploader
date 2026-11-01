"""Service de voix sur Modal (ne tourne PAS sur le serveur du site).

Lit un texte avec la voix enregistrée d'un utilisateur (Chatterbox Multilingual V3, réglage « stable »),
range l'audio dans un volume Modal et renvoie un lien de téléchargement secret, effacé après 24 h.

Mise en ligne (depuis le PC) :  modal deploy voix_modal/service.py
"""
import re
import secrets
import subprocess
import tempfile
import time
from pathlib import Path

import modal

app = modal.App("batchcodeia-voix")
volume = modal.Volume.from_name("batchcodeia-voix-audio", create_if_missing=True)
DOSSIER_AUDIO = Path("/audio")

REGLAGE = {"exaggeration": 0.4, "cfg_weight": 0.3, "temperature": 0.6}   # validé par Samba le 31/10/2026
MAX_CARACTERES = 280                         # le modèle coupe les textes trop longs : on lit par morceaux
PAUSE_PHRASE, PAUSE_PARAGRAPHE = 0.25, 0.7   # secondes de silence
DUREE_CONSERVATION = 24 * 3600               # l'audio est effacé après 24 h


def telecharger_modele():
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    ChatterboxMultilingualTTS.from_pretrained(device="cpu", t3_model="v3")


image_voix = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "git")
    .pip_install("git+https://github.com/resemble-ai/chatterbox.git")
    .run_function(telecharger_modele)
)
image_legere = modal.Image.debian_slim(python_version="3.11").pip_install("fastapi[standard]")


def morceaux(paragraphe):
    phrases = re.split(r"(?<=[.!?…:;])\s+", paragraphe.strip())
    lot = ""
    for p in phrases:
        if lot and len(lot) + len(p) + 1 > MAX_CARACTERES:
            yield lot
            lot = p
        else:
            lot = (lot + " " + p).strip()
    if lot:
        yield lot


def rogner(son, sr, seuil=0.01, marge=0.05):
    """Retire le silence que le modèle laisse au début et à la fin de chaque morceau (jusqu'à ~2 s par phrase)."""
    import torch
    fort = (son.abs() > seuil).any(dim=0).nonzero()
    if len(fort) == 0:
        return son[:, :0]
    garde = int(sr * marge)
    return son[:, max(0, int(fort[0]) - garde): min(son.shape[1], int(fort[-1]) + garde)]


# Jusqu'à 10 cartes graphiques en même temps : chaque paragraphe est lu sur sa propre machine.
# scaledown_window = 5 min : une machine déjà prête resservira (test de voix puis lecture, plusieurs vidéos).
@app.cls(gpu="T4", image=image_voix, volumes={str(DOSSIER_AUDIO): volume}, scaledown_window=300,
         max_containers=10, timeout=3 * 3600)
class Voix:
    @modal.enter()
    def charger(self):
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        self.modele = ChatterboxMultilingualTTS.from_pretrained(device="cuda", t3_model="v3")

    @staticmethod
    def preparer_reference(reference: bytes, dossier: str, debut: float = 0.0) -> str:
        """Convertit l'extrait (webm...) en wav et garde 12 s à partir de « debut » (le modèle n'en écoute que 10)."""
        brut, wav = Path(dossier) / "brut", Path(dossier) / f"reference_{debut}.wav"
        brut.write_bytes(reference)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(debut), "-t", "12", "-i", str(brut),
                        "-ac", "1", "-ar", "24000", str(wav)], check=True)
        return str(wav)

    def sauver(self, son) -> str:
        import torchaudio as ta
        jeton = secrets.token_urlsafe(32)
        ta.save(str(DOSSIER_AUDIO / f"{jeton}.wav"), son, self.modele.sr)
        return f"{telecharger.get_web_url()}?jeton={jeton}"

    @modal.method()
    def lire(self, texte: str, reference: bytes, debut: float = 0.0) -> dict:
        import torch

        with tempfile.TemporaryDirectory() as dossier:
            wav = self.preparer_reference(reference, dossier, debut)
            torch.manual_seed(42)   # même voix d'une fois à l'autre
            sr = self.modele.sr
            silence = lambda s: torch.zeros(1, int(sr * s))
            paragraphes = [p for p in re.split(r"\n\s*\n", texte) if p.strip()]
            tout, minutage, position = [], [], 0.0
            for i, paragraphe in enumerate(paragraphes, 1):
                sons = []
                for m in morceaux(paragraphe):
                    son = self.modele.generate(m, language_id="fr", audio_prompt_path=wav, **REGLAGE)
                    sons += [rogner(son.cpu(), sr), silence(PAUSE_PHRASE)]
                son = torch.cat(sons, dim=1)
                duree = son.shape[1] / sr
                minutage.append({"paragraphe": i, "debut": round(position, 2), "duree": round(duree, 2),
                                 "texte": paragraphe.strip()})
                position += duree + PAUSE_PARAGRAPHE
                tout += [son, silence(PAUSE_PARAGRAPHE)]

        url = self.sauver(torch.cat(tout, dim=1))
        volume.commit()
        return {"url": url, "duree_audio": round(position, 1), "minutage": minutage}

    @modal.method()
    def lire_paragraphe(self, texte: str, reference: bytes, debut: float = 0.0) -> bytes:
        """Un paragraphe, silences rognés ; renvoie l'audio en wav (les paragraphes sont lus en parallèle)."""
        import io

        import torch
        import torchaudio as ta

        with tempfile.TemporaryDirectory() as dossier:
            wav = self.preparer_reference(reference, dossier, debut)
            torch.manual_seed(42)
            sr = self.modele.sr
            sons = []
            for m in morceaux(texte):
                son = self.modele.generate(m, language_id="fr", audio_prompt_path=wav, **REGLAGE)
                sons += [rogner(son.cpu(), sr), torch.zeros(1, int(sr * PAUSE_PHRASE))]
        tampon = io.BytesIO()
        ta.save(tampon, torch.cat(sons, dim=1), sr, format="wav")
        return tampon.getvalue()

    @modal.method()
    def essayer(self, texte: str, reference: bytes) -> list:
        """« Tester ma voix » : le même texte lu à partir de 3 passages de l'enregistrement (début, milieu, fin)."""
        import torch

        with tempfile.TemporaryDirectory() as dossier:
            brut = Path(dossier) / "complet"
            brut.write_bytes(reference)
            sortie = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                     str(brut)], capture_output=True, text=True, check=True)
            try:
                duree = float(sortie.stdout.strip())
            except ValueError:
                duree = 30.0   # certains enregistrements webm n'indiquent pas leur durée
            debuts = sorted({0.0, round(max(0.0, duree / 2 - 5), 1), round(max(0.0, duree - 11), 1)})
            propositions = []
            for debut in debuts:
                wav = self.preparer_reference(reference, dossier, debut)
                torch.manual_seed(42)
                son = self.modele.generate(texte, language_id="fr", audio_prompt_path=wav, **REGLAGE)
                propositions.append({"debut": debut, "url": self.sauver(son.cpu())})
        volume.commit()
        return propositions


@app.function(image=image_voix, volumes={str(DOSSIER_AUDIO): volume}, timeout=3 * 3600)
def lire_parallele(texte: str, reference: bytes, debut: float = 0.0) -> dict:
    """Utilisée par le site : chaque paragraphe part sur sa propre carte graphique (jusqu'à 10 à la fois),
    puis les morceaux sont assemblés dans l'ordre avec le minutage. Cette fonction n'utilise pas de carte graphique."""
    import io

    import torch
    import torchaudio as ta

    paragraphes = [p.strip() for p in re.split(r"\n\s*\n", texte) if p.strip()]
    audios = list(Voix().lire_paragraphe.map(paragraphes, kwargs={"reference": reference, "debut": debut}))
    tout, minutage, position, sr = [], [], 0.0, 24000
    for i, (paragraphe, audio) in enumerate(zip(paragraphes, audios), 1):
        son, sr = ta.load(io.BytesIO(audio))
        duree = son.shape[1] / sr
        minutage.append({"paragraphe": i, "debut": round(position, 2), "duree": round(duree, 2), "texte": paragraphe})
        position += duree + PAUSE_PARAGRAPHE
        tout += [son, torch.zeros(1, int(sr * PAUSE_PARAGRAPHE))]
    jeton = secrets.token_urlsafe(32)
    ta.save(str(DOSSIER_AUDIO / f"{jeton}.wav"), torch.cat(tout, dim=1), sr)
    volume.commit()
    return {"url": f"{telecharger.get_web_url()}?jeton={jeton}", "duree_audio": round(position, 1), "minutage": minutage}


@app.function(image=image_legere, volumes={str(DOSSIER_AUDIO): volume})
@modal.fastapi_endpoint(method="GET")
def telecharger(jeton: str):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    if not re.fullmatch(r"[A-Za-z0-9_-]{30,64}", jeton):
        raise HTTPException(status_code=404, detail="Audio introuvable.")
    volume.reload()
    chemin = DOSSIER_AUDIO / f"{jeton}.wav"
    if not chemin.exists():
        raise HTTPException(status_code=404, detail="Audio introuvable ou expiré (24 h).")
    return FileResponse(chemin, media_type="audio/wav", filename="voix.wav")


@app.function(image=image_legere, volumes={str(DOSSIER_AUDIO): volume}, schedule=modal.Period(hours=6))
def nettoyer():
    """Efface les audios de plus de 24 h (vie privée et place)."""
    volume.reload()
    limite = time.time() - DUREE_CONSERVATION
    for fichier in DOSSIER_AUDIO.glob("*.wav"):
        if fichier.stat().st_mtime < limite:
            fichier.unlink()
    volume.commit()
