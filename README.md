# VF Logistics — Fraud Agents That Can Only Do What an Operator Allows

**Programme:** Google Gen AI Academy APAC 2026 — Meet the Builders
**Live URL:** https://vf-meet-the-builders-304507056252.asia-southeast1.run.app
**Also see:** [architecture diagram](docs/architecture.png) · [build story](docs/PROJECT_STORY.md) · [API](docs/API.md) · [deploy](docs/DEPLOY.md) · [findings](docs/FINDINGS.md) · [screenshots](docs/screenshots)

## At a glance

**What it is.** An autonomous compliance pipeline for shipping documents. A bill
of lading (PDF or scan) or a shipment event arrives, and four Gemini agents plus a
deterministic verifier take it to a decision without anyone stepping it through.
A person sees only the cases that fall outside a policy a person published.

**Why it is worth a look: the agents are not trusted.** A model here never
decides on its own authority.

| Strength | Evidence | Where to check | Read-only on the live service? |
|---|---|---|---|
| **Autonomous, end to end** | Three shipments with different risk profiles reached three different outcomes (`AUTO_CLEARED`, `HELD_FOR_REVIEW`, `ESCALATED`) in about 30 seconds with no human input. My own measurement: four consecutive runs from a reset board gave the same three. | Test 3, on your own deployment | The three outcomes are on the board: yes. Re-running them: no |
| **A model cannot talk its way past the controls** | `effective_risk = max(model_risk, deterministic floor)`. On the live board one document scored 88 by the model has an effective risk of 90, another scored 15 has 85, and a third scored 12 has 75. All three went to a human or were escalated. | [`verifier.py`](verifier.py), Test 4 | Yes, command below |
| **Prompt injection is screened before the agents act** | A PDF with a text layer is screened by Model Armor in overlapping windows before Gemini is invoked, and a blocked one is never transcribed (`security.model_invoked` is `false`). A scan has no text layer, so it is transcribed first and screened before any downstream agent, which is a weaker guarantee the case records. If Model Armor is unreachable the case goes to a human rather than being trusted. The backstop is the deterministic floor, not this screen. | [`model_armor.py`](model_armor.py), `injected_bol.pdf`, Test 6 | One blocked case is on the board: yes. The test itself: no |
| **Authority is published, not earned** | A human publishes a versioned, machine-readable Delegation Boundary. With none in force the system is `SUSPENDED` and refuses every protected action; the live service runs under `BOUNDARY-v1`. A clean shipment declared above the USD 25,000 ceiling is refused too: `CASE-VFL-2026-88453`, risk 8, waits for a person. | [`governance.py`](governance.py), Tests 5 and 6 | Boundary and cases: yes. `SUSPENDED`: only on a new deployment |
| **A forged identity is worse than none** | A real customer's tax ID under a different company name is `identity_mismatch` (floor 75) against 45 for an unknown shipper. The fields a document could use to vouch for itself are excluded from its schema. On the board `CASE-VFL-2026-88442`: model 12, effective 75. | [`shipper_registry.py`](shipper_registry.py), [`untrusted.py`](untrusted.py) | Yes |
| **Auditable** | Every agent hop records the model id and latency. The reviewer sees the shipper's original PDF, or a rendering labelled `SYSTEM-GENERATED` when there is none. | [`document_render.py`](document_render.py), screenshots 05 to 09 | Yes, in the dashboard |
| **Cost-aware by design** | Flash for the calls that decide, Flash-Lite for synthesis. Cases advance inside requests, so the service scales to zero instead of paying roughly 0.095 USD/hour, by my estimate, for an always-on loop. | *Why these choices* | Yes, `/health` shows `mode: ondemand` |
| **Reproducible, and honest about its limits** | Seven sample PDFs and one command that exits non-zero if any lands outside the outcome this README documents. A table says which parts of the design are deployed and which are not. | [`scripts/test_documents.py`](scripts/test_documents.py), *What is connected today* | No: the script wipes the board it targets |

**Google Cloud stack.** Gemini 3.5 Flash and Gemini 3.5 Flash-Lite on Vertex AI
through the Google GenAI SDK, with Cloud Run, Firestore, Cloud Storage, Pub/Sub
and Model Armor.

**Check it in 60 seconds.** No login. These calls are read-only and leave the live
board as it is. The board is demo data and can change, so the figures above are
those read on 2026-11-04.

```bash
BASE=https://vf-meet-the-builders-304507056252.asia-southeast1.run.app
curl -s $BASE/health                  # status healthy, store.backend firestore, mode ondemand
curl -s $BASE/agents                  # four agents: three on gemini-3.5-flash, one on gemini-3.5-flash-lite
curl -s $BASE/api/v1/governance/agent # state READY under BOUNDARY-v1
curl -s "$BASE/api/v1/orchestrator/state?drain=0" | python -c "
import sys, json
for c in json.load(sys.stdin)['cases']:
    r = c.get('reconciliation') or {}
    print(c['case_id'], c['state'], 'model', r.get('model_risk'), 'floor', r.get('risk_floor'), 'effective', r.get('effective_risk'))"
```

The last call lists every case with the model's score, the deterministic floor and
the effective risk, which is the maximum of the two. `drain=0` keeps it a pure
read, because a plain state call also runs one pending case.

**Honest limits.** `vf-executor` is deployed but not connected, the
`case-decisions` topic has no subscriber yet, sanctions screening is the model's
own knowledge rather than a list lookup, and the live board is demo data. The
section *What is connected today* has the detail.

---

Four Gemini agents screen logistics shipments for fraud and sanctions risk and run
deep-dive investigations without a human walking them through each step, while a
published Delegation Boundary, set by the operator, limits what they may do. Runs entirely on Google Cloud services: Gemini 3.5 Flash and
Gemini 3.5 Flash-Lite on Vertex AI + Cloud Run + Firestore + Pub/Sub +
Cloud Storage + Model Armor.

A shipment event arrives and nobody touches it again. Fraud detection and
compliance screening run on it in parallel, deterministic checks test what they
claim, and the result decides whether to open a deep investigation. The system
then acts: releasing the shipment, assigning an analyst, or holding the cargo and
drafting a suspicious activity report for human signature. Each action is a
recorded decision with a receipt on the case; no ERP or WMS is connected yet. In
the deployed configuration the workflow runs inside the request that delivered
the work, not in an always-on process (see *Why these choices*).

Measured on the deployed service, three shipments with deliberately different
risk profiles reached three different outcomes in roughly 30 seconds with no
human input: the injection call returned in 547ms, and the state poll carried the
cases from there.

| Shipment | Fraud risk | Compliance | Outcome | Actions executed |
|---|---|---|---|---|
| Clean garment export | 5/100 | cleared | `AUTO_CLEARED` | released for delivery |
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
scores decide whether cargo is held or released, so they get the stronger model.

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
document it is reading. The pipeline decides whether physical cargo is held or
released, so agent output is treated as a **claim**, not a finding.

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
a reviewer ten minutes. The live board shows the rule holding: the dual-use
document `CASE-VFL-2026-88464` has a model score of 15, a floor of 85 and an
effective risk of 85, and it waits for a person; the identity-spoof document
`CASE-VFL-2026-88442` has 12, 75 and 75. The command under *Check it in 60
seconds* lists them. An earlier test that coerced an agent into returning
`risk_score: 0` for a dual-use shipment recorded an effective risk of 90; that run
is not reproducible from the board as it stands now.

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
      │  vf-meet-the-builders                     │
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

### What is connected today

Read from Cloud Run and Pub/Sub on 2026-11-04. The design has more parts than the
deployed project currently uses, so this table separates the two.

| Part | State |
|---|---|
| `vf-meet-the-builders` | Serves the dashboard and API, and runs every agent and every action under the `vf-analysis` service account. |
| `vf-executor` | Deployed, not connected. `EXECUTOR_URL` is unset on the analysis service, so nothing calls it. |
| `case-decisions` topic | `publish_decision` publishes to it directly; `vf-analysis` holds `roles/pubsub.publisher` on the topic. It has no subscription, so no downstream system receives the messages yet. |
| `shipment-events` topic | Exists, with no subscription. Events arrive by `POST /api/v1/events/shipment`. |
| `shipment-documents` topic | Receives the bucket's `OBJECT_FINALIZE` notifications. It has no subscription, so nothing reaches `/api/v1/events/storage`. Documents placed in the bucket are ingested with `POST /api/v1/ingest/bucket-sweep`. |
| Cloud Scheduler | Not enabled. `tick` and `drain` work when called, and nothing calls them on a schedule. |

So the identity split is built and deployed but not in force: IAM does not stop
the analysis identity from publishing. The control running today is the boundary
check in [`governance.py`](governance.py). Setting `EXECUTOR_URL` would route
`publish_decision`, and only that action, through `vf-executor`; making the
separation real would also mean removing the `vf-analysis` publisher grant on the
topic.

### The autonomous workflow

```
  POST /api/v1/events/shipment ---+
  Scripted simulator           ---+--> Firestore cases (state INGESTED)
  Document upload              ---+
                                  |
     orchestrator.py: claims a case under a lease, performs one step, persists,
     repeats. Deployed as WORKER_MODE=ondemand, the request that delivered the
     work drives this; under WORKER_MODE=poll an asyncio loop does.
                                  |
       INGESTED --> fraud_detection + compliance agents, in parallel
                                  |
                                  v
       verifier.py: effective risk = max(model risk, deterministic floor)
                                  |
          +-- risk < 40, auto-clear permitted,
          |   compliance not flagged ---------> AUTO_CLEARED
          |                                       release_shipment()
          |
          +-- not flagged, risk < 70 ---------> HELD_FOR_REVIEW
          |                                       assign_analyst()
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

       Every action passes the execution gate first; a refused action sends
       the case to PENDING_HUMAN.

       Any step failing 3 times, retried after 5s then 10s --> DEAD_LETTER

       Terminal decisions are published to Pub/Sub case-decisions, where ERP /
       WMS / billing would subscribe (none does yet), and every action lands
       in audit_log.
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
  the clock, cases advance *inside* request handlers: the shipment event POST and
  the document upload run the case to a terminal state, and the dashboard's own
  state poll advances anything left over. The service scales to zero when no
  shipment exists. `POST /api/v1/orchestrator/tick` and `/drain` can clear a
  backlog from a script or Cloud Scheduler (no scheduler job is configured in the
  deployed project), and `WORKER_MODE=poll` still exists for deployments that
  would rather pay for a true always-on loop.
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
| Messaging | **Pub/Sub** — `case-decisions` out, no subscriber yet; `shipment-events` and `shipment-documents` exist but nothing consumes them |
| Web | Flask + gunicorn, flask-cors |
| Frontend | Vanilla HTML/CSS/JS, no build step |
| Runtime | Python 3.11-slim container |

Google Cloud usage check:

| Requirement | Where it is met |
|---|---|
| Gemini 3.5 or newer, via Vertex AI | `gemini-3.5-flash` and `gemini-3.5-flash-lite` |
| A Google agent framework | Google GenAI SDK |
| Google Cloud infrastructure | Cloud Run (compute), Firestore (case state and audit trail), Cloud Storage (document archive), Pub/Sub (decision publishing) |
| Runs without a person stepping it through | The request that delivers the work runs the case through every step with no further input; `WORKER_MODE=poll` adds a background loop that the deployed service does not use |
| Multi-step workflow | Four agents chained with conditional branching |
| Takes meaningful action | Release and hold dispositions recorded, analysts assigned, SAR drafts produced, decisions published |

> Firestore, Cloud Storage and Pub/Sub publishing are used on the live path, not
> merely pinned. BigQuery is not used yet; see *Roadmap*.

---

## API

Endpoint reference, request and response examples: [docs/API.md](docs/API.md).

---

## Run and deploy

Local run, Cloud Run deploy and tear down: [docs/DEPLOY.md](docs/DEPLOY.md). Environment variables and the cost note are in the same file.

---

## Reproducible testing

Tests 1, 2 and 4, the read-only call in Test 5 and the zero-setup path are safe on
the live service: they need no setup and leave the board as it is. Test 2 does run
the agents, but their direct endpoints never write to the board. Replace `$BASE`
with your own URL if you deployed your own copy.

> **Test 3, Test 6 and publishing a boundary in Test 5 are for your own deployment,
> not the live URL.** The live board is shared demo data: the cases shown in the
> screenshots and the video. Test 3 adds cases to it, Test 6 deletes every case,
> event and audit record on it, and publishing replaces the boundary in force. The
> live dashboard is there to browse. **Clear board**, the inject and upload buttons,
> **Publish delegation boundary** and the review decisions all change that data.

```bash
BASE=https://vf-meet-the-builders-304507056252.asia-southeast1.run.app
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

Run this on your own deployment: `simulate` adds three cases to whichever board it
reaches. It needs no reset, because each run gets its own shipment ids and the
response lists the new `case_ids`. The block uses `$OWN_BASE` rather than `$BASE`
so that pasting it cannot reach the live service.

A new deployment has no boundary, and without one every case stops at
`PENDING_HUMAN`, so publish the default template first. It is the template the live
service runs under.

```bash
OWN_BASE=https://YOUR-SERVICE-URL   # printed by gcloud run deploy; never the live URL

# Once per deployment.
curl -s -X POST $OWN_BASE/api/v1/governance/publish \
  -H 'Content-Type: application/json' -d '{"author":"YOUR NAME"}'

curl -s -X POST $OWN_BASE/api/v1/simulate

# Poll. Each poll also runs one pending case to completion (WORKER_MODE=ondemand).
curl -s $OWN_BASE/api/v1/orchestrator/state
```

Repeat the state call until the three new cases are terminal. Expect exactly three
different outcomes — `AUTO_CLEARED`, `HELD_FOR_REVIEW`, `ESCALATED` — from the
same code path with no human decision in between.

### Test 4 — the risk floor cannot be argued down

Read the cases already on the board. `drain=0` keeps the call a pure read, because
a plain state call also runs one pending case. The verifier's deterministic floor
overrides whatever the model returns:

```bash
curl -s "$BASE/api/v1/orchestrator/state?drain=0" | grep -o '"effective_risk":[0-9]*'
```

On the escalated case, `effective_risk` stays at or above the floor even when
`model_risk` is lower — `effective_risk = max(model_risk, floor)`. The call under
*Check it in 60 seconds* prints all three values per case: on 2026-11-04 it showed
model 15 against effective 85, and model 12 against effective 75.

### Test 5 — fail-closed governance

```bash
curl -s $BASE/api/v1/governance/boundaries
```

With no active boundary the system reports `SUSPENDED`: agents still analyse and
propose, but every protected action is refused. The live service has a boundary in
force, so there `GET /api/v1/governance/agent` reports `state: READY` under
`BOUNDARY-v1`; `SUSPENDED` is what a new deployment shows until you publish one
via `POST /api/v1/governance/publish`, after which the same case executes.

### Test 6 — document intake, seven documents, one command

Seven bills of lading are committed to the repo, so the only setup is a deployment
of your own with the default boundary published, as in Test 3. Each is a real PDF,
not a fixture stub, and each isolates one mechanism.

Run this on your own deployment: every pass starts by deleting every case, event
and audit record on the target. `--base` is required, and the script refuses the
live service before sending anything unless you also pass
`--confirm-wipe-live-board`, which exists for whoever maintains that board.

```bash
python scripts/test_documents.py --base $OWN_BASE      # one pass, ~5 minutes
python scripts/test_documents.py --base $OWN_BASE 3    # three passes, reports any disagreement
```

Each pass resets the board, uploads each document, and prints the state next to
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

## Findings and learnings

What went wrong while building this and what it changed: [docs/FINDINGS.md](docs/FINDINGS.md).

---

## Roadmap

The orchestration layer is live; what is still stubbed is the data it reasons
over and the systems it hands off to. The agents currently receive route-cost
baselines as request fields, and sanctions screening is the model's own knowledge
rather than a list lookup. The next steps are BigQuery for real historical
baselines, a genuine OFAC/UN/EU list integration behind the compliance agent,
replacing the scripted simulator with a production Pub/Sub subscription from the
shipment system, connecting `vf-executor` so the identity split is in force, and
attaching a subscriber to `case-decisions` so a decision reaches an ERP or WMS.
`notify_webhook` is wired but inert until `NOTIFY_WEBHOOK_URL` is set to a Slack,
Teams or Google Chat endpoint.

---

## Screenshots

[`docs/screenshots/`](docs/screenshots) holds 13 screenshots, all 3000x2000. All but
`12` were captured from the live service on 2026-11-04 against one board state, so
they are mutually consistent — the counters in `01` are the same run as the cases
in `04`. The capture used a headless browser, which has no PDF viewer, so the PDF
panels in `07`, `09` and `13` show the same files drawn as images. `12` needs a
model call to reproduce, so it comes from an earlier run, and the badges of the
original event are painted out of its header.

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
├── orchestrator.py               Request-driven state machine (optional poll loop)
├── config.py                     Model registry, per-token pricing, runtime switch
├── governance.py                 Delegation Boundary + fail-closed execution gate
├── verifier.py                   Deterministic risk floor (no model consulted)
├── untrusted.py                  Schema whitelist for document-sourced fields
├── shipper_registry.py           Counterparty book: verifies a claimed shipper identity
├── model_armor.py                Windowed prompt-injection screening
├── store.py                      Case/event/audit state (Firestore, memory fallback)
├── document_render.py            Renders event-sourced shipments as a bill of lading
├── document_store.py             Cloud Storage document archive
├── executor_client.py            Calls the executor service; idle while EXECUTOR_URL is unset
├── tools.py                      Actions taken on the operator's behalf
├── simulator.py                  Scripted shipment events for the demo
├── scripts/                      Not deployed; data generation and verification
│   ├── make_sample_docs.py       Generates the seven sample bills of lading
│   ├── seed_demo_board.py        Seeds a board to an exact outcome mix; BASE points at the live service, so change it first
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

## Provenance

This repository is a copy of
[CHAUPHUOCHOA/vf-logistics-hackathon-google](https://github.com/CHAUPHUOCHOA/vf-logistics-hackathon-google),
which I originally built for the All Things Agentic Hackathon 2026. The code and
architecture are the same work by the same author. This copy only removes the
branding of that event, adds an MIT `LICENSE`, and rewrites `SUBMISSION.md` for
Google Gen AI Academy APAC — Meet the Builders. The original repository and its
commit history remain the source of record.

---

## License

MIT — see [LICENSE](LICENSE).
