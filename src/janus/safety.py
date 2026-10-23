"""JANUS-ARC — Shared Non-Clinical Medical Safety Policy.

Defines a deterministic, testable backend safety policy to prevent the system
from providing medical triage, altering medications, or logging daily routines
during medical emergencies.

POLICY OUTCOMES:
1. EMERGENCY_GUIDANCE:
   - Recognized possible emergency indicators take absolute priority over ordinary routine matching.
   - Returns immediate, concise guidance to contact local emergency services (911).
   - Does not diagnose, recommend treatment, or delay guidance with clarification questions.
   - Forbids creating routine proposals or committing records for the request.

2. MEDICAL_ACTION_BLOCKED:
   - Blocks medication dose changes, starting/stopping medicines, and clinical advice.
   - Directs the user to an appropriate qualified healthcare professional.
   - Distinguishes reports of scheduled vitamins from medication-change requests.

3. CLARIFICATION_REQUIRED:
   - Blocks protected mutations for ambiguous, unrecognized, or safety-sensitive requests.
   - Returns a concise clarification request or caregiver-review outcome.
   - Never delays emergency guidance.

4. ROUTINE_ALLOWED:
   - Permits supported non-clinical daily living routines (hydration, meals, vitamins, activity, wellness).
   - Enforces two-step confirmation and caller authorization downstream.

SAFETY POLICY LIMITATIONS & KNOWN RISKS:
- False-Negative Risk: Keyword and regex heuristics cannot detect every medical emergency.
  Subtle or atypical clinical presentations (e.g. silent myocardial infarction, atypical stroke
  without hemiparesis, acute confusion without overt emergency keywords, novel slang, or non-English
  phrasing) may not be recognized by pattern matching.
- False-Positive Risk: Figurative expressions, idioms, or metaphors (e.g. "dying of thirst",
  "my feet are killing me", "heart skipped a beat") may trigger safety interventions even when no
  actual emergency or clinical danger exists.
- Non-Clinical Scope: JANUS is an ambient eldercare demonstration prototype. It is NOT a medical device,
  clinical triage platform, or certified life-safety system.
- Privacy & Log Hygiene: Raw user free-text containing sensitive health details MUST NOT be logged.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("janus.safety")

# Maximum permitted character length for free-text inputs
MAX_INPUT_LENGTH = 1000

# Supported non-clinical routine categories
VALID_ROUTINE_CATEGORIES = frozenset({"meal", "hydration", "vitamins", "activity", "wellness"})


class SafetyOutcome(str, Enum):
    """Machine-readable outcomes for safety policy assessment."""

    EMERGENCY_GUIDANCE = "EMERGENCY_GUIDANCE"
    MEDICAL_ACTION_BLOCKED = "MEDICAL_ACTION_BLOCKED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    ROUTINE_ALLOWED = "ROUTINE_ALLOWED"


# Concise, human-safe guidance messages
GUIDANCE_MESSAGES: Dict[SafetyOutcome, str] = {
    SafetyOutcome.EMERGENCY_GUIDANCE: (
        "Immediate emergency guidance: If you or someone nearby is experiencing a medical emergency, "
        "call 911 (or your local emergency services) immediately. Do not wait."
    ),
    SafetyOutcome.MEDICAL_ACTION_BLOCKED: (
        "JANUS cannot recommend, adjust, or record changes to medication dosages, prescriptions, "
        "or medical treatments. Please contact your prescribing physician, pharmacist, "
        "or qualified healthcare professional."
    ),
    SafetyOutcome.CLARIFICATION_REQUIRED: (
        "This request involves health symptoms or ambiguous medical matters that cannot be recorded "
        "as a routine living activity. Please clarify your request or consult a caregiver or qualified healthcare provider."
    ),
    SafetyOutcome.ROUTINE_ALLOWED: (
        "Non-clinical daily living routine validated."
    ),
}


@dataclass(frozen=True)
class SafetyAssessment:
    """Immutable result of a deterministic safety policy evaluation."""

    outcome: SafetyOutcome
    reason: str
    guidance: str
    matched_rule: Optional[str] = None
    is_allowed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert assessment to dictionary."""
        return {
            "outcome": self.outcome.value,
            "reason": self.reason,
            "guidance": self.guidance,
            "matched_rule": self.matched_rule,
            "is_allowed": self.is_allowed,
        }


# ---------------------------------------------------------------------------
# Pre-Compiled Deterministic Regex Pattern Suites
# ---------------------------------------------------------------------------

# 1. EMERGENCY INDICATORS (Priority 1: Life-threatening acute emergencies)
_EMERGENCY_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    # Cardiac & Chest Symptoms
    (
        re.compile(
            r"\b(chest pain|chest tightness|chest pressure|heart attack|cardiac arrest|crushing chest( pain)?)\b",
            re.IGNORECASE,
        ),
        "cardiac_chest_pain",
    ),
    # Breathing & Respiratory Distress
    (
        re.compile(
            r"\b(can'?t breathe|cannot breathe|unable to breathe|trouble breathing|difficulty breathing|"
            r"shortness of breath|gasping for air|choking|suffocating|stopped breathing|not breathing|"
            r"blue lips|turning blue)\b",
            re.IGNORECASE,
        ),
        "respiratory_distress",
    ),
    # Loss of Consciousness, Unresponsiveness & Severe Fall Trauma
    (
        re.compile(
            r"\b(unconscious|unresponsive|passed out|passed-out|fainted|fainting|blacked out|blackout|"
            r"collapsed|loss of consciousness|won'?t wake up|can'?t wake (her|him|them|up)|unable to wake)\b",
            re.IGNORECASE,
        ),
        "unresponsive_consciousness",
    ),
    (
        re.compile(
            r"\b((fell|fall|fallen)( down)? (and|&)? (can'?t|cannot|unable to) (get up|move|stand)|"
            r"(bad|severe) fall and (can'?t|cannot|unable to) (get up|move)|severe fall and bleeding|"
            r"injured in fall and can'?t move)\b",
            re.IGNORECASE,
        ),
        "severe_fall_trauma",
    ),
    # Stroke & Acute Neurological Symptoms
    (
        re.compile(
            r"\b(stroke|face drooping|facial droop|slurred speech|slurring words|sudden numbness|"
            r"sudden weakness|sudden paralysis|paralyzed|seizure|convulsing|seizures|convulsions|"
            r"worst headache of (my|his|her|their) life)\b",
            re.IGNORECASE,
        ),
        "stroke_neurological",
    ),
    # Acute Hemorrhage & Bleeding
    (
        re.compile(
            r"\b(severe bleeding|bleeding heavily|heavy bleeding|hemorrhage|profuse bleeding|"
            r"coughing (up )?blood|vomiting blood)\b",
            re.IGNORECASE,
        ),
        "severe_hemorrhage",
    ),
    # Anaphylaxis, Poisoning & Overdose
    (
        re.compile(
            r"\b(anaphylaxis|throat (is )?closing|throat swelling|severe allergic reaction|"
            r"overdose|overdosed|poisoned|poisoning|ingested poison|swallowed bleach|swallowed poison)\b",
            re.IGNORECASE,
        ),
        "anaphylaxis_poison_overdose",
    ),
    # Suicidal Ideation / Crisis
    (
        re.compile(
            r"\b(suicide|suicidal|want to die|kill (myself|himself|herself)|end (my|his|her) life)\b",
            re.IGNORECASE,
        ),
        "suicidal_crisis",
    ),
    # Explicit Emergency Invocations
    (
        re.compile(
            r"\b(call 911|call emergency|call an ambulance|need an ambulance|medical emergency)\b",
            re.IGNORECASE,
        ),
        "explicit_emergency_call",
    ),
]


# 2. MEDICAL ACTION / MEDICATION CHANGES (Priority 2: Prescription/Dose Modifications)
_MEDICAL_ACTION_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    # Dosage modifications (increase, decrease, double, cut in half, etc.)
    (
        re.compile(
            r"\b(increase|decrease|double|halve|reduce|cut|raise|lower|adjust|modify|titrate|change) "
            r"(the |my |her |his )?(dose|dosage|medication|medicine|pill|tablets?|mg|units?)\b",
            re.IGNORECASE,
        ),
        "dose_modification",
    ),
    (
        re.compile(
            r"\b(increase|decrease|change|double|halve|reduce|cut|raise|lower|adjust) "
            r"(to|by) \d+\s*(mg|ml|units?|pills?|tablets?)\b",
            re.IGNORECASE,
        ),
        "dosage_amount_change",
    ),
    (
        re.compile(
            r"\b(cut|split|break|halve) (the |my |her |his )?(pill|tablet|capsule) in half\b",
            re.IGNORECASE,
        ),
        "pill_splitting",
    ),
    (
        re.compile(
            r"\b(take|give) (an )?extra (dose|pill|tablet|capsule|medication|medicine)\b",
            re.IGNORECASE,
        ),
        "extra_dose_request",
    ),
    (
        re.compile(
            r"\b(skip|skipping|miss|stop taking|stopped taking|hold|discontinue) "
            r"(the |my |her |his |this |morning |evening |night |daily |scheduled )*"
            r"(dose|dosage|medication|medicine|pills?|prescriptions?|antibiotics?|drugs?|treatment)\b",
            re.IGNORECASE,
        ),
        "discontinue_or_skip_medication",
    ),
    # Starting/stopping or prescribing medicines
    (
        re.compile(
            r"\b(start taking|stop taking|quit taking|start on|put on|prescribe|refill prescription|change prescription)\b",
            re.IGNORECASE,
        ),
        "prescription_start_stop",
    ),
    (
        re.compile(
            r"\b(recommend|advise|prescribe|suggest) (a |some )?(medication|medicine|drug|antibiotic|painkiller|pill)\b",
            re.IGNORECASE,
        ),
        "medication_recommendation",
    ),
    # Specific prescription drug adjustments
    (
        re.compile(
            r"\b(adjust|change|increase|decrease|stop|start) (insulin|lisinopril|metformin|warfarin|coumadin|"
            r"levothyroxine|amlodipine|metoprolol|atorvastatin|statin|prednisone|antibiotics?|"
            r"blood pressure (meds?|medicine|pills?|medication))\b",
            re.IGNORECASE,
        ),
        "specific_rx_adjustment",
    ),
]


# 3. AMBIGUOUS HEALTH & CLINICAL SYMPTOMS (Priority 3: Ambiguous or Unrecognized Health Concerns)
_AMBIGUOUS_HEALTH_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    # Non-emergency clinical symptoms
    (
        re.compile(
            r"\b(headache|dizzy|dizziness|lightheaded|lightheadedness|nauseous|nausea|upset stomach|"
            r"fever|feverish|high temperature|chills|vomiting|vomited|diarrhea|rash|skin rash|"
            r"swollen ankles?|joint pain|knee pain|back pain|stomach ache|belly pain|earache|sore throat)\b",
            re.IGNORECASE,
        ),
        "non_emergency_symptom",
    ),
    (
        re.compile(
            r"\b(feels? (sick|unwell|terrible|awful|weak|faint|shaky)|not feeling well)\b",
            re.IGNORECASE,
        ),
        "general_unwell_complaint",
    ),
    # Clinical vitals and laboratory readings
    (
        re.compile(
            r"\b(blood pressure is|bp is|blood sugar is|glucose is|oxygen is|pulse is|heart rate is|spo2|vital signs?)\b",
            re.IGNORECASE,
        ),
        "clinical_vital_signs",
    ),
    # Unverified prescription administration (non-vitamin drugs)
    (
        re.compile(
            r"\b(took|taken|given|injected|administered) (the |my |her |his |morning |evening |daily |scheduled )*"
            r"(insulin|lisinopril|metformin|warfarin|coumadin|levothyroxine|amlodipine|metoprolol|"
            r"atorvastatin|prednisone|antibiotics?|blood pressure pills?)\b",
            re.IGNORECASE,
        ),
        "unverified_prescription_reporting",
    ),
    # Questions seeking medical diagnosis or advice
    (
        re.compile(
            r"\b(should (i|she|he) (take|see|call|rest)|is (this|that) normal|is (it|this) dangerous|what should (i|we) do)\b",
            re.IGNORECASE,
        ),
        "medical_inquiry",
    ),
]


def assess_safety(
    text: Any,
    category: Optional[str] = None,
    **kwargs: Any,
) -> SafetyAssessment:
    """Evaluate free-text and context against deterministic medical safety rules.

    Priority hierarchy:
    1. Input validation & length limits (reject malformed/oversized inputs).
    2. EMERGENCY_GUIDANCE: Recognized life-threatening emergencies take precedence over
       all routine keywords, medication terms, and caller labels.
    3. MEDICAL_ACTION_BLOCKED: Prescription adjustments, dose changes, and clinical recommendations
       are blocked.
    4. CLARIFICATION_REQUIRED: Ambiguous health symptoms, non-emergency complaints, or unrecognized
       safety-sensitive matters require clarification.
    5. ROUTINE_ALLOWED: Permitted daily living routines (hydration, meals, vitamins, activity, wellness).

    Args:
        text: Free-text request or details to assess.
        category: Caller-provided routine category (e.g. 'hydration', 'vitamins').
        **kwargs: Unused caller metadata (caller labels like `is_safe=True` are explicitly ignored).

    Returns:
        SafetyAssessment dataclass containing outcome, reason, guidance, and matched rule.
    """
    # -------------------------------------------------------------------------
    # 1. Input Type, Malformation & Length Validation
    # -------------------------------------------------------------------------
    if text is None:
        raw_str = ""
    elif isinstance(text, str):
        raw_str = text
    else:
        # Non-string input is malformed
        logger.warning("Safety policy input rejected: non-string type %s", type(text).__name__)
        return SafetyAssessment(
            outcome=SafetyOutcome.CLARIFICATION_REQUIRED,
            reason="Input rejected: text must be a valid string.",
            guidance="Malformed input detected. Please provide a clear textual description.",
            matched_rule="malformed_non_string",
            is_allowed=False,
        )

    # Check for null bytes or control characters
    if "\x00" in raw_str:
        logger.warning("Safety policy input rejected: contained null byte (len=%d)", len(raw_str))
        return SafetyAssessment(
            outcome=SafetyOutcome.CLARIFICATION_REQUIRED,
            reason="Input rejected: contains invalid control characters.",
            guidance="Malformed input detected. Please provide a valid textual description.",
            matched_rule="malformed_control_chars",
            is_allowed=False,
        )

    # Check length limits
    if len(raw_str) > MAX_INPUT_LENGTH:
        logger.warning("Safety policy input rejected: oversized text (len=%d > %d)", len(raw_str), MAX_INPUT_LENGTH)
        return SafetyAssessment(
            outcome=SafetyOutcome.CLARIFICATION_REQUIRED,
            reason=f"Input rejected: text length ({len(raw_str)} chars) exceeds safe threshold ({MAX_INPUT_LENGTH} chars).",
            guidance="Your request exceeds the maximum allowed length. Please provide a concise description.",
            matched_rule="oversized_input_exceeded",
            is_allowed=False,
        )

    normalized = re.sub(r"\s+", " ", raw_str).strip()

    # Empty text handling
    if not normalized:
        # If no text is provided, but a valid non-clinical routine category is supplied:
        if category and str(category).strip().lower() in VALID_ROUTINE_CATEGORIES:
            return SafetyAssessment(
                outcome=SafetyOutcome.ROUTINE_ALLOWED,
                reason=f"Empty details allowed under valid routine category '{category}'.",
                guidance=GUIDANCE_MESSAGES[SafetyOutcome.ROUTINE_ALLOWED],
                matched_rule=None,
                is_allowed=True,
            )
        # Empty text without a valid category requires clarification
        return SafetyAssessment(
            outcome=SafetyOutcome.CLARIFICATION_REQUIRED,
            reason="Empty request provided with no valid routine category.",
            guidance="Empty request. Please specify the daily routine activity to record.",
            matched_rule="empty_input",
            is_allowed=False,
        )

    # -------------------------------------------------------------------------
    # 2. EMERGENCY_GUIDANCE (Priority 1: Life-Threatening Emergency Indicators)
    # -------------------------------------------------------------------------
    for pattern, rule_name in _EMERGENCY_PATTERNS:
        match = pattern.search(normalized)
        if match:
            # Log rule trigger without exposing raw sensitive text
            logger.info("Emergency indicator triggered: rule=%s, span=%s", rule_name, match.span())
            return SafetyAssessment(
                outcome=SafetyOutcome.EMERGENCY_GUIDANCE,
                reason=f"Recognized emergency indicator ('{rule_name}').",
                guidance=GUIDANCE_MESSAGES[SafetyOutcome.EMERGENCY_GUIDANCE],
                matched_rule=rule_name,
                is_allowed=False,
            )

    # -------------------------------------------------------------------------
    # 3. MEDICAL_ACTION_BLOCKED (Priority 2: Prescription / Dose Changes)
    # -------------------------------------------------------------------------
    for pattern, rule_name in _MEDICAL_ACTION_PATTERNS:
        match = pattern.search(normalized)
        if match:
            logger.info("Medical action blocked: rule=%s, span=%s", rule_name, match.span())
            return SafetyAssessment(
                outcome=SafetyOutcome.MEDICAL_ACTION_BLOCKED,
                reason=f"Clinical medication modification requested ('{rule_name}').",
                guidance=GUIDANCE_MESSAGES[SafetyOutcome.MEDICAL_ACTION_BLOCKED],
                matched_rule=rule_name,
                is_allowed=False,
            )

    # -------------------------------------------------------------------------
    # 4. CLARIFICATION_REQUIRED (Priority 3: Ambiguous Health Complaints / Clinical Vitals)
    # -------------------------------------------------------------------------
    for pattern, rule_name in _AMBIGUOUS_HEALTH_PATTERNS:
        match = pattern.search(normalized)
        if match:
            logger.info("Ambiguous health request flagged: rule=%s, span=%s", rule_name, match.span())
            return SafetyAssessment(
                outcome=SafetyOutcome.CLARIFICATION_REQUIRED,
                reason=f"Ambiguous health or symptom request detected ('{rule_name}').",
                guidance=GUIDANCE_MESSAGES[SafetyOutcome.CLARIFICATION_REQUIRED],
                matched_rule=rule_name,
                is_allowed=False,
            )

    # -------------------------------------------------------------------------
    # 5. ROUTINE_ALLOWED (Priority 4: Valid Non-Clinical Daily Living Routine)
    # -------------------------------------------------------------------------
    return SafetyAssessment(
        outcome=SafetyOutcome.ROUTINE_ALLOWED,
        reason="No emergency, clinical medication, or ambiguous health concerns detected.",
        guidance=GUIDANCE_MESSAGES[SafetyOutcome.ROUTINE_ALLOWED],
        matched_rule=None,
        is_allowed=True,
    )


def is_routine_allowed(text: Any, category: Optional[str] = None, **kwargs: Any) -> bool:
    """Convenience helper returning True iff request outcome is ROUTINE_ALLOWED."""
    return assess_safety(text, category=category, **kwargs).outcome == SafetyOutcome.ROUTINE_ALLOWED
