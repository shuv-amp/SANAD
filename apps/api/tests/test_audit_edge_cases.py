import pytest
from sanad_api.services.processing import _stabilize_structured_segment
from sanad_api.services.normalization import to_devanagari_digits

def test_audit_badge_edge_cases():
    # Scenario 1: Mangled Date (The original bug case)
    source = "2026-04-21"
    mangled = "२०२६-०४१"
    entities = [{"kind": "date", "text": "2026-04-21", "start": 0, "end": 10}]
    
    text, was_repaired = _stabilize_structured_segment(source, mangled, entities, [])
    assert text == "२०२६-०४-२१"
    assert was_repaired is True

    # Scenario 2: Perfect Date
    perfect = "२०२६-०४-२१"
    text, was_repaired = _stabilize_structured_segment(source, perfect, entities, [])
    assert text == "२०२६-०४-२१"
    assert was_repaired is False

    # Scenario 3: English Digits
    english = "2026-04-21"
    text, was_repaired = _stabilize_structured_segment(source, english, entities, [])
    assert text == "२०२६-०४-२१"
    assert was_repaired is True

    # Scenario 4: URL Protection
    url_source = "Visit https://api.v1.0"
    url_trans = "https://api.v1.0 मा जानुहोस्"
    url_entities = [{"kind": "url", "text": "https://api.v1.0"}]
    
    text, was_repaired = _stabilize_structured_segment(url_source, url_trans, url_entities, [])
    assert "https://api.v1.0" in text
    assert was_repaired is False

    # Scenario 5: Structural ID Repair
    id_source = "RES-2026-004"
    id_mangled = "RES-२०२६००४"
    id_entities = [{"kind": "id", "text": "RES-2026-004"}]
    
    text, was_repaired = _stabilize_structured_segment(id_source, id_mangled, id_entities, [])
    assert text == "RES-२०२६-००४"
    assert was_repaired is True

@pytest.mark.anyio
async def test_genius_repair_rejection():
    from sanad_api.services.processing import _attempt_auto_repair
    from unittest.mock import MagicMock
    
    provider = MagicMock()
    document = MagicMock()
    document.target_lang = "ne"
    
    source = "Fee: NPR 500"
    failed = "शुल्क: एनपीआर ५००"
    reasons = [{"code": "currency_suboptimal", "detail": "test", "repairable": True}]
    
    async def stupid_repair_mock(request):
        res = MagicMock()
        res.translated_text = "शुल्क: रु" # Bad repair deletes number
        return [res]
        
    provider.translate_batch = stupid_repair_mock
    
    final_text, flag = await _attempt_auto_repair(
        provider, document, source, failed, reasons, [], []
    )
    
    # Verify rejection and fallback
    assert "५००" in final_text
    assert "रु" in final_text
    assert flag is True
    assert final_text != "शुल्क: रु"

def test_script_normalization_audit():
    source = "Year 2026"
    trans = "Year 2026"
    text, was_repaired = _stabilize_structured_segment(source, trans, [], [])
    assert text == "Year २०२६"
    assert was_repaired is True
