"""
Document intake agent - Gemini 3.5 Flash, multimodal.

Reads a real shipping document (bill of lading, commercial invoice, packing
list) and returns the structured shipment record the rest of the pipeline
already understands. This is what turns the system from "somebody typed a
shipment into a form" into "a document landed and the workflow started".

Gemini 3.5 Flash reads PDFs and images natively, so no separate OCR or
Document AI step is needed: the bytes go straight to the model.

"""

from __future__ import annotations

import os
from typing import Any

from google import genai
from google.genai import types

from ._common import Timer, envelope, parse_model_json, extract_tokens
import config as model_config

PROJECT_ID = os.getenv("PROJECT_ID", "project-93ded24f-21c3-4f1b-a7d")
LOCATION = os.getenv("LOCATION", "global")

client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

def get_model_id():
    return model_config.get_model()

# Anything the pipeline reasons over has to come out of here, because a field
# the extractor drops becomes a compliance gap further downstream.
EXTRACTION_PROMPT = """
You are a document intake agent for VF Logistics. You read shipping paperwork
and transcribe it into a structured record. You are a transcriber, not an
analyst: do not score risk, do not editorialise, do not infer facts the
document does not support.

Extract exactly this JSON shape:

{
  "shipment_id": "carrier booking or B/L number as printed",
  "origin": "port or city of loading, with country",
  "destination": "port or city of discharge, with country",
  "weight_kg": number,
  "declared_value": number,
  "shipping_cost": number,
  "currency": "the currency code printed on the document",
  "shipper_name": "string",
  "shipper_company": "string",
  "shipper_country": "string",
  "shipper_tax_id": "string",
  "receiver_name": "string",
  "receiver_company": "string",
  "receiver_country": "string",
  "cargo_description": "goods description as printed",
  "hs_code": "string",
  "route_details": "routing including any transhipment",
  "transit_points": "string, or None",
  "status": "pending",
  "extraction_notes": ["anything illegible, missing, altered or internally inconsistent"],
  "extraction_confidence": 0.0
}

Rules that matter:

- Amounts must be plain numbers with no currency symbol, thousands separator or
  units. Report the currency separately in `currency`.
- If the document states amounts in a currency other than USD, still transcribe
  the printed figures and set `currency` to what is printed. Do not convert.
- For any field genuinely absent from the document, use the string "not stated"
  for text fields and 0 for numeric fields. Never invent a plausible value: a
  missing tax ID is a compliance signal, and inventing one destroys that signal.
- Put every legibility problem, missing mandatory field, alteration, or internal
  contradiction into `extraction_notes`. Downstream agents treat these as
  evidence.
- `extraction_confidence` is your own confidence in the transcription, 0 to 1.
"""

SUPPORTED_MIME = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def mime_for(filename: str) -> str | None:
    ext = os.path.splitext(filename or "")[1].lower()
    return SUPPORTED_MIME.get(ext)


async def extract_shipment(
    document_bytes: bytes, filename: str, mime_type: str | None = None
) -> dict[str, Any]:
    """
    Transcribe a shipping document into a structured shipment record.

    Returns the standard agent envelope; `result` is the shipment dict that can
    be handed straight to the orchestrator.
    """
    mime = mime_type or mime_for(filename) or "application/pdf"

    with Timer() as timer:
        response = await client.aio.models.generate_content(
            model=get_model_id(),
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(data=document_bytes, mime_type=mime),
                        types.Part(
                            text=(
                                "Transcribe this shipping document into the "
                                "required JSON record."
                            )
                        ),
                    ],
                )
            ],
            config=types.GenerateContentConfig(
                system_instruction=EXTRACTION_PROMPT,
                temperature=0.0,  # transcription, not generation
                response_mime_type="application/json",
            ),
        )

    parsed, error = parse_model_json(response.text)
    input_tokens, output_tokens = extract_tokens(response)
    return envelope(
        agent="document_intake",
        model=get_model_id(),
        result=parsed,
        error=error,
        raw=response.text or "",
        latency_ms=timer.ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        legacy_key="extraction",
        source_filename=filename,
        source_mime=mime,
    )


def get_agent_info() -> dict[str, Any]:
    return {
        "name": "VF Logistics Document Intake Agent",
        "version": "1.0.0",
        "model": get_model_id(),
        "project": PROJECT_ID,
        "location": LOCATION,
        "capabilities": [
            "pdf_transcription",
            "scanned_image_transcription",
            "shipment_field_extraction",
            "missing_field_detection",
        ],
        "supported_types": sorted(SUPPORTED_MIME),
    }
