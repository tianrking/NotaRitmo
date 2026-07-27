import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from app.config import settings
from app.workflows.ingest import (
    MeetingIngestWorkflow,
    extract_activity,
    graph_activity,
    normalize_activity,
    prepare_audio_activity,
    transcribe_activity,
)


async def main() -> None:
    while True:
        try:
            client = await Client.connect(
                settings.temporal_address,
                namespace=settings.temporal_namespace,
            )
            break
        except Exception:
            await asyncio.sleep(3)

    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[MeetingIngestWorkflow],
        activities=[
            prepare_audio_activity,
            transcribe_activity,
            normalize_activity,
            extract_activity,
            graph_activity,
        ],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
