"""Speech in and out on the Mac: local Whisper (auto-detects the language) and macOS `say`.

Whisper runs on the M-series GPU through mlx, so no audio leaves the laptop and Chinese, Portuguese
and English all work without picking a language first.
"""
import re
import subprocess
import tempfile

WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
# Preferred voices per language, first one installed wins.
VOICES = {
    "pt": ["Luciana", "Flo (Português (Brasil))", "Eddy (Português (Brasil))"],
    "zh": ["Tingting", "Flo (Chinês (China continental))", "Eddy (Chinês (China continental))"],
    "en": ["Samantha", "Flo (Inglês (EUA))", "Albert"],
    "es": ["Monica", "Paulina", "Flo (Espanhol (Espanha))"],
}
_installed = None
_current = None


def transcribe(audio: bytes, suffix: str = ".webm") -> tuple[str, str]:
    """(text, language code) for a recorded clip in any format ffmpeg reads."""
    import mlx_whisper  # slow import: only when audio actually arrives

    with tempfile.NamedTemporaryFile(suffix=suffix) as f:
        f.write(audio)
        f.flush()
        out = mlx_whisper.transcribe(f.name, path_or_hf_repo=WHISPER_MODEL, condition_on_previous_text=False)
    return out["text"].strip(), out.get("language", "")


def _voices() -> set[str]:
    global _installed
    if _installed is None:
        listing = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
        # lines look like: "Eddy (Português (Brasil)) pt_BR    # Olá, meu nome é Eddy."
        _installed = {m.group(1) for m in re.finditer(r"^(.+?)\s+[a-z]{2,3}_[A-Z0-9]{2,3}\s+#", listing, re.M)}
    return _installed


def speak(text: str, lang: str = "en"):
    """Say it out loud without blocking; a new sentence interrupts the previous one."""
    global _current
    if _current and _current.poll() is None:
        _current.terminate()
    voice = next((v for v in VOICES.get(lang[:2], []) if v in _voices()), None)
    cmd = ["say"] + (["-v", voice] if voice else []) + [text]
    _current = subprocess.Popen(cmd)


def chime():
    """Short sound: 'heard you, thinking'."""
    subprocess.Popen(["afplay", "/System/Library/Sounds/Tink.aiff"])
