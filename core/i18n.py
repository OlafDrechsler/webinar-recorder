"""Lightweight in-app translation.

A plain dict of ``key -> {lang: text}``; ``tr(key, **fmt)`` returns the string for
the current language, falling back to English then German then the key itself.
Language is persisted via ``core.settings``. No Qt .ts/.qm toolchain needed.

Stage note: hub/common strings are translated into all supported languages; the
deeper tool strings currently carry German + English and fall back to English for
the other languages until their dictionaries are filled in.
"""

from __future__ import annotations

from core.settings import get_language, set_language

# Display name per language code, in menu order.
LANGUAGES: dict[str, str] = {
    "de": "Deutsch",
    "en": "English",
    "fr": "Français",
    "es": "Español",
    "it": "Italiano",
    "pt": "Português",
    "nl": "Nederlands",
    "pl": "Polski",
    "tr": "Türkçe",
}

_DEFAULT = "de"
_current = _DEFAULT


def _t(de, en, fr=None, es=None, it=None, pt=None, nl=None, pl=None, tr_=None) -> dict:
    return {"de": de, "en": en, "fr": fr, "es": es, "it": it, "pt": pt,
            "nl": nl, "pl": pl, "tr": tr_}


TRANSLATIONS: dict[str, dict] = {
    # --- common ---
    "common.close": _t("Schließen", "Close", "Fermer", "Cerrar", "Chiudi",
                       "Fechar", "Sluiten", "Zamknij", "Kapat"),
    "common.cancel": _t("Abbrechen", "Cancel", "Annuler", "Cancelar", "Annulla",
                        "Cancelar", "Annuleren", "Anuluj", "İptal"),
    # --- hub ---
    "hub.subtitle": _t("Funktion wählen", "Choose a function", "Choisir une fonction",
                       "Elegir una función", "Scegli una funzione", "Escolher uma função",
                       "Kies een functie", "Wybierz funkcję", "Bir işlev seçin"),
    "hub.record": _t("Aufnahme", "Record", "Enregistrer", "Grabar", "Registra",
                     "Gravar", "Opnemen", "Nagrywaj", "Kaydet"),
    "hub.player": _t("Player", "Player", "Lecteur", "Reproductor", "Lettore",
                     "Reprodutor", "Speler", "Odtwarzacz", "Oynatıcı"),
    "hub.sort": _t("Folien aussortieren", "Sort out slides", "Trier les diapositives",
                   "Depurar diapositivas", "Filtra diapositive", "Filtrar slides",
                   "Dia's opschonen", "Wyczyść slajdy", "Slaytları ayıkla"),
    "hub.settings": _t("Einstellungen", "Settings", "Paramètres", "Ajustes", "Impostazioni",
                       "Definições", "Instellingen", "Ustawienia", "Ayarlar"),
    "settings.language": _t("Sprache", "Language", "Langue", "Idioma", "Lingua",
                            "Idioma", "Taal", "Język", "Dil"),
    "hub.quit_while_recording": _t(
        "Eine Aufnahme läuft. WebinarOD trotzdem beenden? Die laufende Aufnahme geht verloren.",
        "A recording is in progress. Quit WebinarOD anyway? The current recording will be lost.",
        "Un enregistrement est en cours. Quitter WebinarOD quand même ? L'enregistrement en cours sera perdu.",
        "Hay una grabación en curso. ¿Salir de WebinarOD de todos modos? Se perderá la grabación actual.",
        "È in corso una registrazione. Uscire comunque da WebinarOD? La registrazione in corso andrà persa.",
        "Há uma gravação em curso. Sair do WebinarOD mesmo assim? A gravação atual será perdida.",
        "Er is een opname bezig. WebinarOD toch afsluiten? De huidige opname gaat verloren.",
        "Trwa nagrywanie. Zamknąć WebinarOD mimo to? Bieżące nagranie zostanie utracone.",
        "Bir kayıt sürüyor. WebinarOD yine de kapatılsın mı? Geçerli kayıt kaybolacak.",
    ),
    "settings.hint": _t(
        "Die Sprache gilt für neu geöffnete Fenster.",
        "The language applies to newly opened windows.",
        "La langue s'applique aux fenêtres nouvellement ouvertes.",
        "El idioma se aplica a las ventanas abiertas a partir de ahora.",
        "La lingua si applica alle finestre aperte da ora.",
        "O idioma aplica-se às janelas abertas a partir de agora.",
        "De taal geldt voor vanaf nu geopende vensters.",
        "Język dotyczy nowo otwartych okien.",
        "Dil, yeni açılan pencerelere uygulanır.",
    ),
}


def current_language() -> str:
    return _current


def init_language() -> None:
    """Load the saved language (default German) at startup."""
    global _current
    saved = get_language()
    _current = saved if saved in LANGUAGES else _DEFAULT


def set_current_language(code: str) -> None:
    global _current
    if code in LANGUAGES:
        _current = code
        set_language(code)


def tr(key: str, **fmt) -> str:
    entry = TRANSLATIONS.get(key)
    if not entry:
        return key
    text = entry.get(_current) or entry.get("en") or entry.get("de") or key
    return text.format(**fmt) if fmt else text
