"""Official Alexa Presentation Language (APL 2024.3) document templates and builders.

Designed for Echo Show 8 landscape (1280x800 dp):
- High-contrast dark theme (deep slate/black background with white & vivid status accents)
- Arm's length glanceable (24pt+ text sizes across all elements)
- Max 3 visual elements per card:
  1. Header / Status banner
  2. Hero glanceable content block
  3. Action prompt / Confirmation footer
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Tuple

APL_SPEC_VERSION = "2024.3"

# ---------------------------------------------------------------------------
# 1. Routine Proposal Preview Document
# ---------------------------------------------------------------------------
ROUTINE_PREVIEW_DOCUMENT: Dict[str, Any] = {
    "type": "APL",
    "version": APL_SPEC_VERSION,
    "theme": "dark",
    "description": "Echo Show 8 landscape routine proposal preview card with two-step voice confirmation.",
    "mainTemplate": {
        "parameters": ["payload"],
        "item": {
            "type": "Container",
            "width": "100%",
            "height": "100%",
            "backgroundColor": "#0B0F19",
            "paddingLeft": "48dp",
            "paddingRight": "48dp",
            "paddingTop": "36dp",
            "paddingBottom": "36dp",
            "justifyContent": "spaceBetween",
            "items": [
                # Visual Element 1: Header Banner
                {
                    "type": "Container",
                    "direction": "row",
                    "alignItems": "center",
                    "justifyContent": "spaceBetween",
                    "items": [
                        {
                            "type": "Text",
                            "text": "${payload.header}",
                            "fontSize": "26dp",
                            "fontWeight": "700",
                            "color": "#94A3B8",
                            "maxLines": 1,
                        },
                        {
                            "type": "Frame",
                            "backgroundColor": "#1E293B",
                            "borderRadius": "8dp",
                            "paddingLeft": "16dp",
                            "paddingRight": "16dp",
                            "paddingTop": "6dp",
                            "paddingBottom": "6dp",
                            "item": {
                                "type": "Text",
                                "text": "0 Writes • Proposal",
                                "fontSize": "24dp",
                                "fontWeight": "600",
                                "color": "#FBBF24",
                            },
                        },
                    ],
                },
                # Visual Element 2: Hero Content Block
                {
                    "type": "Frame",
                    "backgroundColor": "#111827",
                    "borderColor": "#38BDF8",
                    "borderWidth": "2dp",
                    "borderRadius": "20dp",
                    "paddingLeft": "36dp",
                    "paddingRight": "36dp",
                    "paddingTop": "28dp",
                    "paddingBottom": "28dp",
                    "item": {
                        "type": "Container",
                        "direction": "column",
                        "justifyContent": "center",
                        "items": [
                            {
                                "type": "Text",
                                "text": "${payload.categoryTitle}",
                                "fontSize": "44dp",
                                "fontWeight": "800",
                                "color": "#38BDF8",
                                "maxLines": 1,
                            },
                            {
                                "type": "Text",
                                "text": "${payload.details}",
                                "fontSize": "32dp",
                                "fontWeight": "600",
                                "color": "#F9FAFB",
                                "maxLines": 2,
                            },
                        ],
                    },
                },
                # Visual Element 3: Action / Voice Prompt Footer
                {
                    "type": "Frame",
                    "backgroundColor": "#1F2937",
                    "borderColor": "#F59E0B",
                    "borderWidth": "2dp",
                    "borderRadius": "14dp",
                    "paddingLeft": "24dp",
                    "paddingRight": "24dp",
                    "paddingTop": "14dp",
                    "paddingBottom": "14dp",
                    "item": {
                        "type": "Text",
                        "text": "${payload.voicePrompt}",
                        "fontSize": "28dp",
                        "fontWeight": "700",
                        "color": "#FEF08A",
                        "textAlign": "center",
                        "maxLines": 1,
                    },
                },
            ],
        },
    },
}

# ---------------------------------------------------------------------------
# 2. Caregiver Timeline Summary Document
# ---------------------------------------------------------------------------
CAREGIVER_SUMMARY_DOCUMENT: Dict[str, Any] = {
    "type": "APL",
    "version": APL_SPEC_VERSION,
    "theme": "dark",
    "description": "Echo Show 8 landscape caregiver wellness timeline card summarizing elder daily routines.",
    "mainTemplate": {
        "parameters": ["payload"],
        "item": {
            "type": "Container",
            "width": "100%",
            "height": "100%",
            "backgroundColor": "#0B0F19",
            "paddingLeft": "48dp",
            "paddingRight": "48dp",
            "paddingTop": "36dp",
            "paddingBottom": "36dp",
            "justifyContent": "spaceBetween",
            "items": [
                # Visual Element 1: Header Banner
                {
                    "type": "Container",
                    "direction": "row",
                    "alignItems": "center",
                    "justifyContent": "spaceBetween",
                    "items": [
                        {
                            "type": "Text",
                            "text": "${payload.header}",
                            "fontSize": "26dp",
                            "fontWeight": "700",
                            "color": "#94A3B8",
                            "maxLines": 1,
                        },
                        {
                            "type": "Frame",
                            "backgroundColor": "#064E3B",
                            "borderRadius": "8dp",
                            "paddingLeft": "16dp",
                            "paddingRight": "16dp",
                            "paddingTop": "6dp",
                            "paddingBottom": "6dp",
                            "item": {
                                "type": "Text",
                                "text": "Caregiver Timeline",
                                "fontSize": "24dp",
                                "fontWeight": "600",
                                "color": "#34D399",
                            },
                        },
                    ],
                },
                # Visual Element 2: Hero Metric Block
                {
                    "type": "Frame",
                    "backgroundColor": "#0F291E",
                    "borderColor": "#10B981",
                    "borderWidth": "2dp",
                    "borderRadius": "20dp",
                    "paddingLeft": "36dp",
                    "paddingRight": "36dp",
                    "paddingTop": "28dp",
                    "paddingBottom": "28dp",
                    "item": {
                        "type": "Container",
                        "direction": "column",
                        "justifyContent": "center",
                        "items": [
                            {
                                "type": "Text",
                                "text": "${payload.completionRate}",
                                "fontSize": "48dp",
                                "fontWeight": "800",
                                "color": "#10B981",
                                "maxLines": 1,
                            },
                            {
                                "type": "Text",
                                "text": "${payload.summaryDetails}",
                                "fontSize": "30dp",
                                "fontWeight": "600",
                                "color": "#FFFFFF",
                                "maxLines": 2,
                            },
                        ],
                    },
                },
                # Visual Element 3: Timeline Status Footer
                {
                    "type": "Frame",
                    "backgroundColor": "#1E293B",
                    "borderRadius": "14dp",
                    "paddingLeft": "24dp",
                    "paddingRight": "24dp",
                    "paddingTop": "14dp",
                    "paddingBottom": "14dp",
                    "item": {
                        "type": "Text",
                        "text": "${payload.timelineStatus}",
                        "fontSize": "26dp",
                        "fontWeight": "600",
                        "color": "#CBD5E1",
                        "textAlign": "center",
                        "maxLines": 1,
                    },
                },
            ],
        },
    },
}

# ---------------------------------------------------------------------------
# 3. Caregiver Shift Handoff Confirmation Document
# ---------------------------------------------------------------------------
HANDOFF_CONFIRM_DOCUMENT: Dict[str, Any] = {
    "type": "APL",
    "version": APL_SPEC_VERSION,
    "theme": "dark",
    "description": "Echo Show 8 landscape shift handoff card with two-step safety gate status.",
    "mainTemplate": {
        "parameters": ["payload"],
        "item": {
            "type": "Container",
            "width": "100%",
            "height": "100%",
            "backgroundColor": "#0B0F19",
            "paddingLeft": "48dp",
            "paddingRight": "48dp",
            "paddingTop": "36dp",
            "paddingBottom": "36dp",
            "justifyContent": "spaceBetween",
            "items": [
                # Visual Element 1: Header Banner
                {
                    "type": "Container",
                    "direction": "row",
                    "alignItems": "center",
                    "justifyContent": "spaceBetween",
                    "items": [
                        {
                            "type": "Text",
                            "text": "${payload.header}",
                            "fontSize": "26dp",
                            "fontWeight": "700",
                            "color": "#818CF8",
                            "maxLines": 1,
                        },
                        {
                            "type": "Frame",
                            "backgroundColor": "#312E81",
                            "borderRadius": "8dp",
                            "paddingLeft": "16dp",
                            "paddingRight": "16dp",
                            "paddingTop": "6dp",
                            "paddingBottom": "6dp",
                            "item": {
                                "type": "Text",
                                "text": "Shift Handoff",
                                "fontSize": "24dp",
                                "fontWeight": "600",
                                "color": "#C7D2FE",
                            },
                        },
                    ],
                },
                # Visual Element 2: Hero Handover Notes Block
                {
                    "type": "Frame",
                    "backgroundColor": "#1E1B4B",
                    "borderColor": "#6366F1",
                    "borderWidth": "2dp",
                    "borderRadius": "20dp",
                    "paddingLeft": "36dp",
                    "paddingRight": "36dp",
                    "paddingTop": "28dp",
                    "paddingBottom": "28dp",
                    "item": {
                        "type": "Container",
                        "direction": "column",
                        "justifyContent": "center",
                        "items": [
                            {
                                "type": "Text",
                                "text": "${payload.seniorContext}",
                                "fontSize": "40dp",
                                "fontWeight": "800",
                                "color": "#FFFFFF",
                                "maxLines": 1,
                            },
                            {
                                "type": "Text",
                                "text": "${payload.notes}",
                                "fontSize": "28dp",
                                "fontWeight": "600",
                                "color": "#E0E7FF",
                                "maxLines": 2,
                            },
                        ],
                    },
                },
                # Visual Element 3: Verification Status Footer
                {
                    "type": "Frame",
                    "backgroundColor": "#1F2937",
                    "borderColor": "#10B981",
                    "borderWidth": "2dp",
                    "borderRadius": "14dp",
                    "paddingLeft": "24dp",
                    "paddingRight": "24dp",
                    "paddingTop": "14dp",
                    "paddingBottom": "14dp",
                    "item": {
                        "type": "Text",
                        "text": "${payload.statusText}",
                        "fontSize": "26dp",
                        "fontWeight": "700",
                        "color": "#6EE7B7",
                        "textAlign": "center",
                        "maxLines": 1,
                    },
                },
            ],
        },
    },
}

# ---------------------------------------------------------------------------
# 4. Gentle Missed-Routine Document
# ---------------------------------------------------------------------------
MISSED_ROUTINE_DOCUMENT: Dict[str, Any] = {
    "type": "APL",
    "version": APL_SPEC_VERSION,
    "theme": "dark",
    "description": "Echo Show 8 landscape non-intrusive reminder for elder scheduled routine windows.",
    "mainTemplate": {
        "parameters": ["payload"],
        "item": {
            "type": "Container",
            "width": "100%",
            "height": "100%",
            "backgroundColor": "#0B0F19",
            "paddingLeft": "48dp",
            "paddingRight": "48dp",
            "paddingTop": "36dp",
            "paddingBottom": "36dp",
            "justifyContent": "spaceBetween",
            "items": [
                # Visual Element 1: Header Banner
                {
                    "type": "Container",
                    "direction": "row",
                    "alignItems": "center",
                    "justifyContent": "spaceBetween",
                    "items": [
                        {
                            "type": "Text",
                            "text": "${payload.header}",
                            "fontSize": "26dp",
                            "fontWeight": "700",
                            "color": "#F59E0B",
                            "maxLines": 1,
                        },
                        {
                            "type": "Frame",
                            "backgroundColor": "#451A03",
                            "borderRadius": "8dp",
                            "paddingLeft": "16dp",
                            "paddingRight": "16dp",
                            "paddingTop": "6dp",
                            "paddingBottom": "6dp",
                            "item": {
                                "type": "Text",
                                "text": "Gentle Check-in",
                                "fontSize": "24dp",
                                "fontWeight": "600",
                                "color": "#FCD34D",
                            },
                        },
                    ],
                },
                # Visual Element 2: Hero Reminder Block
                {
                    "type": "Frame",
                    "backgroundColor": "#291504",
                    "borderColor": "#F59E0B",
                    "borderWidth": "2dp",
                    "borderRadius": "20dp",
                    "paddingLeft": "36dp",
                    "paddingRight": "36dp",
                    "paddingTop": "28dp",
                    "paddingBottom": "28dp",
                    "item": {
                        "type": "Container",
                        "direction": "column",
                        "justifyContent": "center",
                        "items": [
                            {
                                "type": "Text",
                                "text": "${payload.routineTitle}",
                                "fontSize": "42dp",
                                "fontWeight": "800",
                                "color": "#FBBF24",
                                "maxLines": 1,
                            },
                            {
                                "type": "Text",
                                "text": "${payload.windowTime}",
                                "fontSize": "30dp",
                                "fontWeight": "600",
                                "color": "#FFFFFF",
                                "maxLines": 2,
                            },
                        ],
                    },
                },
                # Visual Element 3: Ambient Voice Prompt Footer
                {
                    "type": "Frame",
                    "backgroundColor": "#1E293B",
                    "borderRadius": "14dp",
                    "paddingLeft": "24dp",
                    "paddingRight": "24dp",
                    "paddingTop": "14dp",
                    "paddingBottom": "14dp",
                    "item": {
                        "type": "Text",
                        "text": "${payload.voicePrompt}",
                        "fontSize": "26dp",
                        "fontWeight": "700",
                        "color": "#FEF08A",
                        "textAlign": "center",
                        "maxLines": 1,
                    },
                },
            ],
        },
    },
}


# ---------------------------------------------------------------------------
# High-Level Card Builders (Returning APL + Fallback Display)
# ---------------------------------------------------------------------------

def build_routine_preview_card(
    senior_id: str,
    senior_name: str,
    category: str,
    details: str,
    voice_prompt: str,
    transaction_id: str = "",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build genuine APL output and plain display fallback for routine preview."""
    category_icons = {
        "hydration": "💧 Hydration",
        "meal": "🍽️ Meal",
        "vitamins": "💊 Vitamins",
        "mobility": "🚶 Mobility",
        "walk": "🌿 Fresh Air Walk",
        "wellness": "☀️ Wellness Check-in",
    }
    cat_title = category_icons.get(category.lower(), f"📋 {category.title()}")
    desc = details or f"{category.title()} completed"

    datasources = {
        "payload": {
            "header": f"{senior_name} • Routine Proposal",
            "categoryTitle": cat_title,
            "details": desc,
            "voicePrompt": f"Say: 'Alexa, confirm' to save ID {transaction_id[-6:]}" if transaction_id else "Say: 'Alexa, confirm' to record",
            "senior_id": senior_id,
            "transaction_id": transaction_id,
        }
    }

    apl = {
        "document": ROUTINE_PREVIEW_DOCUMENT,
        "datasources": datasources,
    }

    display = {
        "title": f"Proposed: {category.title()}",
        "lines": [
            f"{senior_name} ({senior_id})",
            desc,
            voice_prompt or "Say 'Alexa, confirm' to commit",
        ],
    }

    return apl, display


def build_caregiver_summary_card(
    senior_id: str,
    senior_name: str,
    date: str,
    completion_percentage: int,
    completed_count: int,
    total_count: int,
    next_slot: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build genuine APL output and plain display fallback for caregiver timeline summary."""
    rate_str = f"{completion_percentage}% Completed"
    details_str = f"{completed_count} of {total_count} Daily Living Routines Verified"
    next_str = f"Next Scheduled: {next_slot}" if next_slot else "All Scheduled Routines Up to Date"

    datasources = {
        "payload": {
            "header": f"{senior_name} • Timeline ({date})",
            "completionRate": rate_str,
            "summaryDetails": details_str,
            "timelineStatus": next_str,
            "senior_id": senior_id,
            "date": date,
        }
    }

    apl = {
        "document": CAREGIVER_SUMMARY_DOCUMENT,
        "datasources": datasources,
    }

    display = {
        "title": f"{senior_name} Wellness Timeline",
        "lines": [
            f"Date: {date} • {rate_str}",
            details_str,
            next_str,
        ],
    }

    return apl, display


def build_handoff_confirm_card(
    senior_id: str,
    senior_name: str,
    departing: str,
    incoming: str,
    notes: str,
    is_confirmed: bool,
    transaction_id: str = "",
    spoken_prompt: str = "",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build genuine APL output and plain display fallback for shift handoff."""
    status_label = "✅ Shift Handed Off to SQLite" if is_confirmed else "Say: 'Alexa, confirm' to commit handoff"

    datasources = {
        "payload": {
            "header": f"Shift Handoff • {departing} → {incoming}",
            "seniorContext": f"Senior: {senior_name}",
            "notes": notes or "All morning routines completed; reminded for afternoon hydration.",
            "statusText": status_label,
            "senior_id": senior_id,
            "transaction_id": transaction_id,
            "confirmed": is_confirmed,
        }
    }

    apl = {
        "document": HANDOFF_CONFIRM_DOCUMENT,
        "datasources": datasources,
    }

    display = {
        "title": f"Shift Handoff: {departing} → {incoming}",
        "lines": [
            f"Senior: {senior_name}",
            notes or "Caregiver shift transition",
            status_label,
        ],
    }

    return apl, display


def build_missed_routine_card(
    senior_id: str,
    senior_name: str,
    routine_name: str,
    display_time: str,
    urgency_level: str = "medium",
    voice_prompt: str = "",
    is_missed: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build genuine APL output and plain display fallback for missed routine alerts."""
    routine_title = f"{routine_name.title()} Window"
    time_info = f"Scheduled: {display_time}" if display_time else "Scheduled for Today"
    prompt = voice_prompt or f"Whenever you're ready, say: 'Alexa, log {routine_name.lower()}'"

    datasources = {
        "payload": {
            "header": f"Gentle Reminder • {senior_name}",
            "routineTitle": routine_title,
            "windowTime": time_info,
            "voicePrompt": prompt,
            "urgency": urgency_level,
            "is_missed": is_missed,
            "senior_id": senior_id,
        }
    }

    apl = {
        "document": MISSED_ROUTINE_DOCUMENT,
        "datasources": datasources,
    }

    display = {
        "title": f"Reminder: {routine_name.title()}",
        "lines": [
            f"{senior_name} • {time_info}",
            f"Urgency: {urgency_level.upper()}",
            prompt,
        ],
    }

    return apl, display


def save_apl_documents(target_dir: str = "docs/apl") -> None:
    """Save all 4 official APL documents and matching sample datasources to target directory."""
    os.makedirs(target_dir, exist_ok=True)

    catalog = [
        ("routine_preview", ROUTINE_PREVIEW_DOCUMENT, {
            "payload": {
                "header": "Margaret Vance • Routine Proposal",
                "categoryTitle": "💧 Hydration",
                "details": "500ml Water recorded by senior_voice",
                "voicePrompt": "Say: 'Alexa, confirm' to record to daily timeline",
                "senior_id": "margaret_01",
                "transaction_id": "tx_sample_123456",
            }
        }),
        ("caregiver_summary", CAREGIVER_SUMMARY_DOCUMENT, {
            "payload": {
                "header": "Margaret Vance • Timeline (2026-10-20)",
                "completionRate": "75% Completed",
                "summaryDetails": "3 of 4 Daily Living Routines Verified",
                "timelineStatus": "Next Scheduled: Dinner (6:00 PM)",
                "senior_id": "margaret_01",
                "date": "2026-10-20",
            }
        }),
        ("handoff_confirm", HANDOFF_CONFIRM_DOCUMENT, {
            "payload": {
                "header": "Shift Handoff • David → Sarah",
                "seniorContext": "Senior: Margaret Vance",
                "notes": "Margaret completed 20m activity in garden; afternoon water reminder given.",
                "statusText": "✅ Shift Handed Off to SQLite",
                "senior_id": "margaret_01",
                "transaction_id": "tx_sample_789012",
                "confirmed": True,
            }
        }),
        ("missed_routine", MISSED_ROUTINE_DOCUMENT, {
            "payload": {
                "header": "Gentle Reminder • Margaret Vance",
                "routineTitle": "Afternoon Hydration Window",
                "windowTime": "Scheduled: 2:00 PM - 4:00 PM",
                "voicePrompt": "Whenever you're ready, say: 'Alexa, I drank water'",
                "urgency": "medium",
                "is_missed": True,
                "senior_id": "margaret_01",
            }
        }),
    ]

    for name, doc, sample_data in catalog:
        # 1. Document file (for APL Document tab in Alexa Developer Console)
        doc_path = os.path.join(target_dir, f"{name}.json")
        with open(doc_path, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2)

        # 2. Datasource file (for Data Sources tab in Alexa Developer Console)
        data_path = os.path.join(target_dir, f"{name}_datasource.json")
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(sample_data, f, indent=2)
