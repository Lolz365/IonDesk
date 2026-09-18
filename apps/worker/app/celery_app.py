from celery import Celery
from kombu import Exchange, Queue

from app.settings import WorkerSettings

EXPECTED_QUEUES = {
    "critical",
    "default",
    "media",
    "analysis",
    "exports",
    "webhooks",
}


def create_celery_app(settings: WorkerSettings | None = None) -> Celery:
    resolved_settings = settings or WorkerSettings()
    exchange = Exchange("visualops", type="direct", durable=True)
    app = Celery(
        "visualops",
        broker=resolved_settings.broker_url,
        backend=resolved_settings.result_backend,
    )
    app.conf.update(
        task_queues=tuple(
            Queue(name, exchange=exchange, routing_key=name, durable=True)
            for name in sorted(EXPECTED_QUEUES)
        ),
        task_default_queue="default",
        task_default_exchange="visualops",
        task_default_exchange_type="direct",
        task_default_routing_key="default",
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        enable_utc=True,
        timezone="UTC",
        task_always_eager=False,
        task_annotations={"*": {"max_retries": 5}},
        broker_connection_retry_on_startup=True,
    )
    return app
