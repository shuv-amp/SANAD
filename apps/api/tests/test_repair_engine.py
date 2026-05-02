import pytest
from sanad_api.services.processing import _attempt_auto_repair
from unittest.mock import MagicMock

@pytest.mark.anyio
async def test_repair_instruction_generation():
    # Mocking the dependencies
    provider = MagicMock()
    document = MagicMock()
    document.source_lang = "en"
    document.target_lang = "ne"
    
    source = "Fee: NPR 500. He is not coming."
    # Failed translation with:
    # 1. Sub-optimal currency (एनपीआर)
    # 2. Polarity flip (He is coming)
    # 3. Ghost entity (John)
    failed = "शुल्क: एनपीआर ५००। John आउँदैछन्।"
    
    risk_reasons = [
        {"code": "currency_suboptimal", "detail": "test"},
        {"code": "polarity_flip", "detail": "test"},
        {"code": "ghost_entity", "detail": "test"}
    ]
    
    # We want to verify that the repair instruction contains the correct strings
    # We mock translate_batch to see what it received
    async def mock_translate(request):
        instr = request.segments[0].source_text
        assert "Use 'रु' (the official symbol) for currency" in instr
        assert "Remove names or Latin words" in instr
        assert "meaning was REVERSED (Positive/Negative)" in instr
        
        # Return a 'fixed' version
        mock_result = MagicMock()
        mock_result.translated_text = "शुल्क: रु ५००। उनी आउँदैछैनन्।"
        return [mock_result]
        
    provider.translate_batch = mock_translate
    
    repaired, flag = await _attempt_auto_repair(
        provider, document, source, failed, risk_reasons, [], []
    )
    
    assert flag is True
    assert "रु ५००" in repaired
    assert "आउँदैछैनन्" in repaired
    assert "John" not in repaired

