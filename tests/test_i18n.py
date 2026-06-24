import core.i18n as i18n


def _lang(code):
    i18n._current = code


def test_german():
    _lang("de")
    assert i18n.tr("hub.record") == "Aufnahme"
    assert i18n.tr("hub.sort") == "Folien aussortieren"


def test_english():
    _lang("en")
    assert i18n.tr("hub.record") == "Record"
    assert i18n.tr("hub.sort") == "Filter slides"


def test_other_language_filled():
    _lang("fr")
    assert i18n.tr("hub.record") == "Enregistrer"


def test_unknown_key_returns_key():
    assert i18n.tr("does.not.exist") == "does.not.exist"


def test_missing_language_falls_back_to_english():
    _lang("xx")  # not a real language -> fall back to English
    assert i18n.tr("hub.record") == "Record"
    _lang("de")  # restore for any later use


def test_all_languages_listed():
    assert set(i18n.LANGUAGES) == {"de", "en", "fr", "es", "it", "pt", "nl", "pl", "tr"}


def test_every_key_translated_in_every_language():
    missing = [
        f"{key}:{lang}"
        for key, entry in i18n.TRANSLATIONS.items()
        for lang in i18n.LANGUAGES
        if not entry.get(lang)
    ]
    assert missing == [], f"missing translations: {missing}"


def test_format_placeholders_consistent_across_languages():
    # Keys with {placeholders} must keep them in every language.
    import re
    for key, entry in i18n.TRANSLATIONS.items():
        de_fields = set(re.findall(r"\{(\w+)", entry["de"]))
        for lang in i18n.LANGUAGES:
            assert set(re.findall(r"\{(\w+)", entry[lang])) == de_fields, f"{key}:{lang}"
