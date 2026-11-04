"""
VF Logistics AI Investigation Agent - Gemini 3.5 Flash-Lite
Conducts deep-dive investigations into flagged cases using multi-step reasoning.

This agent uses Gemini 3.5 Flash-Lite for cost-efficient summarization and
report generation, while heavy-lifting agents (document, fraud, compliance)
use Gemini 3.5 Flash for complex multimodal reasoning.

"""

import json
import os
from typing import Any

from google import genai
from google.genai import types

from ._common import Timer, envelope, parse_model_json, extract_tokens
import config as model_config

PROJECT_ID = os.getenv("PROJECT_ID", "project-93ded24f-21c3-4f1b-a7d")
LOCATION = os.getenv("LOCATION", "global")

client = genai.Client(
    vertexai=True,
    project=PROJECT_ID,
    location=LOCATION
)

# Investigation agent uses Flash-Lite for cost-efficient summarization
# Other agents use Flash for heavy multimodal/reasoning tasks
MODEL_ID = "gemini-3.5-flash-lite"

def get_model_id():
    """Investigation agent always uses Flash-Lite for cost efficiency."""
    return MODEL_ID  # Fixed to flash-lite, not configurable

INVESTIGATION_PROMPT = """
You are a senior fraud investigator AI for VF Logistics. Your role is to conduct 
thorough investigations of flagged shipments and entities.

INVESTIGATION METHODOLOGY:
1. EVIDENCE GATHERING
   - Collect all related shipments and transactions
   - Identify connected parties and relationships
   - Map timeline of suspicious activities

2. PATTERN ANALYSIS
   - Look for recurring fraud patterns
   - Identify network of potentially colluding parties
   - Compare against known fraud typologies

3. RISK ASSESSMENT
   - Calculate total exposure and potential losses
   - Assess likelihood of organized fraud vs isolated incident
   - Evaluate systemic vulnerabilities exploited

4. RECOMMENDATION ENGINE
   - Prioritize investigation actions
   - Suggest preventive controls
   - Recommend escalation if warranted

OUTPUT FORMAT (JSON):
- investigation_id: unique ID for this investigation
- summary: executive summary of findings
- evidence: key evidence items discovered
- connections: related entities and shipments
- fraud_pattern: identified fraud type if any
- exposure_estimate: potential financial impact
- confidence_level: investigation confidence (0-1)
- recommended_actions: prioritized next steps
- escalation_required: boolean with reason if true

All monetary amounts in the input are USD. Express exposure_estimate in USD,
leading with a figure (for example "USD 164,000 cargo value plus penalties").
"""


async def investigate_case(case_data: dict[str, Any]) -> dict[str, Any]:
    """
    Conduct a deep investigation of a flagged case.
    """
    case_text = f"""
    CASE ID: {case_data.get('case_id', 'N/A')}
    TRIGGER: {case_data.get('trigger_reason', 'N/A')}
    INITIAL RISK SCORE: {case_data.get('risk_score', 'N/A')}
    
    PRIMARY SHIPMENT:
    {_format_shipment(case_data.get('primary_shipment', {}))}
    
    RELATED SHIPMENTS:
    {_format_related_shipments(case_data.get('related_shipments', []))}
    
    ENTITY PROFILE (Primary):
    {_format_entity(case_data.get('primary_entity', {}))}
    
    HISTORICAL ALERTS:
    {_format_alerts(case_data.get('historical_alerts', []))}
    
    FINANCIAL SUMMARY:
    - Total Transaction Volume: {case_data.get('total_volume', 'N/A')} USD
    - Average Transaction: {case_data.get('avg_transaction', 'N/A')} USD
    - Anomaly Count (30d): {case_data.get('anomaly_count_30d', 'N/A')}
    """
    
    with Timer() as timer:
        response = await client.aio.models.generate_content(
            model=get_model_id(),
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part(text=f"Conduct a thorough investigation:\n{case_text}")]
                )
            ],
            config=types.GenerateContentConfig(
                system_instruction=INVESTIGATION_PROMPT,
                temperature=0.2,  # Slightly higher for creative investigation
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(
                    thinking_budget=8000  # Enable extended thinking for complex analysis
                )
            )
        )

    parsed, error = parse_model_json(response.text)
    input_tokens, output_tokens = extract_tokens(response)
    out = envelope(
        agent="investigation",
        model=get_model_id(),
        result=parsed,
        error=error,
        raw=response.text or "",
        latency_ms=timer.ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        legacy_key="investigation_result",
        case_id=case_data.get("case_id"),
    )
    out["thinking_enabled"] = True
    return out


def _format_shipment(shipment: dict) -> str:
    if not isinstance(shipment, dict) or not shipment:
        return "No data"
    return f"""
    - ID: {shipment.get('shipment_id', 'N/A')}
    - Route: {shipment.get('origin', 'N/A')} → {shipment.get('destination', 'N/A')}
    - Value: {shipment.get('declared_value', 'N/A')} USD
    - Cost: {shipment.get('shipping_cost', 'N/A')} USD
    - Shipper: {shipment.get('shipper_name', 'N/A')}
    - Status: {shipment.get('status', 'N/A')}
    """


def _format_related_shipments(shipments: list) -> str:
    if not shipments:
        return "None found"
    lines = []
    for s in shipments[:10]:  # Limit to 10
        if isinstance(s, dict):
            lines.append(
                f"  - {s.get('shipment_id')}: {s.get('origin')} → {s.get('destination')} "
                f"({s.get('declared_value')} USD)"
            )
        else:
            lines.append(f"  - {s}")
    return "\n".join(lines)


def _format_entity(entity: dict) -> str:
    if not isinstance(entity, dict) or not entity:
        return "No data"
    return f"""
    - Name: {entity.get('name', 'N/A')}
    - Company: {entity.get('company', 'N/A')}
    - Registration Date: {entity.get('registration_date', 'N/A')}
    - Total Transactions: {entity.get('transaction_count', 'N/A')}
    - Risk Rating: {entity.get('risk_rating', 'N/A')}
    - Previous Flags: {entity.get('previous_flags', 'N/A')}
    """


def _format_alerts(alerts: list) -> str:
    """
    Render prior alerts.

    Upstream agents return these as either structured objects or plain strings
    depending on the finding, so both shapes are accepted rather than assumed.
    """
    if not alerts:
        return "No previous alerts"
    lines = []
    for a in alerts[:5]:
        if isinstance(a, dict):
            lines.append(
                f"  - [{a.get('date', 'undated')}] {a.get('type', 'alert')}: "
                f"{a.get('description', '')}"
            )
        else:
            lines.append(f"  - {a}")
    return "\n".join(lines)


async def generate_report(investigation_results: list[dict]) -> dict[str, Any]:
    """
    Generate a consolidated investigation report from multiple case results.
    """
    report_prompt = """
    Based on the investigation results provided, generate a consolidated report with:
    1. Executive Summary
    2. Key Findings
    3. Common Patterns
    4. Total Risk Exposure
    5. Priority Recommendations
    6. Systemic Issues Identified
    
    Output as structured JSON.
    """
    
    results_text = "\n\n".join([
        f"Case {r.get('case_id')}: "
        f"{json.dumps(r.get('result') or r.get('investigation_result') or {}, ensure_ascii=False)}"
        for r in investigation_results
    ])

    with Timer() as timer:
        response = await client.aio.models.generate_content(
            model=get_model_id(),
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part(text=f"Generate report from these investigations:\n{results_text}")]
                )
            ],
            config=types.GenerateContentConfig(
                system_instruction=report_prompt,
                temperature=0.2,
                response_mime_type="application/json",
            )
        )

    parsed, error = parse_model_json(response.text)
    input_tokens, output_tokens = extract_tokens(response)
    out = envelope(
        agent="investigation_report",
        model=get_model_id(),
        result=parsed,
        error=error,
        raw=response.text or "",
        latency_ms=timer.ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        legacy_key="report",
    )
    out["cases_analyzed"] = len(investigation_results)
    return out


def get_agent_info() -> dict[str, str]:
    """Return agent metadata."""
    return {
        "name": "VF Logistics AI Investigation Agent",
        "version": "1.0.0",
        "model": get_model_id(),
        "capabilities": [
            "deep_case_investigation",
            "pattern_analysis",
            "network_mapping",
            "risk_assessment",
            "report_generation",
            "extended_thinking"
        ]
    }
