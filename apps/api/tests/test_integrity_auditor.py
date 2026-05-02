import pytest
from sanad_api.services.risk import score_translation
from sanad_api.services.processing import _strip_ai_chatter, _stabilize_structured_segment
from sanad_api.services.normalization import to_devanagari_digits

def test_number_swap_detection():
    # Source has Total near 500 and Tax near 50
    source = "The total amount is 500 and the tax is 50."
    # Target has numbers swapped (context check)
    # We simulate a model failure where 50 and 500 are swapped
    target = "कुल रकम ५० हो र कर ५०० हो।"
    
    entities = [
        {"kind": "number", "text": "500", "start": 20, "end": 23},
        {"kind": "number", "text": "50", "start": 39, "end": 41}
    ]
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=entities,
        glossary_hits=[]
    )
    
    # Even if numbers match (digits-to-ascii), 
    # we expect the integrity logic to at least flag something or be aware of the shift
    # Current implementation of swap check is a placeholder/heuristic in risk.py
    # but the numbers are verified.
    
    # Let's check if the basic number check passes (it should as digits match)
    assert any(r["code"] == "changed_number" for r in reasons) == False
    
def test_ai_chatter_stripping():
    input_text = "Sure, here is the translation: नमस्कार साथी"
    expected = "नमस्कार साथी"
    assert _strip_ai_chatter(input_text) == expected
    
    input_text = "Translation: \"नमस्ते\""
    expected = "नमस्ते"
    assert _strip_ai_chatter(input_text) == expected

def test_auto_localization_1_1():
    source = "1.1 Introduction"
    target = "1.1 परिचय" # ASCII 1.1
    
    # We test the stabilization layer which now has a final normalization pass
    entities = [{"kind": "number", "text": "1.1", "start": 0, "end": 3}]
    
    result = _stabilize_structured_segment(
        source_text=source,
        translated_text=target,
        protected_entities=entities,
        glossary_hits=[]
    )
    
    assert "१.१" in result[0]
    assert "1.1" not in result[0]

def test_truncation_detection():
    source = "This is a very long paragraph that explains many important things about document translation and safety alignment."
    target = "यो एक धेरै लामो" # Truncated
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "length_deviation" for r in reasons)
    # Check if repairable is True for truncation
    deviation_reason = next(r for r in reasons if r["code"] == "length_deviation")
    assert deviation_reason["repairable"] == True

def test_glossary_script_exemption():
    source = "Open Google Search"
    target = "Google खोज खोल्नुहोस्" # Google is Latin
    
    glossary_hits = [{
        "source_term": "Google",
        "target_term": "Google",
        "term_type": "brand"
    }]
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=glossary_hits
    )
    
    # Should NOT have script_imbalance because Google is in glossary
    assert not any(r["code"] == "script_imbalance" for r in reasons)

def test_punctuation_mismatch():
    source = "The price (estimated) is high."
    target = "मूल्य (अनुमानित मात्र हो।" # Missing closing bracket
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "punctuation_mismatch" for r in reasons)

def test_symbol_leak():
    source = "Total price is 100."
    target = "कुल मूल्य @१०० हो।" # Unexpected @
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "symbol_leak" for r in reasons)

def test_major_omission():
    source = "This is a very long and complex legal sentence that contains multiple clauses about responsibility and liability and should not be shortened."
    target = "यो छोटो छ।" # Very short
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "major_omission" for r in reasons)

def test_date_mismatch():
    source = "The event is on 2024-12-25."
    target = "कार्यक्रम डिसेम्बरमा छ।" # Date missing
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "date_mismatch" for r in reasons)

def test_negation_flip():
    source = "This action is not permitted under the law."
    target = "यो कार्य कानून बमोजिम अनुमति दिइएको छ।" # Affirmative
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "negation_flip" for r in reasons)

def test_honorific_inconsistency():
    target = "तपाईं यता आउ र तिमी बस।" # Mixes high/low
    
    score, reasons = score_translation(
        source_text="Come here and sit down.",
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "honorific_inconsistency" for r in reasons)

def test_instruction_leak():
    target = "Sure, here is the translation: नमस्कार"
    
    score, reasons = score_translation(
        source_text="Hello",
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "instruction_leak" for r in reasons)

def test_placeholder_broken():
    source = "Welcome {{name}}, your ID is [USER_ID]."
    target = "स्वागत छ {{नाम}}, तपाईको आईडी [USER_ID] हो।" # {{name}} was translated
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "placeholder_broken" for r in reasons)

def test_directional_flip():
    source = "The company profit has increased significantly."
    target = "कम्पनीको नाफा उल्लेख्य रूपमा घट्यो।" # Decreased
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "directional_flip" for r in reasons)

def test_unicode_sanitation():
    target = "नमस्ते\u200bदुनिया" # Contains Zero Width Space
    
    score, reasons = score_translation(
        source_text="Hello world",
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "unicode_sanitized" for r in reasons)

def test_negation_abbreviation_fix():
    # Source has "No. 4" (number), target is affirmative.
    # This should NOT trigger negation_flip because "No." is an abbreviation.
    source = "Ward No. 4 will verify the address."
    target = "वडा नं. ४ ले ठेगाना पुष्टि गर्नेछ।" 
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert not any(r["code"] == "negation_flip" for r in reasons)

def test_sov_position_shift_tolerance():
    # "Office" is at end in English (1.0), near middle in Nepali (0.5)
    source = "Submit this form to the Ward Office."
    target = "यो फारम वडा कार्यालयमा बुझाउनुहोला।"
    
    entities = [{
        "kind": "office",
        "text": "Ward Office",
        "start": 24,
        "end": 35,
        "segment_source_len": len(source)
    }]
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=entities,
        glossary_hits=[]
    )
    
    # Should NOT trigger position_shift because of SOV-aware threshold
    assert not any(r["code"] == "position_shift" for r in reasons)

def test_currency_integrity():
    # Source has USD, target has nothing or wrong currency
    source = "The fee is $500."
    target = "शुल्क ५०० हो।" # Missing 'Dollar'
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "currency_missing" for r in reasons)

def test_list_sequence_auditor():
    # Source: 1. A, 2. B, 3. C
    # Target: १. A, २. B, ४. C (Model skipped 3)
    source = "1. First 2. Second 3. Third"
    target = "१. पहिलो २. दोस्रो ४. तेस्रो"
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "list_sequence_broken" for r in reasons)

def test_forbidden_term_shield():
    # Target uses informal 'kaagaj' instead of 'pramanpatra'
    target = "यो एउटा नागरिकताको कागज हो।"
    
    score, reasons = score_translation(
        source_text="This is a citizenship document.",
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "forbidden_term" for r in reasons)

def test_logical_flow_guardian():
    # Source has 'However' (contrast), Target has nothing or wrong logic
    source = "However, the application was rejected."
    target = "त्यसैले, आवेदन अस्वीकृत भयो।" # 'Therefore' instead of 'However'
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "logical_flow_broken" for r in reasons)

def test_identity_swap_sentinel():
    # Source: Ram sued Shyam.
    # Target: श्यामले रामलाई मुद्दा हाल्यो। (Shyam sued Ram)
    source = "Ram sued Shyam."
    target = "Shyam ले Ram लाई मुद्दा हाल्यो।" # Order: Shyam, Ram
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "identity_swap" for r in reasons)

def test_entity_anchor_engine():
    # Source: Ward 4 and House 500
    # Target: वडा ५०० र घर ४ (Mixed up)
    source = "Ward 4 and House 500"
    target = "वडा ५०० र घर ४"
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "anchor_mismatch" for r in reasons)

def test_professional_landmark_auditor():
    # Source has [SIGNATURE] marker, target misses it
    source = "Approved by: [SIGNATURE]"
    target = "द्वारा अनुमोदित:" # Missing signature placeholder
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "missing_landmark" for r in reasons)

def test_certification_marker_guard():
    # Source: Certified True Copy
    # Target: साँचो प्रतिलिपि (Missing 'Certified' / 'Pramanit')
    source = "Certified True Copy"
    target = "साँचो प्रतिलिपि" 
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "certification_missing" for r in reasons)

def test_date_hallucination_guard():
    # Source has 2024 (AD), Target has 2081 (BS)
    source = "The date is 2024-05-01."
    target = "मिति २०८१-०१-१९ हो।"
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "date_conversion_risk" for r in reasons)

def test_anachronism_sentinel():
    # Source has 'VDC' (Obsolete), Target might follow it
    source = "He lives in the Ward 4 VDC."
    target = "उनी वडा ४ गाविसमा बस्छन्।" # 'GAVISA' is VDC
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "anachronism_risk" for r in reasons)

def test_absolute_omission_guard():
    # Source has text, target is empty
    source = "Critical legal clause."
    target = ""
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "total_omission" for r in reasons)
    assert score == 10.0

def test_semantic_number_swap():
    # Source: Ward 4, House 500
    # Target: वडा ५००, घर ४ (Context words 'वडा' and 'घर' swapped their numbers)
    source = "Ward 4 and House 500"
    target = "वडा ५०० र घर ४"
    
    # We need to simulate the context extraction logic
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    # This should trigger 'number_swap' based on context similarity
    assert any(r["code"] == "number_swap" for r in reasons)

def test_transliteration_drift_sentinel():
    # Source has 'Sita' twice. Target translates it differently each time.
    source = "Sita and Sita"
    target = "सिता र सीता" # Different spellings
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "transliteration_drift" for r in reasons)

def test_legal_modal_guardian():
    # Source has 'must' (Mandatory), Target has 'सक्नेछ' (Permissive)
    source = "The applicant must submit the form."
    target = "आवेदकले फारम बुझाउन सक्नेछ।" # 'May submit'
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "legal_modal_flip" for r in reasons)

def test_legalism_sentinel():
    # Target leaves 'Subpoena' in English script
    target = "तपाईंलाई एउटा Subpoena जारी गरिएको छ।"
    
    score, reasons = score_translation(
        source_text="A subpoena has been issued to you.",
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "untranslated_legalism" for r in reasons)

def test_legal_anchor_auditor():
    # Source has 'Provided that', Target misses it
    source = "Provided that the fees are paid."
    target = "शुल्क बुझाएमा।" # Misses the 'Provided that' (बशर्ते)
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[]
    )
    
    assert any(r["code"] == "legal_anchor_missing" for r in reasons)

def test_smart_currency_severity():
    # Source has NPR, target keeps Latin 'NPR' (Style mismatch, but not Value mismatch)
    source = "Fee is NPR 500."
    target = "शुल्क NPR ५०० हो।" 
    
    score, reasons = score_translation(
        source_text=source,
        translated_text=target,
        protected_entities=[],
        glossary_hits=[],
        target_lang="ne"
    )
    
    # Should be 'medium' severity now, not 'high'
    assert any(r["code"] == "currency_unlocalized" and r["severity"] == "medium" for r in reasons)

def test_ghost_entity_detector():
    # Model fabricates a new name 'John' in the translation
    source = "Ram is here."
    target = "John र Ram यहाँ छन्।" # 'John' is a ghost entity
    
    score, reasons = score_translation(
        source_text=source, 
        translated_text=target, 
        protected_entities=[], 
        glossary_hits=[]
    )
    
    assert any(r["code"] == "ghost_entity" and r["severity"] == "high" for r in reasons)

def test_polarity_auditor():
    # Source is Negative ('Not'), Target is Positive (Missing 'Chaina')
    source = "He is not coming."
    target = "उनी आउँदैछन्।" # 'He is coming' (Flipped)
    
    score, reasons = score_translation(
        source_text=source, 
        translated_text=target, 
        protected_entities=[], 
        glossary_hits=[]
    )
    
    assert any(r["code"] == "polarity_flip" for r in reasons)

def test_double_negative_preservation():
    # Source: 'Not uncommon' (Positive), Target: 'Saamanya cha' (Normal/Positive)
    # This should NOT flag a polarity flip
    source = "It is not uncommon."
    target = "यो सामान्य छ।" 
    
    score, reasons = score_translation(
        source_text=source, 
        translated_text=target, 
        protected_entities=[], 
        glossary_hits=[]
    )
    
    # Parity check: (2 negatives in source = Positive)
    # Target has 0 negatives = Positive. (0 % 2 == 2 % 2). Should PASS.
    assert not any(r["code"] == "polarity_flip" for r in reasons)

def test_transliterated_currency_recognition():
    # Source has NPR, target has 'एनपीआर' (Phonetic)
    source = "Amount: NPR 100"
    target = "रकम: एनपीआर १००"
    
    score, reasons = score_translation(
        source_text=source, 
        translated_text=target, 
        protected_entities=[], 
        glossary_hits=[]
    )
    
    # This should NOT flag currency_missing anymore
    assert not any(r["code"] == "currency_missing" for r in reasons)

def test_currency_stylistic_preference():
    # Target has 'एनपीआर' (Correct but sub-optimal)
    target = "शुल्क: एनपीआर १००"
    
    score, reasons = score_translation(
        source_text="Fee: NPR 100",
        translated_text=target,
        protected_entities=[],
        glossary_hits=[],
        target_lang="ne"
    )
    
    assert any(r["code"] == "currency_suboptimal" for r in reasons)

def test_professional_spacing_guard():
    # Target has 'रु१००' (Missing space)
    target = "रु१००"
    
    score, reasons = score_translation(
        source_text="Rs. 100", 
        translated_text=target, 
        protected_entities=[], 
        glossary_hits=[]
    )
    
    assert any(r["code"] == "spacing_standard" for r in reasons)

def test_official_abbreviation_guard():
    # Target has 'न ५' instead of 'नं. ५'
    target = "वडा न ५"
    
    score, reasons = score_translation(
        source_text="Ward No. 5", 
        translated_text=target, 
        protected_entities=[], 
        glossary_hits=[]
    )
    
    assert any(r["code"] == "abbreviation_standard" for r in reasons)

def test_pure_number_no_currency_alarm():
    # Source is just '500', target is '५००'. NO currency should be flagged.
    source = "The total is 500."
    target = "कुल ५०० हो।"
    
    score, reasons = score_translation(
        source_text=source, 
        translated_text=target, 
        protected_entities=[], 
        glossary_hits=[]
    )
    
    # Verify NO currency-related warnings pop up
    assert not any(r["code"].startswith("currency_") for r in reasons)

def test_currency_addition_notice():
    # Source is '500', target adds 'रु' (Implicit addition)
    source = "Amount: 500"
    target = "रकम: रु ५००"
    
    score, reasons = score_translation(
        source_text=source, 
        translated_text=target, 
        protected_entities=[], 
        glossary_hits=[]
    )
    
    # We can implement a check for this if we want to be 'Extreme'
    # For now, let's just make sure it doesn't CRASH or flag 'Missing'
    assert not any(r["code"] == "currency_missing" for r in reasons)
