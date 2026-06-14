"""Choosing a real microphone input device.

Why this exists: on some machines the Windows *default* recording device is
"Stereomix" (a loopback of the speakers) or a virtual audio cable. Recording from
it makes the microphone "hear" the system output — the level meter then mirrors
the headphones instead of the voice. So we do NOT blindly trust the OS default.

``choose_input_device`` picks a genuine microphone: it skips loopback/monitor/
virtual devices, prefers names that look like a mic and the WASAPI host API, and
honours an explicit ``preferred_name`` (what the user selected, remembered in
settings) above everything else.

Pure logic: it operates on a list of plain device dicts so it can be unit-tested
without any audio hardware. Each dict is expected to have at least ``name``,
``index``, ``maxInputChannels``, ``isLoopbackDevice`` and ``hostApiName``.
"""

from __future__ import annotations

from typing import Optional

# Substrings that mark a capture device as a loopback/monitor/virtual rather than
# a real microphone. Such devices are excluded from *automatic* selection (the
# user can still pick one explicitly).
_MONITOR_HINTS = (
    "stereomix", "stereo mix", "what u hear", "wave out", "loopback",
    "cable", "mapper", "primär", "primary sound", "summe", " mix",
)
# Names that strongly suggest a real microphone.
_MIC_HINTS = ("mikrofon", "microphone", "headset", "webcam", "mic ")

_API_RANK = {
    "windows wasapi": 3, "wasapi": 3,
    "windows directsound": 2, "directsound": 2,
    "mme": 1,
}


def _api_rank(device: dict) -> int:
    return _API_RANK.get(str(device.get("hostApiName", "")).lower(), 0)


def _is_monitorish(name: str) -> bool:
    n = name.lower()
    return any(hint in n for hint in _MONITOR_HINTS)


def _score(device: dict, default_index) -> int:
    name = str(device.get("name", "")).lower()
    score = _api_rank(device)
    if device.get("index") == default_index:
        score += 100  # honour the OS default — but only among real mics
    if any(hint in name for hint in _MIC_HINTS):
        score += 50
    return score


def choose_input_device(
    devices: list[dict], default_index, preferred_name: Optional[str] = None
) -> Optional[dict]:
    """Pick the best real microphone from ``devices``.

    Order of preference:
    1. A device whose name contains ``preferred_name`` (the user's saved choice).
    2. The highest-scoring non-monitor input (mic-like name + WASAPI + default).
    3. If every input looks like a monitor, fall back to the best of those, so we
       always return *something* rather than nothing.
    """
    inputs = [
        d for d in devices
        if d.get("maxInputChannels", 0) > 0 and not d.get("isLoopbackDevice")
    ]
    if not inputs:
        return None

    if preferred_name:
        pn = preferred_name.lower()
        matches = [d for d in inputs if pn in str(d.get("name", "")).lower()]
        if matches:
            return max(matches, key=_api_rank)

    real_mics = [d for d in inputs if not _is_monitorish(str(d.get("name", "")))]
    pool = real_mics or inputs
    return max(pool, key=lambda d: _score(d, default_index))


def list_microphone_names(devices: list[dict]) -> list[str]:
    """Unique input-device names for a picker, real mics first, deduped."""
    candidates = [
        d for d in devices
        if d.get("maxInputChannels", 0) > 0 and not d.get("isLoopbackDevice")
    ]
    # Real mics before monitors; within each group prefer the better host API
    # (so the full WASAPI name is seen before MME's 31-char truncated version).
    candidates.sort(key=lambda d: (_is_monitorish(str(d.get("name", ""))), -_api_rank(d)))
    names: list[str] = []
    for d in candidates:
        name = str(d.get("name", ""))
        if not name or name in names:
            continue
        # Skip MME-style truncated duplicates (a prefix of one already kept).
        if any(kept.startswith(name) for kept in names):
            continue
        names.append(name)
    return names
