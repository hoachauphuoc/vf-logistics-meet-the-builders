# VF Logistics — Autonomous Fraud Detection Agents

**Programme:** Google Gen AI Academy APAC 2026 — Meet the Builders
**Live URL:** https://vf-fraud-detection-304507056252.asia-southeast1.run.app

A multi-agent system that screens logistics shipments for fraud, sanctions/trade
compliance violations, and runs deep-dive investigations — without a human
walking it through each step. Built 100% on Google Cloud: Gemini 3.5 Flash and
Gemini 3.5 Flash-Lite on Vertex AI + Cloud Run + Firestore + Pub/Sub +
Cloud Storage + Model Armor.

A shipment event arrives and nobody touches it again. A background worker scores
it for fraud, decides on that score whether compliance screening is warranted,
decides on the screening whether to open a deep investigation, and then acts:
releasing the shipment, assigning an analyst, or holding the cargo and drafting a
suspicious activity report for human signature.

Measured on the deployed service, three shipments with deliberately different
risk profiles reached three different outcomes in roughly 30 seconds, with the
injection call returning in 547ms and no further input:

| Shipment | Fraud risk | Compliance | Outcome | Actions executed |
|---|---|---|---|---|
| Clean garment export | 5/100 | not needed | `AUTO_CLEARED` | released for delivery |
| Underpriced furniture, thin history | 45–48/100 | cleared | `HELD_FOR_REVIEW` | analyst assigned |
| Dual-use goods, 11-day-old shell company | 95/100 | review required | `ESCALATED` | held, SAR drafted, compliance notified |

The outcomes are stable — four consecutive runs from a reset board produced the
same three states. The middle score is given as a range because it is a model
judgement at `temperature=0.1`, and quoting one spot value as though it were
deterministic would misrepresent it; what is deterministic is which side of the
thresholds it falls on.

---

## The problem

Vietnamese logistics operators lose money to shipment fraud that is invisible to
threshold rules: a shipping cost 60% under the historical route average looks
like a promo, not under-invoicing. A shipper with 2 lifetime transactions and a
generic company name looks like a new customer, not a shell entity. Catching
these requires reading many weak signals *together* — exactly what a rules
engine cannot do and an analyst has no time to do at volume.

## What the system does

Four specialised agents plus a deterministic verification layer, coordinated by a
governance control plane:

| Agent | Responsibility | Notable config |
|---|---|---|
| **Document Intake** | Transcribes bills of lading, invoices and packing lists into a structured record. Reports missing fields as missing rather than inventing them. | `temperature=0.0`, multimodal PDF/image input |
| **Fraud Detection** | Price manipulation, route fraud, weight/dimension fraud, document fraud, identity fraud, duplicate & time fraud. | `temperature=0.1` for stable scoring |
| **Compliance Screening** | Sanctions exposure (OFAC/UN/EU patterns), trade & regulatory compliance, AML indicators. | `temperature=0.1`, runs in parallel with fraud |
| **AI Investigation** | Multi-step case investigation, pattern analysis, network mapping. | **Gemini 3.5 Flash-Lite**, **extended thinking** — `thinking_budget=8000` |

### Two models by default, chosen per task

The first three agents run **Gemini 3.5 Flash**: document intake needs native
multimodal PDF reading, and fraud and compliance screening are the calls whose
scores hold or release cargo, so they get the stronger model.

The investigation agent runs **Gemini 3.5 Flash-Lite**. By the time a case
reaches it, the fraud and compliance findings already exist — investigation
synthesises and summarises them rather than making the primary judgement.
Flash-Lite is half the input cost and half the output cost for that shape of
work, and it still accepts `thinking_budget`, so the multi-hop reasoning the
case write-up needs is preserved.

Both models are reached through the same `google-genai` SDK client with
`vertexai=True`, so the split costs no extra integration surface. Every agent
response envelope records which model produced it, visible in the per-case trace
in the dashboard.

All return strict JSON (`response_mime_type="application/json"`), parsed
server-side, so downstream routing is machine-readable.

### The agents are not trusted

This is the part that matters most. Every agent above is a language model, and a
language model can be mistaken, overconfident, or manipulated by the very
document it is reading. The pipeline holds and releases physical cargo, so agent
output is treated as a **claim**, not a finding.

[`verifier.py`](verifier.py) recomputes what can be computed. Freight against
lane baselines, value per kilo, mandatory-field completeness, HS code validity
against a dual-use watchlist held as a code constant, high-risk routing,
counterparty history. No model is consulted, because
`shipping_cost / avg_route_cost` is a division.

Those checks produce a **risk floor**, and the governing rule is asymmetric:

> An agent may **raise** risk. It may never **lower** risk below the
> deterministic floor.

Escalating on model judgement is acceptable; exonerating on model judgement is
not, because a wrong exoneration releases contraband and a wrong escalation costs
a reviewer ten minutes. Measured on the deployed service: an agent coerced into
returning `risk_score: 0` for a dual-use shipment still produced an effective
risk of 90, `auto_clear_permitted: false`, and a case routed to a human.

Three inputs are deliberately excluded from the document schema in
[`untrusted.py`](untrusted.py): `avg_route_cost`, `shipper_tx_count` and
`created_at`. A document that could state its own route average would defeat the
pricing check by setting it low, and one that could state its own shipper history
would defeat the counterparty check by claiming a long one. Absent history is
treated as unverified, and unverified is not clean.

That exclusion leaves a gap the design has to close somewhere else. Absent
history sets a floor of 45, above the auto-clear threshold of 40, so for a while
*no* uploaded or staged document could clear autonomously — the control was
written around an enrichment step that did not exist yet.
[`shipper_registry.py`](shipper_registry.py) is that step: it resolves the
claimed shipper against our own counterparty book and supplies the trading
history the document is not allowed to assert about itself. Identity must match
on tax ID **and** company name together, because the tax ID is itself read off
the untrusted document — a forged bill of lading carrying a real customer's
number would otherwise inherit that customer's clean history. A number that
matches under a different name is reported as `identity_mismatch` and treated as
worse than unknown.

The withheld fields are also reported to the fraud agent as *not available*
rather than as a bare `N/A`, with an instruction that their absence says nothing
about the shipment. Showing an unexplained blank made the agent read our own
intake rule as evidence against the shipper: it called a missing creation
timestamp "highly anomalous, could indicate manual record insertion" and scored a
well-formed bill of lading at 52 — high enough to hold it. The value is still
never taken from the file. The deterministic floor, not the model, remains the
thing that penalises genuinely unverified history.

### Authority is published, not earned

An agent here does not acquire the right to act by reasoning well. A human
publishes a versioned, machine-readable **Delegation Boundary**, and the agent
operates inside it.

That is what keeps this both autonomous and governable. The human is not
approving shipments one at a time — that would be a slow human process with extra
steps. The human approves **policy**, once, and cases execute against it without
supervision. Only cases that fall outside the published boundary come back to a
person.

With no active boundary the system is **SUSPENDED** and fails closed: it still
analyses and proposes, but [`governance.py`](governance.py)'s execution gate
refuses every protected action. Verified on the deployed service — before any
boundary was published, even a demonstrably clean shipment could not be
released.

### The reviewer always has the paperwork

Work enters two ways. A shipment event arrives on `/api/v1/events/shipment`, or a
document is uploaded — drag a PDF or a scan onto the **Document intake** card, or
use the file picker; both paths run the same code. In the deployed
`WORKER_MODE=ondemand` configuration the upload request also advances the case,
usually all the way to a terminal state before it responds. It is not a guarantee:
the drain is bounded by `MAX_CHAIN_STEPS` and `CHAIN_BUDGET_SECONDS`, a case that
runs out of budget is left where it is for the next trigger to pick up, and under
`WORKER_MODE=poll` the response returns at `INGESTED` and the loop takes over.
The status is `202`, not `200`, for that reason.

Whichever way it arrived, **a case is meant to carry a bill of lading a human can
read.** When a shipper's original was uploaded it is archived to Cloud Storage and
shown as-is. When the case came from a data event there is no original, so
[`document_render.py`](document_render.py) renders one from the record and marks
it `SYSTEM-GENERATED` — on the document itself and in the case provenance
(`generated: true`, `rendered_from`). A reconstruction is never presented as an
original. Getting this wrong would corrupt the audit trail the system exists to
keep.

The honest caveat: this depends on `DOCUMENT_BUCKET` being set. Without it the
archive step returns `archived: false` and the case has no document to show, which
is why that variable is flagged in the environment table rather than left as an
optional extra.

This matters more than it sounds. Asking a human to approve a hold on a risk
score they cannot check against paperwork is a rubber stamp with extra steps. The
review queue also colours each case by state — red for escalated, yellow for held
or pending — because a reviewer should not have to read carefully to see
severity. It did not always: for a while the queue painted every item yellow,
which made an escalation look like a routine hold. Green exists in the same map
for cleared and human-released cases, but those do not appear in this queue by
definition — you see them on the board.

---

## Architecture

```
                    Browser (static/index.html)
                      │  fetch() JSON
                      ▼
      ┌───────────────────────────────────────────┐
      │  Cloud Run  ·  asia-southeast1            │
      │  vf-fraud-detection                       │
      │                                           │
      │  gunicorn ──► Flask (main.py)             │
      │                 │                         │
      │                 ├─ /                UI    │
      │                 ├─ /health               │
      │                 ├─ /agents               │
      │                 ├─ /demo                 │
      │                 └─ /api/v1/**            │
      │                      │                    │
      │      agents/ (google-genai SDK, async)    │
      │       ├─ document_agent.py                │
      │       ├─ fraud_detection_agent.py         │
      │       ├─ compliance_agent.py              │
      │       └─ investigation_agent.py           │
      └───────────────────┬───────────────────────┘
                          │  Vertex AI (vertexai=True)
                          ▼
         ┌──────────────────────────────────────┐
         │  Gemini 3.5 Flash                    │
         │    document · fraud · compliance     │
         │                                      │
         │  Gemini 3.5 Flash-Lite               │
         │    investigation                     │
         │                                      │
         │  location: global                    │
         └──────────────────────────────────────┘
```

See `docs/architecture.png` for the architecture diagram.

### The autonomous workflow

```
  Pub/Sub shipment-events ---+
  Scripted simulator      ---+--> POST /api/v1/events/shipment
                             |            |
                             |            v
                             |    Firestore cases (state INGESTED)
                             |
     orchestrator.py: asyncio worker loop, runs with no request in flight,
     claims a case under a lease, performs exactly one step, persists, repeats
                             |
       INGESTED --> fraud_detection agent --> risk_score
          |
          +-- risk < 40 --------------------> AUTO_CLEARED
          |                                     release_shipment()
          |
          +-- risk >= 40 --> compliance agent
                    |
                    +-- cleared, risk < 70 --> HELD_FOR_REVIEW
                    |                            assign_analyst()
                    |
                    +-- BLOCKED / REVIEW_REQUIRED, or risk >= 70
                              |
                              v
                     investigation agent (thinking_budget 8000)
                              |
                              v
                           ESCALATED
                             hold_shipment()
                             draft_sar()
                             notify_webhook()
                             assign_analyst()

       Any step failing 3 times, with 5s/10s/20s backoff --> DEAD_LETTER

       Terminal decisions are published to Pub/Sub case-decisions for
       downstream ERP / WMS / billing, and every action lands in audit_log.
```

Thresholds are environment variables (`FRAUD_CLEAR_BELOW`, `INVESTIGATE_AT`), so
the routing policy is configuration rather than something buried in code.

### Why these choices

- **`location="global"`** — Gemini 3.5 Flash is served from the global endpoint;
  regional endpoints (`us-central1`, `asia-southeast1`) return `404 NOT_FOUND`
  for this model. The Cloud Run service itself stays in `asia-southeast1`, close
  to users in Vietnam.
- **Async SDK calls** (`client.aio.models.generate_content`) with gunicorn
  `--threads 8` — a single instance handles concurrent analyses while each waits
  on model latency.
- **`WORKER_MODE=ondemand` with `--min-instances=0`** — Cloud Run freezes CPU
  between requests, which would suspend a background loop the moment a request
  finished. Rather than pay for `--no-cpu-throttling --min-instances=1` around
  the clock, cases advance *inside* request handlers: the Pub/Sub push, the
  document upload, and the dashboard's own state poll each carry the pipeline
  forward a step. The service scales to zero when no shipment exists.
  `POST /api/v1/orchestrator/tick` and `/drain` are the Cloud Scheduler levers
  for clearing a backlog unattended, and `WORKER_MODE=poll` still exists for
  deployments that would rather pay for a true always-on loop.
- **Claims are leases, not locks** — a case claimed by an instance that then
  crashes or is replaced mid-rollout becomes claimable again after
  `CLAIM_LEASE_SECONDS`. An earlier build used permanent claims and stranded
  every in-flight case on each deploy.
- **Firestore with an in-memory fallback** — `STORE_BACKEND=memory` runs the
  whole pipeline with no database, so the demo cannot be blocked by
  provisioning. A Firestore failure at boot degrades to memory and is reported
  on `/health` rather than crashing the container.
- **Readiness filtering happens in Python, not in the query** — expressing
  "unclaimed or lease expired, in one of these states, oldest first" as a
  Firestore query needs a hand-built composite index. Keeping it in code means
  the service runs against a bare Firestore database with no setup step.
- **State is persisted before the next step starts** — so a case survives an
  instance restart and resumes where it stopped, rather than restarting the
  workflow or losing the agent output already paid for.

---

## Tech stack

| Layer | Choice |
|---|---|
| Model | **Gemini 3.5 Flash** (document, fraud, compliance) + **Gemini 3.5 Flash-Lite** (investigation), both via **Vertex AI** |
| Agent framework | **Google GenAI SDK** (`google-genai`) |
| Input security | **Model Armor** — windowed prompt-injection screening |
| Compute | **Cloud Run** (source deploy → Cloud Build → Artifact Registry) |
| State | **Firestore** (Native mode, `asia-southeast1`) — cases, events, audit log |
| Messaging | **Pub/Sub** — `shipment-events` in, `case-decisions` out |
| Web | Flask + gunicorn, flask-cors |
| Frontend | Vanilla HTML/CSS/JS, no build step |
| Runtime | Python 3.11-slim container |

Google Cloud usage check:

- Gemini 3.5 or newer, via Vertex AI -> `gemini-3.5-flash` and
  `gemini-3.5-flash-lite`
- At least one Google agent framework -> Google GenAI SDK
- Google Cloud infrastructure -> Cloud Run (compute), Firestore (case state and
  audit trail), Pub/Sub (event ingestion and decision fan-out)
- Works asynchronously in the background -> a worker loop inside the container
  drives cases with no request in flight
- Multi-step workflow -> four agents chained with conditional branching
- Takes meaningful action -> shipments are held or released, analysts assigned,
  SAR drafts produced, decisions published

> Firestore and Pub/Sub are used on the live path, not merely pinned.
> `google-cloud-bigquery` and `google-cloud-storage` remain unused; they are
> pinned for the historical-baseline work described under *Roadmap*.

---

## API

### Autonomous orchestration

These are the autonomous-orchestration endpoints. None of them wait for an agent: ingestion
returns as soon as the case is durably recorded, and the background worker
carries the workflow to completion on its own.

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/events/shipment` | POST | Shipment-created event sink. Accepts a bare shipment or a Pub/Sub push envelope. Idempotent per `shipment_id`. |
| `/api/v1/simulate` | POST | Inject the scripted three-shipment demo batch |
| `/api/v1/orchestrator/state` | GET | Full dashboard projection: cases, events, audit, counters |
| `/api/v1/orchestrator/case/<case_id>` | GET | One case with every agent hop, latency and action receipt |
| `/api/v1/orchestrator/tick` | POST | Advance the pipeline one step. Cloud Scheduler fallback; the background loop normally does this. |
| `/api/v1/orchestrator/reset` | POST | Clear all cases, events and audit records. Published delegation boundaries deliberately survive: clearing a board is a demo convenience, revoking authority is not. |
| `/api/v1/orchestrator/drain` | POST | Run every pending case to a terminal state. The explicit lever for `WORKER_MODE=ondemand` — usable from Cloud Scheduler or to clear a backlog without waiting for the dashboard to poll it away one case at a time. |
| `/api/v1/events/document` | POST | Document intake. Multipart `file` (PDF or image). Screens for injection, transcribes, archives the original, then runs the case to a terminal state in the same request. |
| `/api/v1/events/storage` | POST | Cloud Storage notification sink — ingests a document dropped straight into the bucket. |
| `/api/v1/ingest/bucket-sweep` | POST | Ingest every unprocessed object in `DOCUMENT_BUCKET`. Recovery path for notifications that were missed. |
| `/api/v1/simulate/bulk` | POST | Randomised shipments weighted like a real book of business. Capped at `MAX_BULK_COUNT`. |

### Review, governance and configuration

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/review/queue` | GET | Everything the agent was not permitted to close, with state, risk and findings |
| `/api/v1/review/<case_id>/decide` | POST | Record a human decision — release, block or request more information |
| `/api/v1/review/<case_id>/document` | GET | The case's bill of lading: the shipper's original when one was uploaded, otherwise a `SYSTEM-GENERATED` reconstruction, labelled as such |
| `/api/v1/governance/agent` | GET | Agent status and the boundary version it is operating under |
| `/api/v1/governance/boundaries` | GET | Every published boundary version, newest first |
| `/api/v1/governance/publish` | POST | Publish a new delegation boundary. Supersedes the previous version rather than editing it. |
| `/api/v1/config` | GET | Effective configuration and thresholds |
| `/api/v1/config/model` | GET, POST | Read or switch the model used by intake, fraud and compliance. Investigation is pinned and unaffected. |
| `/internal/execute` | POST | The execution surface. Same codebase, deployed a second time as `vf-executor` with a different service account — that deployment is the only place a protected action actually happens. Not under `/api/v1` because it is not a public API. |

### Direct agent access

Useful for inspecting a single agent in isolation, and what the Single Agent
Console in the dashboard calls.

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Web dashboard (HTML) |
| `/health` | GET | Health check, store backend, worker status |
| `/agents` | GET | Agent metadata & capabilities |
| `/demo` | GET | Runs the fraud agent on a built-in sample shipment |
| `/api/v1/fraud/analyze` | POST | Analyse one shipment |
| `/api/v1/fraud/batch` | POST | Analyse many — body `{"shipments":[...]}` |
| `/api/v1/compliance/screen` | POST | Compliance screening for a shipment |
| `/api/v1/compliance/entity` | POST | Screen a single entity |
| `/api/v1/investigation/case` | POST | Deep-dive investigation |
| `/api/v1/investigation/report` | POST | Consolidated report — body `{"investigations":[...]}` |

### Example

```bash
curl -s -X POST \
  https://vf-fraud-detection-304507056252.asia-southeast1.run.app/api/v1/fraud/analyze \
  -H 'Content-Type: application/json' \
  -d '{
    "shipment_id": "VF-2026-0001",
    "origin": "Ho Chi Minh City",
    "destination": "Hanoi",
    "weight_kg": 150,
    "declared_value": 50000000,
    "shipping_cost": 1200000,
    "avg_route_cost": 3000000,
    "shipper_name": "Thanh Phat Trading Co",
    "receiver_name": "Minh Long Import Ltd",
    "shipper_tx_count": 2,
    "status": "pending",
    "route_details": "HCMC to Hanoi"
  }'
```

Response (`analysis` is a JSON string produced by the model):

```json
{
  "shipment_id": "VF-2026-0001",
  "model": "gemini-3.5-flash",
  "analyzed_at": "2026-08-29T07:10:00.000000",
  "analysis": "{\"risk_score\":78,\"risk_level\":\"HIGH\",\"flags\":[...],\"recommendations\":[...],\"confidence\":0.9}"
}
```

---

## Spin-up instructions

### Prerequisites

- Python 3.11+
- `gcloud` CLI
- A Google Cloud project with billing enabled

### 1. Run locally

```bash
git clone <this-repo>
cd vf-logistics-meet-the-builders

python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

Authenticate so the GenAI SDK can reach Vertex AI:

```bash
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

Configure and start:

```bash
cp .env.example .env       # Windows: copy .env.example .env
# set PROJECT_ID=YOUR_PROJECT_ID and LOCATION=global

python main.py             # http://localhost:8080
```

### 2. Deploy to Cloud Run

Enable the APIs:

```bash
gcloud services enable \
  run.googleapis.com \
  aiplatform.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  modelarmor.googleapis.com \
  --project YOUR_PROJECT_ID
```

Grant the default compute service account the roles it needs. **This step is
required** — source deploys fail without the build/storage roles, every model
call returns `403 PERMISSION_DENIED` without `aiplatform.user`, and the
orchestrator cannot persist a case without `datastore.user`:

```bash
PROJECT_ID=YOUR_PROJECT_ID
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
SA="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"

for ROLE in \
  roles/aiplatform.user \
  roles/datastore.user \
  roles/pubsub.publisher \
  roles/storage.objectAdmin \
  roles/artifactregistry.writer \
  roles/logging.logWriter \
  roles/modelarmor.user
do
  gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SA" --role="$ROLE"
done
```

IAM changes take up to a minute to propagate. A `403 Missing or insufficient
permissions` from Firestore immediately after granting `datastore.user` usually
means you were faster than IAM, not that the grant failed.

`roles/modelarmor.user` is easy to miss because nothing crashes without it. The
system degrades honestly instead: `security.model_armor.available` reports
`false` with the 403 in `detail`, the independent pattern screen still catches
the injection, and the case is still held for a human. If you want to see Model
Armor itself return `MATCH_FOUND`, grant the role.

Provision the state store and the topics:

```bash
gcloud firestore databases create --location=asia-southeast1
gcloud pubsub topics create shipment-events
gcloud pubsub topics create case-decisions
```

No Firestore indexes need to be created; the service is written to run against a
bare database. To skip Firestore entirely, deploy with `STORE_BACKEND=memory`.

Deploy:

```bash
gcloud run deploy vf-fraud-detection \
  --source . \
  --region asia-southeast1 \
  --allow-unauthenticated \
  --memory 1Gi --cpu 1 --timeout 300 \
  --min-instances 0 --max-instances 3 \
  --set-env-vars "PROJECT_ID=$PROJECT_ID,LOCATION=global,WORKER_MODE=ondemand,STORE_BACKEND=firestore,DECISIONS_TOPIC=case-decisions,CLAIM_LEASE_SECONDS=120"
```

This is the deployed configuration: `WORKER_MODE=ondemand` advances cases inside
request handlers, so the service costs nothing while idle. If you would rather
run a genuine always-on background loop, deploy with `WORKER_MODE=poll` **and**
add `--no-cpu-throttling --min-instances 1` — without both flags Cloud Run
suspends the container between requests and the loop stops advancing cases.

Verify — `/health` reports which store backend is live and the worker mode:

```bash
BASE=$(gcloud run services describe vf-fraud-detection \
  --region asia-southeast1 --format='value(status.url)')

curl -s $BASE/health          # expect store.backend=firestore, worker.mode=ondemand
curl -s $BASE/agents          # each agent reports the model it runs on

# Run the autonomous pipeline end to end
curl -s -X POST $BASE/api/v1/simulate
curl -s $BASE/api/v1/orchestrator/state   # poll; each poll also advances a step
```

Open `$BASE` in a browser for the dashboard.

### 3. Tear down

```bash
gcloud run services delete vf-fraud-detection --region asia-southeast1
```

---

## Reproducible testing

Every step below runs against the live service with no setup. Replace `$BASE`
with your own URL if you deployed your own copy.

```bash
BASE=https://vf-fraud-detection-304507056252.asia-southeast1.run.app
```

### Test 1 — the service is up and both models are wired

```bash
curl -s $BASE/health
curl -s $BASE/agents
```

Expect `status: healthy`, `store.backend: firestore`, and `/agents` reporting
`gemini-3.5-flash` for document/fraud/compliance and `gemini-3.5-flash-lite`
for investigation.

### Test 2 — the multi-model split is real, not just documented

Two calls, two different models in the response envelope:

```bash
# Fraud detection → gemini-3.5-flash
curl -s -X POST $BASE/api/v1/fraud/analyze \
  -H 'Content-Type: application/json' \
  -d '{"shipment_id":"T-1","origin":"Ho Chi Minh City","destination":"Hanoi",
       "weight_kg":150,"declared_value":50000000,"shipping_cost":1200000,
       "avg_route_cost":3000000,"shipper_name":"Thanh Phat Trading Co",
       "shipper_tx_count":2}' | grep -o '"model":"[^"]*"'

# Investigation → gemini-3.5-flash-lite
curl -s -X POST $BASE/api/v1/investigation/case \
  -H 'Content-Type: application/json' \
  -d '{"case_id":"T-1","trigger_reason":"reproducible test","risk_score":75}' \
  | grep -o '"model":"[^"]*"'
```

### Test 3 — the autonomous pipeline, one call and no further input

```bash
curl -s -X POST $BASE/api/v1/orchestrator/reset
curl -s -X POST $BASE/api/v1/simulate

# Poll. Each poll also advances the pipeline one step (WORKER_MODE=ondemand).
curl -s $BASE/api/v1/orchestrator/state
```

Repeat the state call until all three cases are terminal. Expect exactly three
different outcomes — `AUTO_CLEARED`, `HELD_FOR_REVIEW`, `ESCALATED` — from the
same code path with no human decision in between.

### Test 4 — the risk floor cannot be argued down

Send a dual-use shipment whose fields invite a low score. The verifier's
deterministic floor overrides whatever the model returns:

```bash
curl -s $BASE/api/v1/orchestrator/state | grep -o '"effective_risk":[0-9]*'
```

On the escalated case, `effective_risk` stays at or above the floor even when
`model_risk` is lower — `effective_risk = max(model_risk, floor)`.

### Test 5 — fail-closed governance

```bash
curl -s $BASE/api/v1/governance/boundaries
```

With no active boundary the system reports `SUSPENDED`: agents still analyse and
propose, but every protected action is refused. Publish one via
`POST /api/v1/governance/publish` and the same case executes.

### Test 6 — document intake, seven documents, one command

Seven bills of lading are committed to the repo, so this needs no setup beyond
cloning. Each is a real PDF, not a fixture stub, and each isolates one mechanism.

```bash
python scripts/test_documents.py        # one pass, ~5 minutes
python scripts/test_documents.py 3      # three passes, reports any disagreement
```

That script resets the board, uploads each document, and prints the state next to
the state this README claims — so a disagreement between the two is visible
immediately rather than something a reader has to take on trust. It exits non-zero
if any document lands outside its documented outcome. It is the same script that
produced the table below.

Gemini 3.5 Flash reads the PDFs directly — there is no OCR stage. Because
`WORKER_MODE=ondemand`, each upload returns the final `state` in the same
response, so expect 30 to 60 seconds per document.

| Document | Outcome | Why |
|---|---|---|
| `clean_bol.pdf` | `AUTO_CLEARED` | Tax ID and company resolve in the counterparty book to 412 prior shipments. No deterministic finding, compliance clears, released with no human. |
| `unknown_shipper_bol.pdf` | `HELD_FOR_REVIEW` or `PENDING_HUMAN` | Same lane and cargo, shipper not on file. Unverified history sets a floor of 45. Which of the two it lands on depends on how close the model's own score comes to that floor — see the note below. |
| `identity_spoof_bol.pdf` | `PENDING_HUMAN` | Carries a real customer's tax ID under a different company name. Reported as `identity_mismatch`, floor 75, `ESCALATED` proposed and refused pending a human. |
| `over_ceiling_bol.pdf` | `PENDING_HUMAN` | Nothing wrong with it: risk low, compliance cleared, `AUTO_CLEARED` proposed. Declared value USD 40,000 exceeds the delegated USD 25,000, so the boundary refuses the release. |
| `dual_use_bol.pdf` | `PENDING_HUMAN` | Unremarkable paperwork carrying controlled HS 8542. Dual-use floor of 85 against a low model score. |
| `dirty_bol.pdf` | `ESCALATED` | No tax ID, dual-use cargo, freight far below market, transhipments added after booking. The model agreed with the floor, so the system escalated it unaided. |
| `injected_bol.pdf` | `PENDING_HUMAN` | Blocked before the model was ever called; `security.model_invoked` is `false`. |

The first three are a matched set and the most useful comparison in the project.
The paperwork is of equal quality in all three; what differs is only whether the
counterparty resolves against our own records. Known shipper releases itself.
Unknown shipper waits. A shipper presenting someone else's tax number is treated
as worse than unknown, not better — which is the whole reason
[`shipper_registry.py`](shipper_registry.py) matches on tax ID *and* company name
rather than the number alone.

**Why four of these end in `PENDING_HUMAN`, and why one of them is not pinned.**
`PENDING_HUMAN` is reached by three different routes: blocked at intake, refused
by the value ceiling, or refused because the deterministic floor and the model
disagreed by 15 points or more (`score_disputed` in
[`governance.py`](governance.py)). That last trigger is why documents behave
differently from data events: the model is not shown the freight baseline or the
shipper's history, on purpose, so on an uploaded document the two sources of truth
are working from different information and a disagreement is common. The system's
answer — act on neither, hand it to a person — is the correct one, and it is why
`unknown_shipper_bol.pdf` is documented with two acceptable outcomes instead of
one. It was measured landing on both sides of that threshold. Pinning it to a
single state would give you a README that disagrees with your own run.

The injected document is still the one worth reading closely. It contains text
instructing the model to set the risk score to zero and skip compliance
screening. Model Armor screens the extracted text in overlapping windows *before*
Gemini is invoked, returns `MATCH_FOUND` at `LOW_AND_ABOVE`, and the request
stops there — `security.model_invoked` is `false` and no `extracted` record is
produced. The injection is recorded on the trace and the case is routed to a
human, not silently discarded. A second, independent pattern-based screen runs
regardless of whether Model Armor is reachable, so the path fails closed.

To regenerate the PDFs, or to make new ones:
`python scripts/make_sample_docs.py`.

The counterparty lookup that lets a document clear has its own self-check, since
it is the module that decides whether a shipment may be released without a human:

```bash
python scripts/check_registry.py   # 11 checks, exits non-zero on failure
```

It covers the case that matters most — a real tax number presented under the
wrong company name must be reported as `identity_mismatch` and must not inherit
that customer's clean history.

### Zero-setup path

`GET $BASE/demo` runs the fraud agent on a built-in sample shipment — one
request, no body, no configuration. Open `$BASE` in a browser for the dashboard,
which shows the per-case trace with the real model id and latency on every hop.

---

## Environment variables

| Variable | Description | Default |
|---|---|---|
| `PROJECT_ID` | GCP project used for Vertex AI, Firestore, Pub/Sub | `project-93ded24f-21c3-4f1b-a7d` |
| `LOCATION` | Vertex AI location — must be `global` for Gemini 3.5 Flash | `global` |
| `WORKER_MODE` | `ondemand` (advance inside requests, costs nothing idle) or `poll` (always-on background loop) | `ondemand` |
| `STORE_BACKEND` | `firestore` or `memory` | `firestore` |
| `CLAIM_LEASE_SECONDS` | How long a claimed case stays claimed before another worker may take it | `180` |
| `FRAUD_CLEAR_BELOW` | Risk below which auto-clear is considered | `40` |
| `INVESTIGATE_AT` | Risk at or above which investigation always opens | `70` |
| `DOCUMENT_BUCKET` | Cloud Storage bucket for document archive and stage ingestion. **Set this** — without it no case keeps a reviewable document, and the review panel has nothing to show a human | unset |
| `MODEL_ARMOR_TEMPLATE` | Model Armor template id; set to an empty value to disable the gate | `vf-document-intake` |
| `MODEL_ARMOR_LOCATION` | Model Armor region | `asia-southeast1` |
| `MODEL_ARMOR_WINDOW_CHARS` | Screening window size — see the findings section for why windowing is required | `400` |
| `MODEL_ARMOR_MAX_CHARS` | Ceiling on how much document text is screened | `20000` |
| `EXECUTOR_URL` | Executor service URL; unset means no identity split | unset |
| `DECISIONS_TOPIC` | Pub/Sub topic for published decisions | `case-decisions` |
| `NOTIFY_WEBHOOK_URL` | Outbound alert webhook; unset records the payload without sending | unset |
| `MAX_BULK_COUNT` | Cap on the volume-test endpoint | `10` |
| `PORT` | Port gunicorn binds to (set by Cloud Run) | `8080` |
| `GEMINI_MODEL` | Model for intake, fraud and compliance. Investigation ignores it. | `gemini-3.5-flash` |
| `MAX_DOCUMENT_MB` | Rejection threshold for uploaded documents | `20` |
| `MAX_ATTEMPTS` | Retries before a case is dead-lettered | `3` |
| `MAX_CONCURRENT` | Cases advanced in parallel | `3` |
| `MAX_CHAIN_STEPS` | Hops one case may take before the chain is cut. Guards against a case cycling forever, not a Gemini call budget. | `6` |
| `CHAIN_BUDGET_SECONDS` | Wall-clock ceiling for one case's chain | `120` |
| `POLL_SECONDS` | Loop interval in `WORKER_MODE=poll`. Ignored in `ondemand`. | `1.5` |
| `MODEL_ARMOR_WINDOW_OVERLAP` | Overlap between screening windows, so an injection split across a boundary is still seen whole | `120` |
| `MODEL_ARMOR_MAX_WINDOWS` | Cap on windows screened per document | `8` |
| `BOUNDARY_BOOTSTRAP_AUTHOR` | Name recorded as the publisher of the bootstrap boundary. Unset leaves the bootstrap author blank rather than inventing one. | unset |
| `DRIFT_MIN_SAMPLE` | Decisions required before drift is assessed at all | `8` |
| `DRIFT_MAX_AUTO_RELEASE_RATE` | Auto-release rate above which the agent is flagged as drifting permissive | `0.85` |
| `DRIFT_MAX_VETO_RATE` | Human-veto rate above which the agent's judgement is flagged as untrusted | `0.60` |
| `DRIFT_MAX_INJECTION_RATE` | Injection-attempt rate above which intake is flagged as under attack | `0.20` |

`config.py` holds the shared model registry and per-token pricing. Three of the
four agents — document intake, fraud detection and compliance — resolve their
model at call time through `model_config.get_model()`, which reads `GEMINI_MODEL`
at import and can be changed at runtime via `POST /api/v1/config/model` or the
dashboard dropdown. The registry holds four ids: `gemini-3.5-flash` (default),
`gemini-3.5-flash-lite`, `gemini-3.6-flash` and `gemini-3.7-flash`.

The investigation agent is the exception: `agents/investigation_agent.py` pins
`gemini-3.5-flash-lite` as a module constant, so the one hop chosen for being
cheap cannot be switched to an expensive model by a runtime call or a
misconfigured environment variable.

This is worth stating plainly because an earlier version of this section claimed
the opposite — that every model id was pinned in code and therefore immune to a
bad deploy. It is not. A wrong `GEMINI_MODEL` will silently move three agents
onto a different model, and the switch is deliberately exposed over HTTP so the
cost comparison in the dashboard is real rather than described. If you need the
stronger guarantee, remove the setter at `config.py:50` and the
`POST /api/v1/config/model` route in `main.py`.

### A note on cost

`WORKER_MODE=poll` requires `--no-cpu-throttling --min-instances=1`, which bills
around the clock — roughly 0.095 USD/hour in `asia-southeast1` whether or not any
shipment exists. That was the original design and it was the wrong default: it is
the polling equivalent of paying continuously to ask whether anything happened.

`ondemand` is the default for that reason. Cases advance inside request
handlers — the Pub/Sub push, the document upload, and the dashboard's own state
poll — so the pipeline runs when there is work and the service scales to zero
when there is not. `POST /api/v1/orchestrator/drain` is the explicit lever for
clearing a backlog from a script or Cloud Scheduler.

---

## Findings & learnings

**A human reviewer with no paperwork is not a control.** The review panel showed
the source PDF only for cases uploaded as a document; cases that arrived as a
Pub/Sub event or from the bulk simulator displayed "this case did not originate
from a document". So on exactly the volume path the system is built for, a person
was being asked to release or hold a container on a risk score and a state label,
with nothing to check either against. That is a rubber stamp with extra steps.

Now a case carries a document. Event-sourced shipments are rendered into a
bill of lading (`document_render.py`) and archived beside real uploads, so
`provenance.uri` resolves and the reviewer has something to read whenever
`DOCUMENT_BUCKET` is configured — without a bucket the archive step reports
`archived: false` and there is nothing to show, which is the one case where this
still fails.
The rendering is labelled `SYSTEM-GENERATED` on the page and `generated: true` in
the provenance, and the panel says so above the viewer: it is a faithful
rendering of the event that opened the case, not a scan of a shipper's original.
Passing a reconstruction off as an original would corrupt the audit trail the
system exists to keep.

The same review revealed the archive had never run in production at all —
`DOCUMENT_BUCKET` was unset on the Cloud Run service, so `document_store.archive`
returned `{"archived": false, "reason": "DOCUMENT_BUCKET not configured"}` and
even document-sourced cases had no viewable original. The graceful degradation
worked exactly as designed, which is why it went unnoticed: ingestion never
failed, it just quietly stopped keeping evidence.

**`asyncio.run()` per Flask request breaks a cached client.** The single-agent
endpoints were wrapped in a decorator that called `asyncio.run()`, which closes
its event loop on the way out. The Vertex AI client is built once and cached at
module level, so it held a reference to a loop that no longer existed and the
*second* analysis in a container's life failed with `Event loop is closed`. It
looked intermittent because Cloud Run kept starting fresh instances, and a single
curl against a cold container always passed. Every coroutine in the process now
runs on the one long-lived worker loop the orchestrator already uses.

**Documenting a constraint is not the same as enforcing it.** This README states
in two places that `LOCATION` must be `global`, and `cloudbuild.yaml` set it to
`asia-southeast1` — the exact value described two paragraphs below as returning
`404 NOT_FOUND`. The Cloud Build path was never the one used to deploy by hand,
so nothing exercised it. A constraint that matters belongs in the file that
applies it, with the reason next to it, not only in prose.

**A UI can invite an action it does not implement.** The intake card read "Drop a
bill of lading…" and had no drop handler, so dropping a PDF made the browser
navigate away from the dashboard and open the file. Every test had used the file
picker, so nothing caught it until the demo was scripted shot by shot. The fix
routes a dropped file into the existing input and clicks the existing button —
one upload path to keep correct rather than two that drift apart.

**Gemini 3.5 Flash is not on regional endpoints.** `us-central1` and
`asia-southeast1` both returned `404 NOT_FOUND` for
`publishers/google/models/gemini-3.5-flash`. Only `locations/global` served it.
The 404 message ("was not found **or your project does not have access to it**")
reads like an entitlement problem, which sent us looking at IAM before we
checked the endpoint — worth knowing.

**`ThinkingConfig` field is `thinking_budget`, not `thinking_budget_tokens`.**
The wrong name raises a pydantic validation error *before* any network call, so
the endpoint failed in ~3 ms. That latency in the Cloud Run request log is the
tell: a model failure would have taken seconds. I found the real field with
`python -c "import google.genai.types as t; print(list(t.ThinkingConfig.model_fields))"`.

**Cloud Build source deploys need three separate grants.** The default compute
service account needs `storage.objectAdmin` (read the uploaded source zip),
`artifactregistry.writer` (push the image) and `logging.logWriter` (or build
logs vanish, which is how I ended up debugging a "FAILURE" build with no log
output at all). A build whose docker step reports `SUCCESS` but produces no
entry under `results.images` has failed at push, not at build.

**Prompting for `response_mime_type="application/json"` is what makes the
multi-agent hand-off practical.** Each agent's output is consumed as data, not
re-parsed prose, so adding a fourth agent is a routing change rather than a
parsing project.

**Design insight:** this started as SQL predicates over historical aggregates.
Moving to Gemini let us delete most of that and describe the *intent* instead —
but it also means the output is no longer deterministic, so `temperature=0.1`
and an explicit `confidence` field in the schema are doing real work.

---

## Roadmap

The orchestration layer is live; what is still stubbed is the data it reasons
over. The agents currently receive route-cost baselines as request fields, and
sanctions screening is the model's own knowledge rather than a list lookup. The
next steps are BigQuery for real historical baselines, a genuine OFAC/UN/EU list
integration behind the compliance agent, and replacing the scripted simulator
with a production Pub/Sub subscription from the shipment system. `notify_webhook`
is wired but inert until `NOTIFY_WEBHOOK_URL` is set to a Slack, Teams or Google
Chat endpoint.

---

## Screenshots

[`docs/screenshots/`](docs/screenshots) holds 13 screenshots, all 3000x2000. They were captured against one board state so
they are mutually consistent — the counters in `01` are the same run as the cases
in `04`.

| | |
|---|---|
| `01-autonomous-operations.png` | Board, controls and outcome counters |
| `02-cost-and-agent-usage.png` | Per-agent tokens and dollars for the run |
| `03-live-event-feed-and-actions.png` | Event feed and actions taken on the operator's behalf |
| `04-review-queue.png` | Queue coloured by state |
| `05-case-evidence-fraud-agent.png` | Case detail and fraud findings |
| `06-compliance-and-investigation.png` | Compliance and investigation output, with model and latency |
| `07-source-document-original.png` | A shipper's uploaded PDF beside the deterministic findings |
| `08-findings-and-human-decision.png` | Deterministic checks and the release / block / request-info controls |
| `09-generated-bill-of-lading.png` | `SYSTEM-GENERATED` reconstruction for an event-sourced case |
| `10-delegation-boundary.png` | The boundary the agent is operating under |
| `11-boundary-publish-and-history.png` | Machine-readable permissions and version history |
| `12-single-agent-console.png` | One agent in isolation |
| `13-prompt-injection-blocked.png` | A document denied before any model was invoked |

---

## Repository layout

```
.
├── main.py                       Flask app, routes, async bridge, worker boot
├── orchestrator.py               Autonomous state machine + background worker
├── config.py                     Model registry, per-token pricing, runtime switch
├── governance.py                 Delegation Boundary + fail-closed execution gate
├── verifier.py                   Deterministic risk floor (no model consulted)
├── untrusted.py                  Schema whitelist for document-sourced fields
├── shipper_registry.py           Counterparty book: verifies a claimed shipper identity
├── model_armor.py                Windowed prompt-injection screening
├── store.py                      Case/event/audit state (Firestore, memory fallback)
├── document_render.py            Renders event-sourced shipments as a bill of lading
├── document_store.py             Cloud Storage document archive
├── executor_client.py            Calls the split-identity executor service
├── tools.py                      Actions taken on the operator's behalf
├── simulator.py                  Scripted shipment events for the demo
├── scripts/                      Not deployed; data generation and verification
│   ├── make_sample_docs.py       Generates the seven sample bills of lading
│   ├── seed_demo_board.py        Seeds the board to an exact outcome mix
│   ├── test_documents.py         Uploads every sample doc, checks the README table
│   └── check_registry.py         Self-check for the counterparty book
├── sample_docs/                  Seven committed sample PDFs, one per mechanism
├── agents/
│   ├── __init__.py               Public agent API
│   ├── _common.py                Shared JSON parsing, timing, response envelope
│   ├── document_agent.py         Multimodal PDF/image intake      — Flash
│   ├── fraud_detection_agent.py  Fraud scoring                    — Flash
│   ├── compliance_agent.py       Sanctions / trade / AML          — Flash
│   └── investigation_agent.py    Deep-dive, extended thinking     — Flash-Lite
├── static/
│   └── index.html                Dashboard (no build step)
├── infra/
│   └── model_armor_template.json  Filter config for the Model Armor template
├── docs/
│   ├── architecture.html         Diagram source
│   ├── architecture.png          Architecture diagram
│   ├── PROJECT_STORY.md          What was built and what it cost to learn
│   └── screenshots/              The 13 screenshots, 3000x2000
├── Dockerfile                    python:3.11-slim + gunicorn
├── cloudbuild.yaml               Cloud Build config
├── requirements.txt
├── .env.example
├── SUBMISSION.md                 Meet the Builders submission copy
└── README.md
```

## License

MIT — see [LICENSE](LICENSE).
