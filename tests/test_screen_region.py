from io_adapters.screen import Region, physical_region


def test_identity_at_100_percent():
    # dpr 1.0 (100%) must leave the rectangle unchanged.
    r = physical_region(400, 200, 640, 480, 1.0)
    assert r == Region(400, 200, 640, 480)


def test_scales_at_150_percent():
    # A point framed at logical 400 sits at physical 600 on a 150% display.
    r = physical_region(400, 200, 640, 480, 1.5)
    assert r == Region(600, 300, 960, 720)


def test_scales_at_125_percent():
    r = physical_region(800, 0, 100, 100, 1.25)
    assert r == Region(1000, 0, 125, 125)


def test_negative_origin_left_monitor():
    # A monitor left of primary has negative coords; scaling must preserve sign.
    r = physical_region(-1920, 0, 300, 200, 1.5)
    assert r == Region(-2880, 0, 450, 300)


def test_rounds_fractional_pixels():
    r = physical_region(10, 10, 101, 101, 1.5)
    # 10*1.5=15, 101*1.5=151.5 -> 152 (round-half-to-even gives 152)
    assert r == Region(15, 15, round(101 * 1.5), round(101 * 1.5))
