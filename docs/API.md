# API reference

Part of the [README](../README.md). Base URL: the Cloud Run service, or `http://localhost:8080` locally.

## Autonomous orchestration

These are the autonomous-orchestration endpoints. In the deployed
`WORKER_MODE=ondemand` configuration, `/api/v1/events/shipment` and
`/api/v1/events/document` run the case to a terminal state before responding,
usually 30 to 60 seconds. Under `WORKER_MODE=poll` they return once the case is
recorded and the background worker carries it on.

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/events/shipment` | POST | Shipment-created event sink. Accepts a bare shipment or a Pub/Sub push envelope. Idempotent per `shipment_id`. |
| `/api/v1/simulate` | POST | Inject the scripted three-shipment demo batch |
| `/api/v1/orchestrator/state` | GET | Full dashboard projection: cases, events, audit, counters |
| `/api/v1/orchestrator/case/<case_id>` | GET | One case with every agent hop, latency and action receipt |
| `/api/v1/orchestrator/tick` | POST | Advance the pipeline one step, for a script or Cloud Scheduler to call. In `WORKER_MODE=poll` the background loop does this. |
| `/api/v1/orchestrator/reset` | POST | Clear all cases, events and audit records. Published delegation boundaries deliberately survive: clearing a board is a demo convenience, revoking authority is not. Not for the live URL, whose board is shared demo data. |
| `/api/v1/orchestrator/drain` | POST | Run every pending case to a terminal state. The explicit lever for `WORKER_MODE=ondemand` — usable from Cloud Scheduler or to clear a backlog without waiting for the dashboard to poll it away one case at a time. |
| `/api/v1/events/document` | POST | Document intake. Multipart `file` (PDF or image). Screens for injection, transcribes, archives the original, then runs the case to a terminal state in the same request. |
| `/api/v1/events/storage` | POST | Cloud Storage notification sink — ingests a document dropped straight into the bucket. No subscription connects `shipment-documents` to this endpoint in the deployed project. |
| `/api/v1/ingest/bucket-sweep` | POST | Ingest every unprocessed object in `DOCUMENT_BUCKET`. A recovery path for missed notifications, and in the deployed project the only route from the bucket into the pipeline. |
| `/api/v1/simulate/bulk` | POST | Randomised shipments weighted like a real book of business. Capped at `MAX_BULK_COUNT`. |

## Review, governance and configuration

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
| `/internal/execute` | POST | Executes `publish_decision`, the only delegated action, on behalf of the analysis service. Served by `vf-executor` (same codebase, different service account), which is deployed but not called because `EXECUTOR_URL` is unset. Not under `/api/v1` because it is not meant as a public API. |

## Direct agent access

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

## Example

```bash
curl -s -X POST \
  https://vf-meet-the-builders-304507056252.asia-southeast1.run.app/api/v1/fraud/analyze \
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
