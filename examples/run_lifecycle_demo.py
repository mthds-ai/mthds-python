"""Run-lifecycle demo against the hosted MTHDS API.

`start_and_wait` is the whole lifecycle in one call (start → poll → result), so
each run below is a single line. Two ways to select the same batch method:

    A. inline bundle  — start_and_wait(mthds_contents=[bundle], inputs=...)
    B. stored method  — start_and_wait(inputs=..., extra={"method_id": METHOD_ID})

`method_id` is a hosted-API extension arg, so it rides the generic `extra`
passthrough — never the SDK's named params. Credentials resolve from
`~/.mthds/config` (`MTHDS_API_URL` / `MTHDS_API_KEY`). Run it from the repo:

    .venv/bin/python examples/run_lifecycle_demo.py
"""

import asyncio
from pathlib import Path

from mthds.protocol.pipeline_inputs import PipelineInputs
from mthds.runners.api.client import MthdsAPIClient
from mthds.runners.api.runs import WaitForResultOptions

BUNDLE_PATH = Path(__file__).parent / "invoice_reimbursement.mthds"
METHOD_ID = "mt_1781165499447_dmp33iuxl"

# Two invoice PDFs already in pipelex storage (any https://, data: or pipelex-storage:// URL works).
INVOICE_URLS = [
    "pipelex-storage://a60500bb-5e82-4864-99cd-b37ed4b5bb14/assets/fdc4b8e2-4b29-452c-99ea-b7a7e8c9e294.pdf",
    "pipelex-storage://a60500bb-5e82-4864-99cd-b37ed4b5bb14/assets/fe4dae31-6ce4-4852-bb5a-ffeb89fd6ec9.pdf",
]
INPUTS: PipelineInputs = {"invoices": {"concept": "Document", "content": [{"url": url} for url in INVOICE_URLS]}}
WAIT = WaitForResultOptions(timeout_seconds=300)


async def main() -> None:
    async with MthdsAPIClient() as client:
        version = await client.version()
        print(f"version: protocol {version.protocol_version}, runner {version.runner_version}")

        print(f"A. inline bundle ({BUNDLE_PATH.name}):")
        run_a = await client.start_and_wait(mthds_contents=[BUNDLE_PATH.read_text(encoding="utf-8")], inputs=INPUTS, wait_options=WAIT)
        print(run_a.main_stuff)

        print(f"B. stored method ({METHOD_ID}):")
        run_b = await client.start_and_wait(inputs=INPUTS, extra={"method_id": METHOD_ID}, wait_options=WAIT)
        print(run_b.main_stuff)


if __name__ == "__main__":
    asyncio.run(main())
