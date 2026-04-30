from sanad_api.services.processing import _stabilize_structured_segment


def test_hash_labels_stay_exact() -> None:
    assert _stabilize_structured_segment("#11", "११११") == "#11"
    assert _stabilize_structured_segment("  #5  ", "५५ जना") == "#5"


def test_normal_segments_keep_provider_translation() -> None:
    assert _stabilize_structured_segment("Physical Harm", "शारीरिक हानी") == "शारीरिक हानी"
