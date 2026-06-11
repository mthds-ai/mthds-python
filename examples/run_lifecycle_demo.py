"""End-to-end demo of the MthdsAPIClient run lifecycle against the hosted API.

Exercises every run-lifecycle convenience the client exposes (these are SDK
functions on top of the MTHDS Protocol, not protocol routes themselves):

1. ``version``          — the public protocol handshake.
2. Start & wait         — ``start`` immediately followed by ``wait_for_result``.
3. Start only           — ``start`` returns the 202 ack (grab the
                          ``pipeline_run_id``; the run keeps executing).
4. Poll & get result    — ``wait_for_result`` by that ``pipeline_run_id``
                          (honors the server's ``Retry-After`` between polls).
5. Get result once      — ``get_run_result`` single-shot on the finished run.

Credentials resolve exactly like the CLI (env > ``~/.mthds/config`` > defaults):
``MTHDS_API_KEY`` / ``MTHDS_API_URL``, with the legacy ``PIPELEX_*`` aliases
still honored. Run it from the repo:

    .venv/bin/python examples/run_lifecycle_demo.py
"""

import asyncio
import time
from pathlib import Path

from mthds.models.pipeline_inputs import PipelineInputs
from mthds.runners.api_runner import MthdsAPIClient
from mthds.runners.runs import RunResultCompleted, RunResults, WaitForResultOptions

BUNDLE_PATH = Path(__file__).parent / "invoice_reimbursement.mthds"

# Two invoice PDFs already in pipelex storage (replace with your own assets —
# any https://, data: or pipelex-storage:// URL works).
INVOICE_URLS = [
    "pipelex-storage://a60500bb-5e82-4864-99cd-b37ed4b5bb14/assets/fdc4b8e2-4b29-452c-99ea-b7a7e8c9e294.pdf",
    "pipelex-storage://a60500bb-5e82-4864-99cd-b37ed4b5bb14/assets/fe4dae31-6ce4-4852-bb5a-ffeb89fd6ec9.pdf",
]

INPUTS: PipelineInputs = {
    "invoices": {
        "concept": "Document",
        "content": [{"url": url} for url in INVOICE_URLS],
    },
}

WAIT = WaitForResultOptions(timeout_seconds=300)


def summarize(results: RunResults) -> None:
    """Print one line per invoice decision from the batch output."""
    items = results.main_stuff if isinstance(results.main_stuff, list) else [results.main_stuff]
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            print(f"   invoice {index + 1}: (unexpected item shape: {type(item).__name__})")
            continue
        invoice = item.get("invoice_data") or {}
        decision = item.get("reimbursement") or {}
        print(
            f"   invoice {index + 1}: {invoice.get('vendor_name')} "
            f"{invoice.get('total_amount')} {invoice.get('currency')} "
            f"-> {decision.get('decision')} ({decision.get('reason', '')[:80]})"
        )


async def main() -> None:
    client = MthdsAPIClient()
    bundle = BUNDLE_PATH.read_text(encoding="utf-8")

    version = await client.version()
    print(f"1. version: {version.implementation} v{version.implementation_version} (protocol {version.protocol_version})")

    # --- Scenario A: start & wait in one flow -------------------------------
    started_at = time.monotonic()
    ack_a = await client.start(mthds_contents=[bundle], inputs=INPUTS)
    print(f"2. start & wait: started pipeline_run_id={ack_a.pipeline_run_id}")
    results_a = await client.wait_for_result(ack_a.pipeline_run_id, WAIT)
    print(f"   completed in {time.monotonic() - started_at:.1f}s")
    summarize(results_a)

    # --- Scenario B: start only, then poll by id ----------------------------
    ack_b = await client.start(mthds_contents=[bundle], inputs=INPUTS)
    print(f"3. start only: pipeline_run_id={ack_b.pipeline_run_id}")

    status = await client.get_run_status(ack_b.pipeline_run_id)
    print(f"   get_run_status: status={status.status} retry_after={status.retry_after_seconds}")

    started_at = time.monotonic()
    results_b = await client.wait_for_result(ack_b.pipeline_run_id, WAIT)
    print(f"4. poll & get result: completed in {time.monotonic() - started_at:.1f}s")
    summarize(results_b)

    # --- Scenario C: single-shot get on the finished run --------------------
    single = await client.get_run_result(ack_b.pipeline_run_id)
    if isinstance(single, RunResultCompleted):
        print("5. get_run_result (single shot): COMPLETED — same run fetched without polling")
    else:
        print(f"5. get_run_result (single shot): unexpected state {type(single).__name__}")


if __name__ == "__main__":
    asyncio.run(main())
