# Meet the Builders — Submission Copy

Material for the Google Gen AI Academy APAC 2026 "Meet the Builders" form.
Fill in the fields the form asks for; nothing here is submitted automatically.

## Project name

VF Logistics — Autonomous Fraud Detection Agents

## One-line pitch

Four Gemini agents screen logistics shipments for fraud and sanctions risk, but
the operator, not the agents, decides what they may do about it, through a
published Delegation Boundary.

## Links

- Live service: https://vf-meet-the-builders-304507056252.asia-southeast1.run.app
- Code: https://github.com/hoachauphuoc/vf-logistics-meet-the-builders
- Architecture diagram: `docs/architecture.png`
- Screenshots: `docs/screenshots/`
- Build story (basis for the write-up): `docs/PROJECT_STORY.md`

## Why it stands out

- **Autonomous end to end.** Three shipments with different risk profiles reached
  three different outcomes in about 30 seconds with no human input.
- **The agents are not trusted.** A deterministic verifier sets a risk floor that a
  model can raise but never lower: an agent coerced into `risk_score: 0` on a
  dual-use shipment still produced an effective risk of 90 and a human review.
- **Injection is stopped before the model runs.** Model Armor screens an untrusted
  document first; a blocked document never reaches Gemini.
- **Authority is published, not earned.** A human publishes a versioned Delegation
  Boundary. With none in force the system fails closed and refuses every
  protected action.
- **Auditable and reproducible.** Every hop records its model and latency, and
  seven sample PDFs plus one script check the documented outcomes.

## Check it in 60 seconds

No login. Read-only, leaves the live board as it is:

    BASE=https://vf-meet-the-builders-304507056252.asia-southeast1.run.app
    curl -s $BASE/health
    curl -s $BASE/agents
    curl -s "$BASE/api/v1/orchestrator/state?drain=0"

## Honest limits

`vf-executor` is deployed but not connected, the `case-decisions` topic has no
subscriber yet, and sanctions screening is the model's own knowledge rather than a
list lookup. See `README.md`, section "What is connected today".

## Google technology used

- Gemini 3.5 Flash and Gemini 3.5 Flash-Lite through Vertex AI (Google Gen AI SDK)
- Cloud Run, Firestore, Pub/Sub, Cloud Storage
- Model Armor (input screening for untrusted documents)

## Problem and who it helps

Vietnamese logistics operators lose money to shipment fraud that threshold rules
cannot see. This project combines weak signals (price, identity, timing,
documents, sanctions exposure) and keeps a human in control of what the agents
may execute. See `README.md` and `docs/PROJECT_STORY.md`.

## Try it

No login required. See README, section "Reproducible testing".

## Before submitting

- [x] Public GitHub repository created
- [ ] Confirm the form's required fields, deadline and badge steps on the Register page
- [ ] Check the live service still responds (`GET /health`)
