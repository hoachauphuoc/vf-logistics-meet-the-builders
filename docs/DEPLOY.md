# Deploy and configure

Part of the [README](../README.md).

## Prerequisites

- Python 3.11+
- `gcloud` CLI
- A Google Cloud project with billing enabled

## 1. Run locally

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

## 2. Deploy to Cloud Run

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

The deploy command does not create the Model Armor template either. The service
looks for one named `vf-document-intake` in `MODEL_ARMOR_LOCATION`, and
[`infra/model_armor_template.json`](../infra/model_armor_template.json) holds the
filter settings it expects. Without a template the screen cannot run, so
`model_armor.py` reports the gate as unavailable rather than trusting the document.
Create the template in the Model Armor console or API with those settings, or set
`MODEL_ARMOR_TEMPLATE` to an empty value to run without the gate.

Provision the state store, the document bucket and the topics:

```bash
gcloud firestore databases create --location=asia-southeast1
gcloud storage buckets create gs://YOUR_BUCKET --location=asia-southeast1
gcloud pubsub topics create shipment-events
gcloud pubsub topics create case-decisions
```

No Firestore indexes need to be created; the service is written to run against a
bare database. To skip Firestore entirely, deploy with `STORE_BACKEND=memory`.

Deploy:

```bash
gcloud run deploy vf-meet-the-builders \
  --source . \
  --region asia-southeast1 \
  --allow-unauthenticated \
  --memory 1Gi --cpu 1 --timeout 300 \
  --min-instances 0 --max-instances 3 \
  --set-env-vars "PROJECT_ID=$PROJECT_ID,LOCATION=global,WORKER_MODE=ondemand,STORE_BACKEND=firestore,DECISIONS_TOPIC=case-decisions,CLAIM_LEASE_SECONDS=120,DOCUMENT_BUCKET=YOUR_BUCKET"
```

The environment variables match the live service, which runs under a dedicated
`vf-analysis` service account instead of the default compute account.
`WORKER_MODE=ondemand` advances cases inside request handlers, so the service
costs nothing while idle. If you would rather run a genuine always-on background
loop, deploy with `WORKER_MODE=poll` **and** add
`--no-cpu-throttling --min-instances 1` — without both flags Cloud Run suspends
the container between requests and the loop stops advancing cases.

Verify — `/health` reports which store backend is live and the worker mode:

```bash
BASE=$(gcloud run services describe vf-meet-the-builders \
  --region asia-southeast1 --format='value(status.url)')

curl -s $BASE/health          # expect store.backend=firestore, worker.mode=ondemand
curl -s $BASE/agents          # each agent reports the model it runs on

# Run the autonomous pipeline end to end
curl -s -X POST $BASE/api/v1/simulate
curl -s $BASE/api/v1/orchestrator/state   # poll; each poll also runs one pending case
```

Open `$BASE` in a browser for the dashboard.

## 3. Tear down

```bash
gcloud run services delete vf-meet-the-builders --region asia-southeast1
```

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
| `MODEL_ARMOR_WINDOW_CHARS` | Screening window size. The filter missed an injection inside a 1,150-character document that it flagged when the same text was sent alone, so documents are screened in overlapping pieces as well as whole (`_windows()` in `model_armor.py`) | `400` |
| `MODEL_ARMOR_MAX_CHARS` | Ceiling on how much document text is screened | `20000` |
| `EXECUTOR_URL` | Executor service URL; unset means no identity split. Unset on the deployed service, so `publish_decision` runs under the analysis identity | unset |
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
handlers — the event POST, the document upload, and the dashboard's own state
poll — so the pipeline runs when there is work and the service scales to zero
when there is not. `POST /api/v1/orchestrator/drain` is the explicit lever for
clearing a backlog from a script or Cloud Scheduler.
