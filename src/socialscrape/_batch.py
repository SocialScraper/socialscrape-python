"""`client.batch.run`: many GET calls in one request.

The registry's `requests` parameter is a bare array, so this resource is
written by hand to accept an endpoint id (`"tiktok.profile"`) as well as a
raw path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Sequence, TypedDict, Union

from ._generated.endpoints import ENDPOINTS
from ._generated.models import BatchResult
from ._response import RequestOptions, Response

if TYPE_CHECKING:
    from ._base_client import RequestSender


class BatchById(TypedDict, total=False):
    endpoint: str  # a registry id such as "tiktok.profile" (GET endpoints only)
    params: Mapping[str, Any]


class BatchByPath(TypedDict, total=False):
    path: str  # "/v1/tiktok/profile", optionally with a query string
    params: Mapping[str, Any]


BatchRequest = Union[BatchById, BatchByPath]


def to_wire(requests: Sequence[BatchRequest]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, item in enumerate(requests):
        if "endpoint" in item:
            info = ENDPOINTS.get(item["endpoint"])  # type: ignore[typeddict-item]
            if info is None:
                raise ValueError(f"requests[{i}]: unknown endpoint id {item['endpoint']!r}")  # type: ignore[typeddict-item]
            if info["method"] != "GET":
                raise ValueError(f"requests[{i}]: {item['endpoint']} is not a GET endpoint; batch runs GETs")  # type: ignore[typeddict-item]
            if "{" in info["path"]:
                raise ValueError(f"requests[{i}]: {item['endpoint']} has a path parameter ({info['path']}); batch cannot fill it, call it directly")  # type: ignore[typeddict-item]
            wire: dict[str, Any] = {"path": info["path"]}
        elif "path" in item:
            wire = {"path": item["path"]}  # type: ignore[typeddict-item]
        else:
            raise ValueError(f"requests[{i}] needs `endpoint` or `path`")
        if item.get("params"):
            wire["params"] = dict(item["params"])  # type: ignore[arg-type]
        out.append(wire)
    return out


class BatchResource:
    """`client.batch`"""

    def __init__(self, client: RequestSender) -> None:
        self._request = client._request

    def run(self, requests: Sequence[BatchRequest], *, request_options: RequestOptions | None = None) -> Response[BatchResult]:
        """Run up to the account's batch limit of GET requests in one call.

        Each item behaves exactly like the same call made alone (cache, charge,
        free failures). `credits_charged` is the sum; each result's `response`
        is a full envelope. Items are `{"endpoint": "tiktok.profile", "params": {...}}`
        or `{"path": "/v1/tiktok/profile", "params": {...}}`.
        """
        return self._request("POST", "/v1/batch", body={"requests": to_wire(requests)}, options=request_options)


class AsyncBatchResource:
    """`client.batch`"""

    def __init__(self, client: RequestSender) -> None:
        self._request = client._request

    async def run(self, requests: Sequence[BatchRequest], *, request_options: RequestOptions | None = None) -> Response[BatchResult]:
        """Same as the sync `batch.run`."""
        return await self._request("POST", "/v1/batch", body={"requests": to_wire(requests)}, options=request_options)
