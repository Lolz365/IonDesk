from kombu import Queue

from app.celery_app import EXPECTED_QUEUES, create_celery_app
from app.settings import WorkerSettings


def settings() -> WorkerSettings:
    return WorkerSettings(
        broker_url="redis://:secret@redis:6379/0",
        result_backend="redis://:secret@redis:6379/1",
    )


def test_worker_declares_all_operational_queues() -> None:
    celery_app = create_celery_app(settings())

    queues = {
        queue.name for queue in celery_app.conf.task_queues if isinstance(queue, Queue)
    }

    assert (
        queues
        == EXPECTED_QUEUES
        == {
            "critical",
            "default",
            "media",
            "analysis",
            "exports",
            "webhooks",
        }
    )


def test_worker_uses_durable_safe_execution_defaults() -> None:
    celery_app = create_celery_app(settings())

    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.result_serializer == "json"
    assert celery_app.conf.enable_utc is True
    assert celery_app.conf.timezone == "UTC"
    assert celery_app.conf.task_always_eager is False
    assert celery_app.conf.task_annotations["*"]["max_retries"] == 5
