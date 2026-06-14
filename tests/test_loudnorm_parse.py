from io_adapters.encode import parse_loudnorm_json

# A realistic tail of FFmpeg loudnorm stderr (preamble + JSON block).
SAMPLE = """\
[Parsed_loudnorm_0 @ 000001]
{
    "input_i" : "-27.61",
    "input_tp" : "-12.34",
    "input_lra" : "5.20",
    "input_thresh" : "-37.80",
    "output_i" : "-16.01",
    "output_tp" : "-1.50",
    "normalization_type" : "dynamic",
    "target_offset" : "0.01"
}
"""


def test_parses_integrated_and_true_peak():
    lufs, tp = parse_loudnorm_json(SAMPLE)
    assert lufs == -27.61
    assert tp == -12.34


def test_silence_floor_becomes_none():
    text = '{ "input_i" : "-70.1", "input_tp" : "-120.0" }'
    assert parse_loudnorm_json(text) == (None, None)


def test_inf_becomes_none():
    text = '{ "input_i" : "-inf", "input_tp" : "-inf" }'
    assert parse_loudnorm_json(text) == (None, None)


def test_no_json_returns_none():
    assert parse_loudnorm_json("nothing useful here") == (None, None)


def test_malformed_json_returns_none():
    assert parse_loudnorm_json("{ not valid json ") == (None, None)


def test_picks_last_json_block():
    text = '{"input_i":"-99.0"} ... later ... {"input_i":"-18.0","input_tp":"-2.0"}'
    assert parse_loudnorm_json(text) == (-18.0, -2.0)
