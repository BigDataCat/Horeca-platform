"""Minimal in-process Prometheus metrics (per worker process)."""

from collections import defaultdict
from threading import Lock

_lock = Lock()
_requests: dict[tuple[str, str, str], int] = defaultdict(int)
_duration_sum: dict[tuple[str, str], float] = defaultdict(float)
_duration_count: dict[tuple[str, str], int] = defaultdict(int)


def route_label(request) -> str:
    """Request path with matched path parameters replaced by their names (bounded cardinality)."""
    if request.scope.get("route") is None:
        return "unmatched"
    path = request.url.path
    for name, value in request.scope.get("path_params", {}).items():
        path = path.replace(f"/{value}", f"/{{{name}}}", 1)
    return path


def observe(method: str, route: str, status: int, seconds: float) -> None:
    with _lock:
        _requests[(method, route, str(status))] += 1
        _duration_sum[(method, route)] += seconds
        _duration_count[(method, route)] += 1


def render() -> str:
    lines = [
        "# HELP horeca_up Whether the API process is running.",
        "# TYPE horeca_up gauge",
        "horeca_up 1",
        "# HELP horeca_http_requests_total HTTP requests by method, route and status.",
        "# TYPE horeca_http_requests_total counter",
    ]
    with _lock:
        for (method, route, status), count in sorted(_requests.items()):
            lines.append(f'horeca_http_requests_total{{method="{method}",route="{route}",status="{status}"}} {count}')
        lines += [
            "# HELP horeca_http_request_duration_seconds Request duration.",
            "# TYPE horeca_http_request_duration_seconds summary",
        ]
        for (method, route), total in sorted(_duration_sum.items()):
            lines.append(f'horeca_http_request_duration_seconds_sum{{method="{method}",route="{route}"}} {total:.6f}')
            lines.append(
                f'horeca_http_request_duration_seconds_count{{method="{method}",route="{route}"}} {_duration_count[(method, route)]}'
            )
    return "\n".join(lines) + "\n"


def reset() -> None:
    with _lock:
        _requests.clear()
        _duration_sum.clear()
        _duration_count.clear()
