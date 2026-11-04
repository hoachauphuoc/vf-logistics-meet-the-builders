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

- Live service: https://vf-fraud-detection-304507056252.asia-southeast1.run.app
- Code: *(add the public GitHub URL of this repository once pushed)*
- Architecture diagram: `docs/architecture.png`
- Screenshots: `docs/screenshots/`
- Build story (basis for the write-up): `docs/PROJECT_STORY.md`

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

- [ ] Push this repository to a new public GitHub repo and fill in the Code link
- [ ] Confirm the form's required fields, deadline and badge steps on the Register page
- [ ] Check the live service still responds (`GET /health`)
