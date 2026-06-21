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
    assert i18n.tr("hub.sort") == "Sort out slides"


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
