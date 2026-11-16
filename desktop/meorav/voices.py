"""Bundled voice avatars (assets/voices/<voice-id>.png, 512x512).

The five Meorav-Multi-Voice avatars are illustrations, not likenesses (none of the voices is a real
person); master copies, prompts and provenance: Hebrish-Mgmt brand/voices/ (README.md, prompts.json).
Daniel's voice (Meorav v2.2) shows the app icon. An unknown voice id gets a lettered placeholder
in the window (app.py), so a catalogue can add a voice before the app ships its picture.
"""
from __future__ import annotations

from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"
AVATARS = ("josh", "rivka", "nigel", "fiona", "bazza")


def avatar_path(voice_id: str) -> Path | None:
    p = ASSETS / "voices" / f"{voice_id}.png"
    if p.is_file():
        return p
    if voice_id == "daniel" and (ASSETS / "meorav.png").is_file():
        return ASSETS / "meorav.png"
    return None
