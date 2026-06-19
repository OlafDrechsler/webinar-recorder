from core.filmstrip import Frame, build_filmstrip, visible_slots


def test_build_includes_auto_and_marked_sorted():
    names = ["00010.png", "00000.png", "00010_markiert_01.png", "notes.txt", "system.mp3"]
    frames = build_filmstrip(names)
    assert frames == [
        Frame(0, "00000.png", False),
        Frame(10, "00010.png", False),
        Frame(10, "00010_markiert_01.png", True),
    ]


def test_marked_flag_set():
    frames = build_filmstrip(["00137_markiert_02.png"])
    assert frames == [Frame(137, "00137_markiert_02.png", True)]


def test_ignores_non_slides():
    assert build_filmstrip(["mikro_00005.wav", "_aussortiert", "x.png"]) == []


def test_visible_slots_centres_current():
    # 5 slots, current=4 in the middle, plenty either side
    assert visible_slots(total=10, current=4, slots=5) == [2, 3, 4, 5, 6]


def test_visible_slots_empty_left_edge():
    assert visible_slots(total=10, current=0, slots=5) == [None, None, 0, 1, 2]


def test_visible_slots_empty_right_edge():
    assert visible_slots(total=3, current=2, slots=5) == [0, 1, 2, None, None]


def test_visible_slots_single_frame():
    assert visible_slots(total=1, current=0, slots=5) == [None, None, 0, None, None]
