from __future__ import annotations

from types import SimpleNamespace

try:
    from celery import Celery
    from celery.signals import worker_process_init, worker_process_shutdown
except ModuleNotFoundError:  # pragma: no cover - exercised only when Celery is not installed locally.
    class _DummySignal:
        def connect(self, func):
            return func

    class Celery:  # type: ignore[no-redef]
        def __init__(self, *_args, **_kwargs) -> None:
            self.conf = {}
            self.control = SimpleNamespace(revoke=lambda *_args, **_kwargs: None)

        def task(self, *dargs, **dkwargs):
            def _decorate(func):
                func.app = self
                func.apply_async = lambda *args, **kwargs: None
                func.delay = lambda *args, **kwargs: None
                func.name = dkwargs.get("name", func.__name__)
                return func

            if dargs and callable(dargs[0]) and len(dargs) == 1 and not dkwargs:
                return _decorate(dargs[0])
            return _decorate

    worker_process_init = _DummySignal()
    worker_process_shutdown = _DummySignal()

from app.core.config import settings

celery_app = Celery(
    "crawlerai",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks"],
)

celery_app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    enable_utc=True,
    timezone="UTC",
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)
