# Devpost Submission — VF Logistics Autonomous Fraud Detection

Copy-paste material for the Devpost form. The demo shooting script is kept
outside the repository — it is recording notes, not part of the submission.

---

## Project name

VF Logistics — Fraud Detection an Operator Can Delegate To

## Elevator pitch (200 char limit on Devpost)

Four Gemini agents screen shipments for fraud and sanctions, but the operator—not the agents—decides what they may do about it. A published Delegation Boundary is the only source of authority.

## Track

The Taskmaster — Autonomous Workflow Automation

## Hosted project URL

https://vf-fraud-detection-304507056252.asia-southeast1.run.app

---

## Text description

### The problem

Vietnamese logistics operators lose money to shipment fraud that threshold rules
cannot see. A shipping cost 60% under the historical route average looks like a
promotion, not under-invoicing. A shipper with two lifetime transactions and a
generic company name looks like a new customer, not a shell entity. A creation
timestamp in the future looks like a data-entry slip, not manipulation.

Individually each signal is weak and generates false positives. Together they
are damning. Catching that combination is what a SQL rules engine structurally
cannot do, and what a human analyst has no time to do across thousands of
shipments a day.

But detecting fraud is only half the problem. The harder question is: **who
decides what the agent may do about it?** An agent that reasons well is not the
same as an agent you can hand authority to.

### What we built

A multi-agent system on Cloud Run where **four** specialised Gemini agents share
one shipment record, each with its own model, system instruction, sampling
temperature and reasoning budget—and a **governance layer** that determines
which of those agents' recommendations actually execute.

**Document Intake Agent** — reads a real shipping document (bill of lading,
commercial invoice, packing list) using Gemini's native PDF and image support.
Transcribes into the structured shipment record the rest of the pipeline
understands. Runs at `temperature=0.0` because this is transcription, not
generation.

**Fraud Detection Agent** — screens seven fraud families (price manipulation,
route fraud, weight/dimension fraud, document fraud, identity fraud, duplicate
billing, time fraud). Returns `risk_score` 0–100, `risk_level`, a `flags[]`
array with per-finding severity and evidence, `recommendations[]`, and an
explicit `confidence`. Runs at `temperature=0.1` so scoring is stable across
repeat calls on the same shipment.

**Compliance Screening Agent** — sanctions exposure against OFAC / UN / EU
patterns, trade and regulatory compliance, AML indicators, and standalone entity
screening for a counterparty.

**AI Investigation Agent** — multi-step case investigation across related
shipments, pattern analysis, network mapping and consolidated reporting. This is
the one agent given extended thinking (`thinking_budget=8000`) because case work
genuinely needs multi-hop reasoning rather than a single pass. It is also the one
agent that runs on **Gemini 3.5 Flash-Lite** rather than Flash — see below.

### Two models, chosen per task

The model is not a single global setting in this system. Document intake, fraud
detection and compliance screening run **Gemini 3.5 Flash**: intake needs native
multimodal PDF reading, and fraud and compliance produce the scores that hold or
release physical cargo, so they get the stronger model.

Investigation runs **Gemini 3.5 Flash-Lite**. By the time a case reaches it the
fraud and compliance findings already exist — investigation synthesises and
summarises them rather than making the primary judgement. Flash-Lite is half the
input and half the output cost for that shape of work, and it still accepts
`thinking_budget`, so the multi-hop reasoning the case write-up needs survives
the downgrade.

Both models are reached through the same `google-genai` client with
`vertexai=True`, so the split adds no integration surface. Every agent response
envelope records the model that produced it, and the dashboard's per-case trace
shows it on each hop — the split is observable, not just asserted.

Every agent is constrained to `response_mime_type="application/json"`, so each
output is data the next stage can route on rather than prose someone has to
re-parse.

### Governance: the part most agent systems skip

Most agent demonstrations treat "the model decided" as the end of the story.
We treat it as the beginning of a different question: **who authorised that
decision?**

The answer in this system is a **Delegation Boundary**: a versioned,
machine-readable policy published by a named human. The boundary says exactly
which actions the agent may take (`release_shipment`, `hold_shipment`,
`assign_analyst`, `draft_sar`, `notify_webhook`, `publish_decision`) and within
what limits—maximum declared value, maximum effective risk, forbidden HS
prefixes, forbidden destinations. Publishing a new version marks the previous
one **SUPERSEDED**. Every executed action records the boundary version that
permitted it.

The boundary enforces a simple rule: **an agent may raise risk, never lower it
below a deterministic floor.** `verifier.py` computes that floor from arithmetic
and code-resident reference lists (lane freight baselines, dual-use HS prefixes,
enhanced due diligence destinations). A successful prompt injection can
manipulate the model's score; it cannot manipulate the floor, because the floor
does not come from the model.

With no active boundary the entire system is **SUSPENDED**. Analysis keeps
running—the agents will still tell you what they found—but protected actions are
refused. A fresh deployment can look but cannot touch until a human has
published authority.

This is what "governed autonomous" means: the agent is fully autonomous *inside*
the boundary and stops at its edge.

### Input security: documents are untrusted

A shipping document is attacker-controlled. It arrives as a PDF, goes into a
model, and the model's output moves physical cargo. We treat it as a
prompt-injection channel.

**Google Cloud Model Armor** screens the document before Gemini sees it. For a
PDF with a text layer, pypdf extracts the text deterministically, Model Armor
screens that, and a blocked document produces **no model processing at all**.
For a scanned image there is no text layer to pre-screen; the transcription is
screened after, which is a weaker assurance the case records explicitly.

The screen uses **windowed analysis**: the same 275-character injection that
triggers MEDIUM_AND_ABOVE when sent alone scored NO_MATCH when buried in a
four-page bill of lading. Documents are therefore screened in 400-character
windows with 120-character overlap, in addition to the full text.

After transcription, `untrusted.py` enforces a **strict field whitelist**.
`avg_route_cost`, `shipper_tx_count` and `created_at` are deliberately excluded—a
document that could state its own shipper's history would defeat the thin-history
check by claiming a long one. `risk_score`, `decision`, and `state` are
**forbidden fields**; any document attempting to set them is logged and flagged
for human review.

That exclusion has to be paid for somewhere. Unverified history sets a
deterministic floor of 45 against an auto-clear threshold of 40, which meant no
uploaded document could ever clear autonomously — the control assumed an
enrichment step nobody had built. `shipper_registry.py` is that step: it resolves
the claimed shipper against our own counterparty book and supplies the history the
document is not allowed to assert about itself. Identity has to match on tax ID
**and** company name, because the tax ID is read off the untrusted document too—a
forgery carrying a real customer's number would otherwise inherit their clean
record. A number matching under a different name is treated as worse than unknown.

With it, `sample_docs/clean_bol.pdf` reaches `AUTO_CLEARED` and
`sample_docs/dirty_bol.pdf`, which carries no usable tax ID, still `ESCALATED`.
The difference between the two is whether we can vouch for the counterparty from
our own records, which is the only basis on which a machine should be releasing
cargo unsupervised.

Seven sample bills of lading are committed, each isolating one mechanism, and one
command runs all of them against the deployed service and checks the result
against the table in the README:

```bash
python scripts/test_documents.py 3
```

The most useful comparison is a matched set of three whose paperwork is of equal
quality and differs only in the counterparty: a shipper on file releases itself, a
shipper we have never traded with waits, and a shipper presenting *someone else's*
tax number is treated as worse than unknown rather than better. A fourth is
low-risk and compliance-clear but priced above the delegated ceiling, so the
boundary refuses the release and a human gets it — the governance claim,
demonstrable in one upload.

One of the seven is documented with two acceptable outcomes rather than one,
because it was measured landing on both sides of the `score_disputed` threshold.
Pinning it to a single state would have produced a submission that disagrees with
a judge's own run.

### Scale-to-zero without losing work

The service runs with `WORKER_MODE=ondemand` and `--min-instances=0`. No
background loop, no hourly billing. Cases advance inside request handlers: a
Pub/Sub push drives its own case to completion; the dashboard's state poll
drains a step at a time.

Failures retry with 5s/10s/20s exponential backoff and dead-letter after three
attempts. Claims are leases, so a case held by an instance that crashes or is
replaced mid-rollout is picked up by the next worker.

### Measured on the deployed service

One click and no further input:

| Shipment | Fraud risk | Compliance | Outcome | Actions executed |
|---|---|---|---|---|
| Clean garment export | 5/100 | not needed | `AUTO_CLEARED` | released for delivery |
| Underpriced furniture, thin history | 45–48/100 | cleared | `HELD_FOR_REVIEW` | analyst assigned |
| Dual-use goods, 11-day-old shell company | 95/100 | review required | `ESCALATED` | held, SAR drafted, compliance notified, decision published |

All three reached terminal state in roughly 30 seconds. Average agent hop was
7.3 seconds across six Gemini calls. Four consecutive runs from a reset board
produced the same three outcomes; the middle score is a range because it is a
model judgement at `temperature=0.1`, and only which side of the threshold it
falls on is deterministic.

### Features and functionality

- **Four specialised agents on two models** — document intake, fraud detection
  and compliance on Gemini 3.5 Flash; investigation on Gemini 3.5 Flash-Lite
  with extended thinking. The first three resolve their model at call time, so
  the dashboard can switch them and show the cost difference; investigation is
  pinned in code, because the hop chosen for being cheap should not be
  switchable to an expensive model.
- **Autonomous multi-step workflow** — conditional routing with no human
  step-through
- **Delegation Boundary** — versioned policy published by a named human; the
  only source of authority for protected actions
- **Fail-closed execution gate** — no boundary, no execution; SUSPENDED state
  refuses protected actions while analysis continues
- **Deterministic risk floor** — arithmetic and code-resident lists constrain
  what the agent can claim; `effective_risk = max(model_risk, floor)`
- **Model Armor integration** — windowed screening catches injections diluted by
  surrounding document text
- **Untrusted input gate** — schema whitelist, forbidden fields, invisible
  character stripping
- **Document intake** — Gemini 3.5 Flash reads PDFs and images natively; no
  separate OCR step. Drop a file onto the intake card or use the file picker;
  both run the same path, and the response does not return until the case has
  reached a terminal state.
- **Every case gets reviewable paperwork** — an uploaded original is archived to
  Cloud Storage and shown as-is; a case that arrived as a data event gets a bill
  of lading rendered from its record and labelled `SYSTEM-GENERATED`, on the
  document and in the provenance. A reconstruction is never presented as an
  original. Requires `DOCUMENT_BUCKET`; without a bucket the archive reports
  `archived: false` and there is nothing to show.
- **Identity split** — `vf-fraud-detection` has `aiplatform.user` + `datastore.user`
  + `storage.objectAdmin` but no `pubsub.publisher`; `vf-executor` has no
  `aiplatform.user` — neither service can do everything
- **Scale-to-zero** — `--min-instances=0`, `WORKER_MODE=ondemand`, lease-based
  claiming, exponential backoff
- **Human review queue** — cases that hit the boundary's limits or non-waivable
  triggers go to a named reviewer; SAR drafts require human signoff. Each case is
  coloured by state — red escalated, yellow held or pending — so severity is
  visible without reading.
- **Live operations dashboard** — pipeline board, event feed, action log, and a
  per-case trace showing every agent hop with its real latency
- **Decision Packs** — four synthesised views (integrity/pricing, sanctions,
  exposure/counterparty, document chain) so the reviewer sees conclusions and
  disagreements, not six raw payloads
- Three independent agents also exposed behind a versioned REST API (`/api/v1/**`)
- Batch analysis, standalone entity screening, consolidated report generation
- `/demo` endpoint that runs a built-in sample so a judge needs zero setup
- Structured JSON contract on every agent output, parsed server-side

### Technologies used

| Layer | Choice |
|---|---|
| Model | Gemini 3.5 Flash (`gemini-3.5-flash`) for document, fraud and compliance; Gemini 3.5 Flash-Lite (`gemini-3.5-flash-lite`) for investigation — both via Vertex AI, `location=global` |
| Agent framework | Google GenAI SDK (`google-genai`), async client |
| Input security | Google Cloud Model Armor (`asia-southeast1`, `vf-document-intake` template) |
| Compute | Cloud Run (source deploy → Cloud Build → Artifact Registry), `--min-instances=0` |
| State | Firestore Native mode in `asia-southeast1` — `cases`, `events`, `audit_log`, `delegation_boundaries` |
| Messaging | Pub/Sub — `shipment-events` inbound, `case-decisions` outbound |
| Documents | Cloud Storage — source landing zone, processed archive |
| Web | Flask + gunicorn (1 worker, 8 threads), flask-cors |
| Frontend | Vanilla HTML/CSS/JS, inline SVG gauge, no build step |
| Container | python:3.11-slim |
| Region | Cloud Run in `asia-southeast1`, close to users in Vietnam |

Hackathon requirements: Gemini 3.5 or newer via Vertex AI (two models) · a Google
agent framework (GenAI SDK) · Google Cloud infrastructure (Cloud Run, Firestore,
Pub/Sub, Cloud Storage, Model Armor) · asynchronous background operation ·
multi-step workflow · meaningful action taken on the user's behalf

### Other data sources used

None. Shipment records—including the historical route-cost baseline and the
shipper transaction count the agents reason against—are supplied per request.
The verifier falls back to code-resident lane tables when no `avg_route_cost` is
provided, which is always the case for document-sourced shipments.

### Findings and learnings

**Gemini 3.5 Flash is not served from regional endpoints.** Both `us-central1`
and `asia-southeast1` returned `404 NOT_FOUND` for
`publishers/google/models/gemini-3.5-flash`. Only `locations/global` served it.
The 404 body reads "was not found **or your project does not have access to
it**", which sent us auditing IAM before we thought to question the endpoint—
we granted `aiplatform.admin` chasing a problem that was never a permission
problem. Cloud Run stays regional; only the Vertex AI call goes global.

**A 3 ms 500 is a client-side validation error, not a model failure.** Our
investigation agent failed instantly while the other two worked. The Cloud Run
request log showed `latency=0.003279797s`—far too fast to have touched Vertex
AI. Cause: we passed `thinking_budget_tokens` to `ThinkingConfig`, but the real
field is `thinking_budget`, so pydantic rejected it before any network call.
Confirmed in one line:
`python -c "import google.genai.types as t; print(list(t.ThinkingConfig.model_fields))"`
→ `['include_thoughts', 'thinking_budget', 'thinking_level']`. Reading latency
before reading the stack trace would have saved an hour.

**A Cloud Build step can report SUCCESS while the build fails.** Two builds
showed `run-docker-build: SUCCESS` with a completed PUSH phase, yet
`status: FAILURE` and an empty Artifact Registry. The tell is
`results.buildStepImages` populated but `results.images` absent—the push
failed, not the build. It was masked because the compute service account lacked
`logging.logWriter`, so there were no build logs to read at all. Source deploys
need three distinct grants (`storage.objectAdmin` to read the uploaded zip,
`artifactregistry.writer` to push, `logging.logWriter` to be debuggable) and
Google only warns about the third one after the fact.

**Designing for LLM non-determinism traded predictability for expressiveness.**
The original approach encoded fraud rules as SQL predicates over historical
aggregates. With Gemini we deleted most of that and described intent instead—
which is why the system now catches signal combinations that SQL never could.
But the output stopped being reproducible, so `temperature=0.1` and a
model-reported `confidence` field are load-bearing, not decoration.

**Structured output is the actual multi-agent primitive.** Forcing
`response_mime_type="application/json"` on every agent is what turns three
separate model calls into a pipeline. Without it, agent hand-off becomes string
munging and the architecture stops scaling at two agents.

**Model Armor's whole-document score dilutes localised injections.** A planted
instruction scored MEDIUM_AND_ABOVE when isolated but NO_MATCH when embedded in
legitimate BOL text. Windowed screening (400 chars, 120 overlap) restores
detection without losing context.

**Model choice is a per-agent decision, not a project-wide one.** We started with
one model id shared by every agent because that is the obvious way to build it.
But the four agents are not doing the same kind of work: intake is transcription,
fraud and compliance are primary judgements on physical cargo, and investigation
is summarisation of findings that already exist. Once we separated them, the
investigation hop moved to Flash-Lite at half the token cost with no loss in the
case write-up — it still gets `thinking_budget`, and it was never the call that
decided whether cargo moves. The lesson is that "which model" is a property of
the task, and treating it as one global constant leaves cost on the table for no
correctness benefit.

**The execution gate is more important than the model.** Judges will remember
"you can publish a policy that constrains what the agent does" longer than
"Gemini scored this shipment 78." Governance is the differentiator; the model
is the commodity.

---

## Video script

The shooting script is deliberately not in this repository. It is operator notes
for one recording session, it has to track the UI shot by shot, and a copy that
lives next to the submission drifts from both.

The version that used to sit inline here is the argument for that. It had gone
stale in two ways: it said to click an **Upload document** button, when the intake
card now accepts a dropped file as well, and it summarised the pipeline as "four
agents on the GenAI SDK to Gemini 3.5 Flash", which contradicts the multi-model
split this submission claims as its bonus — the investigation agent runs
Flash-Lite.

Two things worth knowing before recording, because neither is visible in the UI:
the board has to be seeded first or the cost meter and the pipeline are both empty
on camera, and a document upload takes roughly 30 to 50 seconds to reach a
terminal state, so the narration over that scene has to be long enough to cover
it.

---

## Devpost form — field-by-field answers

### Project details

**Built with** (tags, already entered): gemini, vertex-ai, google-cloud,
cloud-run, firestore, pub-sub, cloud-storage, model-armor, google-genai-sdk,
python, flask, gunicorn, asyncio, javascript, html5, ci-cd, docker

**"Try it out" links:**
- https://vf-fraud-detection-304507056252.asia-southeast1.run.app
- https://github.com/CHAUPHUOCHOA/vf-logistics-hackathon-google

### Additional info

| Field | Answer |
|---|---|
| **Submitter Type** | Individual |
| **Country of residence** | Vietnam |
| **Category** | The Taskmaster — Autonomous Workflow Automation |
| **Organization name** | *(leave blank / "N/A" — submitting as an individual)* |
| **Date started** | 08-2026 (use the real first-commit date, MM-DD-YY) |
| **Public code repo URL** | https://github.com/CHAUPHUOCHOA/vf-logistics-hackathon-google |
| **Reproducible Testing instructions in README?** | **Yes** — README → *Reproducible testing* |
| **Hosted project URL** | https://vf-fraud-detection-304507056252.asia-southeast1.run.app |
| **Testing instructions (private)** | No login required. `GET /health` to warm it, then `POST /api/v1/simulate` and poll `GET /api/v1/orchestrator/state`. Each poll advances the pipeline one step. Full walkthrough in the README's *Reproducible testing* section. |
| **Architecture diagram** | upload `docs/architecture.png` |

**Which Google SDK did you use?** → **Google Gen AI SDK** (`google-genai`)

**Which Google Cloud Service(s) did you use?** → **Cloud Run**, **Firestore**,
**Pub/Sub**, **Cloud Storage** (Vertex AI is the model platform; Model Armor is
the input-security service — select them too if the list offers them)

**Which Google AI Models did you use?** (Gemini 3.5 or newer REQUIRED; additional
models boost your score)

```
Gemini 3.5 Flash (gemini-3.5-flash) — document intake, fraud detection, compliance screening
Gemini 3.5 Flash-Lite (gemini-3.5-flash-lite) — investigation agent, extended thinking
```

> Both models are verifiable on the live service: `GET /agents` reports the model
> per agent, and every analysis response carries a `"model"` field.

**Startup Prize fields** → leave blank (submitting as an individual, not an
incorporated organisation).

**Bonus points** → optional; the *Findings & learnings* section above is
publishable as a blog post, and a social post needs
`#AllThingsAgenticHackathon`.

---

## Submission checklist

| Item | Status |
|---|---|
| Demo video ~4 min | ⬜ record using script above |
| Public code repository | ⬜ push to GitHub |
| Architecture diagram | ✅ `docs/architecture.png` |
| Devpost text description | ✅ this file |
| README with spin-up instructions | ✅ `README.md` |
| Reproducible testing instructions | ✅ `README.md` → *Reproducible testing*, 5 tests |
| Hosted project URL | ✅ live on Cloud Run |
| Gemini 3.5+ via Vertex AI | ✅ `gemini-3.5-flash` + `gemini-3.5-flash-lite` |
| Google agent framework | ✅ Google GenAI SDK |
| Google Cloud infra service | ✅ Cloud Run, Firestore, Pub/Sub, Cloud Storage, Model Armor |

### Bonus (optional)

| Item | Status |
|---|---|
| Blog / video about the build | ⬜ the *Findings & learnings* section is already a post |
| Social post with `#AllThingsAgenticHackathon` | ⬜ |
| Additional Google AI model | ✅ **Gemini 3.5 Flash-Lite** alongside Flash — investigation agent |

If the repository is private, share it with `testing@devpost.com` and
`cloudhackathons@google.com`.

---

## Cost note

The service runs with `--min-instances=0`, so it scales to zero when idle. The
rules confirm the project does **not** need to be live at judging time—the
video and repo are the proof. After recording, you can delete it:

```bash
gcloud run services delete vf-fraud-detection --region asia-southeast1
```
