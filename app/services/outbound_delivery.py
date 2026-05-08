from __future__ import annotations

import atexit
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from threading import Lock
from time import monotonic
from weakref import WeakKeyDictionary
from typing import Any, Callable


class BackgroundDeliveryService:
    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max(1, int(max_workers)))
        self._lock = Lock()
        self._futures: set[Future[Any]] = set()

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future[Any]:
        future = self._executor.submit(fn, *args, **kwargs)
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._discard_future)
        return future

    def wait_for_idle(self, timeout: float = 5.0) -> bool:
        deadline = monotonic() + max(0.0, float(timeout))
        while True:
            with self._lock:
                futures = tuple(self._futures)
            if not futures:
                return True

            remaining = deadline - monotonic()
            if remaining <= 0:
                return False

            for future in futures:
                try:
                    future.result(timeout=min(0.05, remaining))
                except FutureTimeout:
                    continue
                except Exception:
                    continue

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)

    def _discard_future(self, future: Future[Any]) -> None:
        with self._lock:
            self._futures.discard(future)


_services: WeakKeyDictionary[object, BackgroundDeliveryService] = WeakKeyDictionary()
_services_lock = Lock()


def get_background_delivery_service(app) -> BackgroundDeliveryService:
    with _services_lock:
        service = _services.get(app)
        if service is None:
            workers = int(app.config.get("WHATSAPP_BACKGROUND_DELIVERY_WORKERS", 2))
            service = BackgroundDeliveryService(max_workers=workers)
            _services[app] = service
        return service


def _shutdown_services() -> None:
    with _services_lock:
        services = list(_services.values())
        _services.clear()

    for service in services:
        service.shutdown(wait=False)


atexit.register(_shutdown_services)
