from sanad_api.services.processing import _stable_structured_candidate, _stabilize_structured_segment


def test_hash_labels_stay_exact() -> None:
    assert _stabilize_structured_segment("#11", "११११")[0] == "#११"
    assert _stabilize_structured_segment("  #5  ", "५५ जना")[0] == "#५"


def test_standalone_structural_labels_skip_provider_translation() -> None:
    assert _stable_structured_candidate("11") == "११"
    assert _stable_structured_candidate("1.2") == "१.२"
    assert _stable_structured_candidate("iv") == "iv"
    assert _stable_structured_candidate("•") == "•"
    assert _stable_structured_candidate(". . . . .") == ". . . . ."


def test_normal_segments_keep_provider_translation() -> None:
    assert _stabilize_structured_segment("Physical Harm", "शारीरिक हानी")[0] == "शारीरिक हानी"
    assert _stable_structured_candidate("Abstract") is None
