"""Drop a Gunicorn worker's metrics file when that worker exits."""

import os


def child_exit(server: object, worker: object) -> None:
    if not os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        return
    pid = getattr(worker, "pid", None)
    if not isinstance(pid, int):
        return
    from prometheus_client import multiprocess

    multiprocess.mark_process_dead(pid)
