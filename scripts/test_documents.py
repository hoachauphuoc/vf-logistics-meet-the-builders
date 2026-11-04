"""
Upload every sample bill of lading and report the outcome of each.

This is the script that produced the outcome table in the README. It is the same
one a reader runs, on their own deployment of the same code, so a mismatch between
the table and their result is a bug in one of the two rather than a difference in
method.

Each document is uploaded to /api/v1/events/document. WORKER_MODE=ondemand means
the request returns only once the case has reached a terminal state, so no polling
is needed - expect 30 to 60 seconds per document.

The board is reset before each pass. Case ids derive from the B/L number in the
document and ingestion is idempotent on shipment id, so uploading the same file
twice without a reset returns the first case unchanged rather than re-running it.
That is correct behaviour and it is also why a repeat pass needs the reset.

The reset deletes every case, event and audit record on the target, so --base is
required and there is no default. The live board is shared demo data: the script
refuses it before sending anything, unless --confirm-wipe-live-board is also given.

A new deployment has no delegation boundary, and without one every document stops
at PENDING_HUMAN. Publish the default template first; the README shows how.

Usage:
    python scripts/test_documents.py --base URL      # one pass
    python scripts/test_documents.py --base URL 3    # three passes, reports agreement

Exits non-zero if any document lands outside its expected state(s), if repeated
passes disagree where a single state was expected, or if it refuses the target.
"""

from __future__ import annotations

import argparse
import http.client
import io
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlsplit

# The shared demo board lives in one project's Firestore, so a reset reaches it
# through every Cloud Run service in that project, under either URL form Cloud Run
# issues. Matching the project's part of the hostname covers all of them, and a
# deployment in another project never matches, even under the same service name.
LIVE_HOST_SUFFIXES = (
    "-304507056252.asia-southeast1.run.app",
    "-bdg2ip66aa-as.a.run.app",
)

# Set by main() from --base, and only once that URL has passed the live check.
BASE = ""

# Resolved from this file, not the working directory, so the script runs the same
# from the repository root or from inside scripts/.
SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_docs"

# (filename, accepted states, what the document is testing)
#
# Expectations are deliberate: all but one of these is decided by a deterministic
# floor in verifier.py or a gate in governance.py, not by where the fraud model
# happens to land.
#
# unknown_shipper_bol.pdf is the exception and is listed with two accepted states
# on purpose. Its outcome turns on the score_disputed trigger, which fires when
# the deterministic floor exceeds the model score by 15 or more - so it depends on
# a model judgement near a threshold, and it has been observed landing either side.
# Pinning it to one state would produce a README that a reader could fairly call
# wrong. Both states are correct behaviour: one queues the case for review, the
# other escalates it to a human because the two sources of truth disagreed.
#
# PENDING_HUMAN arrives by three different routes, which is why this script
# reports the proposed outcome and the gate's refusal alongside the state. The
# state alone does not distinguish "blocked before the model ran" from "the
# analysis finished and the boundary would not let it act".
DOCUMENTS: list[tuple[str, str, tuple[str, ...], str]] = [
    ("clean_bol.pdf", "VFL-2026-88420", ("AUTO_CLEARED",),
     "shipper resolves in the counterparty book; released with no human"),
    ("unknown_shipper_bol.pdf", "VFL-2026-88431",
     ("HELD_FOR_REVIEW", "PENDING_HUMAN"),
     "shipper not on file and the goods are thinly priced: floor 45, and whether "
     "the model lands within 15 of it decides review queue vs human"),
    ("identity_spoof_bol.pdf", "VFL-2026-88442", ("PENDING_HUMAN",),
     "a known customer's tax ID under another company name: floor 75, disputed"),
    ("over_ceiling_bol.pdf", "VFL-2026-88453", ("PENDING_HUMAN",),
     "low risk and compliance clear, but value exceeds the delegated ceiling"),
    ("dual_use_bol.pdf", "VFL-2026-88464", ("PENDING_HUMAN",),
     "controlled HS code 8542: floor 85 against a low model score, disputed"),
    ("dirty_bol.pdf", "VFL-2026-91177", ("ESCALATED",),
     "no tax ID, dual-use cargo, freight below market, route changed; the model "
     "agreed with the floor, so the system escalated it unaided"),
    # Blocked at intake, so no shipment record is ever extracted and the case is
    # keyed by a content hash instead of a B/L number.
    ("injected_bol.pdf", "", ("PENDING_HUMAN",),
     "prompt injection blocked before the model is invoked"),
]

TERMINAL = {"AUTO_CLEARED", "HELD_FOR_REVIEW", "ESCALATED", "PENDING_HUMAN",
            "DEAD_LETTER"}


def is_live(base: str) -> bool:
    """Whether this URL reaches the shared demo board, whatever its case or port."""
    host = (urlsplit(base).hostname or "").rstrip(".")
    return host.endswith(LIVE_HOST_SUFFIXES)


def post_json(path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body or {}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.load(resp)


def upload(filename: str) -> dict | None:
    """
    POST a file as multipart/form-data, without adding a dependency.

    Returns None if the connection dropped rather than raising. Cloud Run closes
    a request at its own timeout, and a document that takes longer than that to
    reach a terminal state loses the connection even though the case continues to
    completion on the server. Losing the whole run to that would be a defect in
    the harness, not a result, so the caller recovers the outcome from the board.
    """
    payload = (SAMPLE_DIR / filename).read_bytes()

    boundary = uuid.uuid4().hex
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="file"; '
               f'filename="{filename}"\r\n'.encode())
    body.write(b"Content-Type: application/pdf\r\n\r\n")
    body.write(payload)
    body.write(f"\r\n--{boundary}--\r\n".encode())

    req = urllib.request.Request(
        BASE + "/api/v1/events/document",
        data=body.getvalue(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.load(resp)
    except (ConnectionResetError, TimeoutError, http.client.HTTPException,
            urllib.error.URLError):
        return None


def await_case(shipment_id: str, timeout_s: int = 240) -> dict | None:
    """
    Find a case on the board and wait for it to settle.

    Used when the upload connection dropped. An empty shipment_id means the
    document was blocked at intake, so there is no extracted record to key on and
    the case carries a content hash instead.
    """
    waited = 0
    while waited < timeout_s:
        cases = list(board().values())
        if shipment_id:
            case = next((c for c in cases
                         if c.get("shipment_id") == shipment_id), None)
        else:
            case = next((c for c in cases
                         if str(c.get("case_id") or "").startswith("CASE-BLOCKED-")),
                        None)
        if case and case.get("state") in TERMINAL:
            return case
        time.sleep(6)
        waited += 6
    return None


def board() -> dict[str, dict]:
    """Cases currently on the target board, keyed by shipment id."""
    with urllib.request.urlopen(BASE + "/api/v1/orchestrator/state",
                                timeout=120) as resp:
        cases = json.load(resp)["cases"]
    return {c.get("shipment_id") or c.get("case_id"): c for c in cases}


def describe(case: dict | None, blocked: bool) -> str:
    """
    One line saying why the case ended where it did.

    Three different mechanisms produce PENDING_HUMAN and the state does not say
    which, so it is spelled out here rather than left for a reader to infer.
    """
    if blocked:
        return "blocked at intake, model never invoked"
    if case is None:
        return ""

    denials = case.get("gate_denials") or []
    if denials:
        proposed = case.get("proposed_outcome") or "?"
        reason = (denials[0].get("reason") or "").replace("DENIED: ", "")
        return f"proposed {proposed}, refused by boundary: {reason}"

    risk = case.get("risk_score")
    floor = (case.get("reconciliation") or {}).get("risk_floor")
    model = (case.get("reconciliation") or {}).get("model_risk")
    return f"effective risk {risk} (model {model}, floor {floor})"


def one_pass(index: int, total: int) -> dict[str, tuple[str, str]]:
    if total > 1:
        print(f"\n=== pass {index} of {total}", flush=True)

    cleared = post_json("/api/v1/orchestrator/reset").get("cleared")
    print(f"board reset ({cleared} cases cleared)", flush=True)

    results: dict[str, tuple[str, str]] = {}
    blocked_flags: dict[str, bool] = {}
    case_ids: dict[str, str] = {}

    for filename, shipment_id, accepted, _ in DOCUMENTS:
        resp = upload(filename)

        if resp is None:
            # Connection dropped; the case is still running server-side.
            case = await_case(shipment_id)
            if case is None:
                results[filename] = ("NO RESULT", "connection dropped and the "
                                                  "case never settled")
                print(f"  DIFF {filename:<24} NO RESULT", flush=True)
                continue
            state = case.get("state") or "?"
            case_ids[filename] = case.get("case_id") or ""
            blocked_flags[filename] = not shipment_id
            note = " (recovered from the board after the connection dropped)"
        else:
            state = resp.get("state") or "?"
            case_ids[filename] = resp.get("case_id") or ""
            blocked_flags[filename] = bool(resp.get("blocked"))
            note = ""

        results[filename] = (state, "")
        mark = "ok  " if state in accepted else "DIFF"
        print(f"  {mark} {filename:<24} {state:<16} expected "
              f"{' or '.join(accepted)}{note}", flush=True)

    # One board read afterwards, to recover why each case landed where it did.
    cases = board()
    by_case_id = {c.get("case_id"): c for c in cases.values()}
    for filename in list(results):
        state, _ = results[filename]
        case = by_case_id.get(case_ids.get(filename))
        results[filename] = (state, describe(case, blocked_flags.get(filename, False)))

    return results


def main() -> int:
    global BASE

    parser = argparse.ArgumentParser(
        description="Upload every sample document to a deployment and compare each "
                    "outcome with the README. Every pass first deletes all cases, "
                    "events and audit records on that deployment.",
        # A confirmation flag has to be typed in full, not abbreviated to --c.
        allow_abbrev=False,
    )
    parser.add_argument("passes", nargs="?", type=int, default=1,
                        help="how many passes to run (default: 1)")
    parser.add_argument("--base", required=True, metavar="URL",
                        help="your own deployment, such as https://YOUR-SERVICE-URL")
    parser.add_argument("--confirm-wipe-live-board", action="store_true",
                        help="allow --base to be the shared live board, which is "
                             "otherwise refused")
    args = parser.parse_args()

    # A value that does not parse to a host could not be recognised as the live
    # service, so it is rejected here rather than treated as some other deployment.
    target = urlsplit(args.base)
    if target.scheme not in ("http", "https") or not target.hostname:
        parser.error(f"--base needs a full http(s) URL, got {args.base!r}")

    if is_live(args.base) and not args.confirm_wipe_live_board:
        print(f"refusing to run: {args.base} is the shared live demo board.\n"
              "Every pass starts by deleting all of its cases, events and audit "
              "records. Nothing was sent.\n"
              "Point --base at your own deployment, or add "
              "--confirm-wipe-live-board if you mean to wipe it.", file=sys.stderr)
        return 2

    BASE = args.base.rstrip("/")
    passes = args.passes

    observed = [one_pass(i + 1, passes) for i in range(passes)]

    print("\n" + "=" * 78)
    print(f"{'document':<24} {'expected':<32} observed")
    print("-" * 78)

    failures = 0
    for filename, _shipment_id, accepted, note in DOCUMENTS:
        states = [run[filename][0] for run in observed]
        unique = sorted(set(states))
        shown = unique[0] if len(unique) == 1 else " / ".join(unique)

        stray = [s for s in unique if s not in accepted]
        if stray:
            failures += 1
            status = "  MISMATCH"
        else:
            status = ""

        print(f"{filename:<24} {' or '.join(accepted):<32} {shown}{status}")
        print(f"{'':<24} why: {observed[-1][filename][1]}")
        print(f"{'':<24} tests: {note}")
        print()

    print("-" * 78)
    if failures:
        print(f"{failures} of {len(DOCUMENTS)} landed outside their expected "
              f"state(s) across {passes} pass(es).")
        print("If this is a fresh clone with the default boundary published, the "
              "README table is wrong and should be corrected rather than "
              "explained away.")
    else:
        print(f"All {len(DOCUMENTS)} documents matched across {passes} pass(es).")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
