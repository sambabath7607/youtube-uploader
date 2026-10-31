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


@app.cls(gpu="T4", image=image_voix, volumes={str(DOSSIER_AUDIO): volume}, scaledown_window=60, timeout=3 * 3600)
class Voix:
    @modal.enter()
    def charger(self):
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        self.modele = ChatterboxMultilingualTTS.from_pretrained(device="cuda", t3_model="v3")

    @modal.method()
    def lire(self, texte: str, reference: bytes) -> dict:
        import torch
        import torchaudio as ta

        # L'extrait arrive tel qu'enregistré dans le navigateur (webm...) : conversion en wav
        with tempfile.TemporaryDirectory() as dossier:
            brut, wav = Path(dossier) / "brut", Path(dossier) / "reference.wav"
            brut.write_bytes(reference)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(brut), "-ac", "1", "-ar", "24000", str(wav)], check=True)

            torch.manual_seed(42)   # même voix d'une fois à l'autre
            sr = self.modele.sr
            silence = lambda s: torch.zeros(1, int(sr * s))
            paragraphes = [p for p in re.split(r"\n\s*\n", texte) if p.strip()]
            tout, minutage, position = [], [], 0.0
            for i, paragraphe in enumerate(paragraphes, 1):
                sons = []
                for m in morceaux(paragraphe):
                    son = self.modele.generate(m, language_id="fr", audio_prompt_path=str(wav), **REGLAGE)
                    sons += [son.cpu(), silence(PAUSE_PHRASE)]
                son = torch.cat(sons, dim=1)
                duree = son.shape[1] / sr
                minutage.append({"paragraphe": i, "debut": round(position, 2), "duree": round(duree, 2),
                                 "texte": paragraphe.strip()})
                position += duree + PAUSE_PARAGRAPHE
                tout += [son, silence(PAUSE_PARAGRAPHE)]

        jeton = secrets.token_urlsafe(32)
        ta.save(str(DOSSIER_AUDIO / f"{jeton}.wav"), torch.cat(tout, dim=1), sr)
        volume.commit()
        return {"url": f"{telecharger.get_web_url()}?jeton={jeton}", "duree_audio": round(position, 1),
                "minutage": minutage}


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
