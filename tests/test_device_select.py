from core.device_select import choose_input_device, list_microphone_names

# Modelled on a real machine where the OS default input is "Stereomix" (a
# loopback of the speakers) — the bug this logic fixes.
DEVICES = [
    {"index": 0, "name": "Microsoft Soundmapper - Input", "maxInputChannels": 2,
     "isLoopbackDevice": False, "hostApiName": "MME"},
    {"index": 1, "name": "Stereomix (Realtek(R) Audio)", "maxInputChannels": 2,
     "isLoopbackDevice": False, "hostApiName": "MME"},
    {"index": 3, "name": "Mikrofon (Logitech Webcam C925e)", "maxInputChannels": 2,
     "isLoopbackDevice": False, "hostApiName": "MME"},
    {"index": 23, "name": "Mikrofon (Logitech Webcam C925e)", "maxInputChannels": 2,
     "isLoopbackDevice": False, "hostApiName": "Windows WASAPI"},
    {"index": 24, "name": "Stereomix (Realtek(R) Audio)", "maxInputChannels": 2,
     "isLoopbackDevice": False, "hostApiName": "Windows WASAPI"},
    {"index": 25, "name": "Lautsprecher (Realtek(R) Audio) [Loopback]",
     "maxInputChannels": 2, "isLoopbackDevice": True, "hostApiName": "Windows WASAPI"},
]

DEFAULT_INDEX = 1  # Stereomix is the OS default — must NOT be auto-selected


def test_picks_real_mic_over_default_stereomix():
    chosen = choose_input_device(DEVICES, DEFAULT_INDEX)
    assert "Logitech" in chosen["name"]


def test_prefers_wasapi_among_equal_mics():
    chosen = choose_input_device(DEVICES, DEFAULT_INDEX)
    assert chosen["hostApiName"] == "Windows WASAPI"
    assert chosen["index"] == 23


def test_never_auto_selects_loopback():
    chosen = choose_input_device(DEVICES, DEFAULT_INDEX)
    assert chosen["isLoopbackDevice"] is False


def test_preferred_name_wins():
    # User explicitly saved the Logitech mic by name.
    chosen = choose_input_device(DEVICES, DEFAULT_INDEX, preferred_name="Logitech")
    assert "Logitech" in chosen["name"]
    assert chosen["hostApiName"] == "Windows WASAPI"  # best API among matches


def test_preferred_name_can_select_stereomix_if_asked():
    chosen = choose_input_device(DEVICES, DEFAULT_INDEX, preferred_name="Stereomix")
    assert "Stereomix" in chosen["name"]


def test_returns_none_without_inputs():
    only_loopback = [DEVICES[5]]
    assert choose_input_device(only_loopback, None) is None


def test_falls_back_when_only_monitors_present():
    monitors = [DEVICES[1], DEVICES[4]]  # only Stereomix entries
    chosen = choose_input_device(monitors, DEFAULT_INDEX)
    assert chosen is not None  # better than nothing


def test_list_names_unique_and_real_first():
    names = list_microphone_names(DEVICES)
    assert names[0] == "Mikrofon (Logitech Webcam C925e)"  # real mic first
    assert names.count("Mikrofon (Logitech Webcam C925e)") == 1  # deduped
    assert "Lautsprecher (Realtek(R) Audio) [Loopback]" not in names  # no loopback


def test_list_names_suppresses_mme_truncated_duplicate():
    # MME truncates names to 31 chars; the truncated prefix must not show twice.
    devices = [
        {"index": 23, "name": "Mikrofon (Logitech Webcam C925e)", "maxInputChannels": 2,
         "isLoopbackDevice": False, "hostApiName": "Windows WASAPI"},
        {"index": 3, "name": "Mikrofon (Logitech Webcam C925e", "maxInputChannels": 2,
         "isLoopbackDevice": False, "hostApiName": "MME"},
    ]
    assert list_microphone_names(devices) == ["Mikrofon (Logitech Webcam C925e)"]
