import threading

progress_state = {"percent": 0, "status": "idle", "done": True}
_progress_lock = threading.Lock()


def _set_progress(percent, status, done):
    with _progress_lock:
        progress_state["percent"] = percent
        progress_state["status"] = status
        progress_state["done"] = done


def _progress_callback(current, total):
    percent = int(current * 100 / total) if total else 0
    _set_progress(percent, f"rendered {current} of {total}", False)
