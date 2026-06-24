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
    "hub.sort": _t("Folien aussortieren", "Filter slides", "Trier les diapositives",
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

    # --- common (DE + EN; other languages fall back to EN for now) ---
    "common.next": _t("Weiter", "Continue"),
    "common.browse": _t("Durchsuchen…", "Browse…"),
    "common.start": _t("Start", "Start"),
    "common.save": _t("Speichern", "Save"),
    "common.edit": _t("Bearbeiten", "Edit"),
    "common.delete": _t("Löschen", "Delete"),
    "common.on": _t("AN", "On"),
    "common.off": _t("aus", "off"),

    # --- colours ---
    "color.yellow": _t("Gelb", "Yellow"),
    "color.red": _t("Rot", "Red"),
    "color.blue": _t("Blau", "Blue"),
    "color.green": _t("Grün", "Green"),
    "color.black": _t("Schwarz", "Black"),
    "color.white": _t("Weiß", "White"),

    # --- storage dialog ---
    "storage.title": _t("Speicherort wählen", "Choose storage location"),
    "storage.info": _t(
        "Wo sollen die Aufnahmen gespeichert werden?\nTipp: einen OneDrive-Ordner "
        "wählen, der zwischen den Rechnern synchronisiert wird. Die Auswahl wird "
        "gemerkt und beim nächsten Start vorausgefüllt.",
        "Where should the recordings be saved?\nTip: choose a OneDrive folder that "
        "syncs between your computers. The choice is remembered and pre-filled next time.",
    ),
    "storage.choose_folder": _t("Ordner wählen", "Choose folder"),
    "storage.error_title": _t("Ordner nicht nutzbar", "Folder not usable"),
    "storage.error_body": _t(
        "Der Ordner konnte nicht angelegt werden:\n{path}\n\n{error}\n\nBitte einen anderen Speicherort wählen.",
        "The folder could not be created:\n{path}\n\n{error}\n\nPlease choose a different location.",
    ),

    # --- post-processing progress ---
    "progress.wait_title": _t("Bitte warten", "Please wait"),
    "progress.processing": _t("Aufnahme wird verarbeitet…", "Processing the recording…"),
    "progress.system": _t("System-Ton wird umgewandelt…", "Converting system audio…"),
    "progress.analyze_seg": _t("Analysiere Mikro-Segment {i}/{n}…", "Analysing mic segment {i}/{n}…"),
    "progress.convert_seg": _t("Wandle Mikro-Segment {i}/{n} um…", "Converting mic segment {i}/{n}…"),
    "progress.done": _t("Fertig.", "Done."),

    # --- recording control window ---
    "record.start": _t("Aufnahme starten", "Start recording"),
    "record.stop": _t("Aufnahme beenden", "Stop recording"),
    "record.region_choose": _t("Aufnahmebereich wählen", "Choose capture area"),
    "record.region_rechoose": _t("Bereich neu wählen", "Re-select area"),
    "record.photo": _t("Foto-Aufnahme", "Photo capture"),
    "record.edit_image": _t("Bild bearbeiten", "Edit image"),
    "record.status": _t(
        "Aufnahme: {rec} | Bereich: {region} | Folien: {count} | {hk}",
        "Recording: {rec} | Area: {region} | Slides: {count} | {hk}",
    ),
    "record.rec_running": _t("läuft ●", "running ●"),
    "record.rec_idle": _t("bereit (nicht gestartet)", "ready (not started)"),
    "record.region_set": _t("gewählt", "selected"),
    "record.region_none": _t("—", "—"),
    "record.hotkeys_on": _t("Hotkeys aktiv", "Hotkeys active"),
    "record.hotkeys_off": _t("Hotkeys aus (Admin nötig)", "Hotkeys off (admin required)"),
    "record.mic_off": _t("Mikro: AUS (nimmt nichts auf)", "Mic: OFF (records nothing)"),
    "record.mic_on_recording": _t("Mikro: AN (nimmt durchgehend auf ●)", "Mic: ON (recording continuously ●)"),
    "record.mic_on_idle": _t("Mikro: AN (startet mit der Aufnahme)", "Mic: ON (starts with the recording)"),
    "record.mic_auto_idle": _t("Mikro: Auto (Pegel-Test möglich, nimmt noch nicht auf)",
                               "Mic: Auto (level test possible, not recording yet)"),
    "record.mic_auto_active": _t("Mikro: Auto – nimmt auf ●", "Mic: Auto – recording ●"),
    "record.mic_auto_wait": _t("Mikro: Auto – wartet auf Geräusch", "Mic: Auto – waiting for sound"),

    # --- mic mode + level test ---
    "mic.label": _t("Mikro:", "Mic:"),
    "mic.on": _t("an", "on"),
    "mic.off": _t("aus", "off"),
    "mic.auto": _t("auto", "auto"),
    "mic.level_test": _t("Mikro-Pegel-Test", "Mic level test"),
    "mic.test_instruction": _t(
        "Sprich normal – der Balken sollte beim Reden über die Schwelle steigen, bei Stille darunter.",
        "Speak normally – the bar should rise above the threshold while talking and stay below in silence.",
    ),
    "mic.device_label": _t("Mikrofon:", "Microphone:"),
    "mic.threshold_label": _t("Schwelle:", "Threshold:"),
    "mic.threshold_value": _t("Schwelle: {value:.3f}", "Threshold: {value:.3f}"),
    "mic.over": _t("Status: ÜBER Schwelle (würde aufnehmen)", "Status: ABOVE threshold (would record)"),
    "mic.under": _t("Status: unter Schwelle (Stille)", "Status: below threshold (silence)"),

    # --- work area (edit) ---
    "edit.title": _t("Arbeitsbereich – Sekunde {sec}", "Work area – second {sec}"),
    "edit.highlighter": _t("Textmarker", "Highlighter"),
    "edit.pen": _t("Stift", "Pen"),
    "edit.text": _t("Text", "Text"),
    "edit.eraser": _t("Radierer", "Eraser"),
    "edit.thickness": _t("Dicke", "Thickness"),
    "edit.font_size": _t("Schriftgröße: {n} px", "Font size: {n} px"),

    # --- slide filter (sort out) ---
    "sort.prev": _t("‹ vorheriges", "‹ previous"),
    "sort.next": _t("nächstes ›", "next ›"),
    "sort.reference": _t("Referenzbild {i}/{n}: {name}", "Reference image {i}/{n}: {name}"),
    "sort.rect": _t("Rechteck", "Rectangle"),
    "sort.ellipse": _t("Ellipse", "Ellipse"),
    "sort.remove_last": _t("Letzten Bereich entfernen", "Remove last area"),
    "sort.clear_all": _t("Alle löschen", "Clear all"),
    "sort.mode_ignore": _t("Modus: Ignorierbereich", "Mode: Ignore area"),
    "sort.mode_compare": _t("Modus: Vergleichsbereich", "Mode: Compare area"),
    "sort.sensitivity": _t("Empfindlichkeit:", "Sensitivity:"),
    "sort.mask_save": _t("Maske speichern…", "Save mask…"),
    "sort.mask_load": _t("Maske laden…", "Load mask…"),
    "sort.action_move": _t("Aktion: Aussortieren (verschieben)", "Action: Filter out (move)"),
    "sort.action_delete": _t("Aktion: ENDGÜLTIG LÖSCHEN", "Action: DELETE PERMANENTLY"),
    "sort.dry_run": _t("Probelauf", "Dry run"),
    "sort.choose_folder": _t("Folienordner wählen", "Choose slide folder"),
    "sort.mask_save_title": _t("Maske speichern", "Save mask"),
    "sort.mask_load_title": _t("Maske laden", "Load mask"),
    "sort.load_failed": _t("Laden fehlgeschlagen", "Load failed"),
    "sort.nothing_title": _t("Nichts zu tun", "Nothing to do"),
    "sort.nothing_body": _t("Keine Bilder vorhanden.", "No images present."),
    "sort.delete_confirm_title": _t("Endgültig löschen?", "Delete permanently?"),
    "sort.delete_confirm_body": _t(
        "Die als Duplikat erkannten Bilder werden UNWIDERRUFLICH gelöscht.\nFortfahren?",
        "The images detected as duplicates will be deleted IRREVERSIBLY.\nContinue?",
    ),
    "sort.comparing": _t("Vergleiche Bilder…", "Comparing images…"),
    "sort.dry_result": _t(
        "Probelauf: {removed} von {total} Bildern wären Duplikate (es bliebe(n) {kept}).",
        "Dry run: {removed} of {total} images would be duplicates ({kept} would remain).",
    ),
    "sort.none_found": _t("Keine Duplikate gefunden – nichts geändert.", "No duplicates found – nothing changed."),
    "sort.moved": _t("{n} Bilder nach '_aussortiert' verschoben.", "{n} images moved to '_aussortiert'."),
    "sort.deleted": _t("{n} Bilder endgültig gelöscht.", "{n} images permanently deleted."),
    "sort.remaining": _t("{done} Verbleibend: {n}.", "{done} Remaining: {n}."),
    "sort.no_slides": _t("Keine Folienbilder (NNNNN.png) in diesem Ordner gefunden.",
                         "No slide images (NNNNN.png) found in this folder."),

    # --- player ---
    "player.folder_label": _t("Ordner:", "Folder:"),
    "player.choose_folder_btn": _t("Ordner wählen…", "Choose folder…"),
    "player.no_folder_loaded": _t("(kein Ordner geladen)", "(no folder loaded)"),
    "player.choose_folder_title": _t("Aufnahme-Ordner wählen", "Choose recording folder"),
    "player.slide": _t("Folie: {name}", "Slide: {name}"),
    "player.slide_none": _t("Folie: —", "Slide: —"),
    "player.tempo": _t("Tempo:", "Speed:"),
    "player.system": _t("System:", "System:"),
    "player.mic": _t("Mikro:", "Mic:"),
    "player.segments": _t("Mikro-Segmente: {n}", "Mic segments: {n}"),
    "player.note": _t("Notiz", "Note"),
    "player.back_tip": _t("10 s zurück", "10 s back"),
    "player.fwd_tip": _t("10 s vor", "10 s forward"),
    "player.slide_tip": _t("Klick = Play/Pause · Doppelklick links/rechts = 10 s zurück/vor",
                           "Click = play/pause · double-click left/right = 10 s back/forward"),
    "player.note_tip": _t("Aktuelle Folie pausieren und annotieren (wird im Filmstreifen abgelegt)",
                          "Pause the current slide and annotate it (stored in the film strip)"),
    "player.no_slide": _t("Keine Folie", "No slide"),
    "player.no_folder": _t("Kein Ordner geladen", "No folder loaded"),
    "player.no_slides_folder": _t("Keine Folien in diesem Ordner", "No slides in this folder"),
    "player.delete_title": _t("Bild löschen?", "Delete image?"),
    "player.delete_body": _t("'{name}' wirklich löschen?", "Really delete '{name}'?"),
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
