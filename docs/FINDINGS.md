# Findings and learnings

Part of the [README](../README.md). Problems met while building and what they changed.

**A human reviewer with no paperwork is not a control.** The review panel showed
the source PDF only for cases uploaded as a document; cases that arrived as a
shipment event or from the bulk simulator displayed "this case did not originate
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
reads like an entitlement problem, which sent the author looking at IAM before
checking the endpoint — worth knowing.

**`ThinkingConfig` field is `thinking_budget`, not `thinking_budget_tokens`.**
The wrong name raises a pydantic validation error *before* any network call, so
the endpoint failed in ~3 ms. That latency in the Cloud Run request log is the
tell: a model failure would have taken seconds. The real field turned up with
`python -c "import google.genai.types as t; print(list(t.ThinkingConfig.model_fields))"`.

**Cloud Build source deploys need three separate grants.** The default compute
service account needs `storage.objectAdmin` (read the uploaded source zip),
`artifactregistry.writer` (push the image) and `logging.logWriter` (or build
logs vanish, which led to debugging a "FAILURE" build with no log
output at all). A build whose docker step reports `SUCCESS` but produces no
entry under `results.images` has failed at push, not at build.

**Prompting for `response_mime_type="application/json"` is what makes the
multi-agent hand-off practical.** Each agent's output is consumed as data, not
re-parsed prose, so adding a fourth agent is a routing change rather than a
parsing project.

**Design insight:** this started as SQL predicates over historical aggregates.
Moving to Gemini made it possible to delete most of that and describe the *intent* instead —
but it also means the output is no longer deterministic, so `temperature=0.1`
and an explicit `confidence` field in the schema are doing real work.
