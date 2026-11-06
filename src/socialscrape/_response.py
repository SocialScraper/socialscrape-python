"""What every method returns, and the per-call options."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, Mapping, TypedDict, TypeVar

T = TypeVar("T")


class RequestOptions(TypedDict, total=False):
    """Per-call overrides. Anything left out uses the client's setting."""

    timeout: float  # seconds, per attempt
    max_retries: int
    idempotency_key: str  # POST/DELETE get a random one automatically
    headers: Mapping[str, str]
    wait_for_job: bool  # follow a 202 job to its result (default True)
    job_timeout: float  # seconds to wait for a job


@dataclass(frozen=True)
class HttpInfo:
    """Transport facts about the answer; the envelope fields live on Response."""

    status_code: int
    headers: Mapping[str, str]  # lower-cased names
    request_id: str | None
    rate_limit_limit: int | None  # x-ratelimit-limit; the api no longer sends it, so None
    rate_limit_remaining: int | None  # x-ratelimit-remaining; None as well
    ignored_params: tuple[str, ...] = ()  # x-ignored-params: names the API did not recognise
    idempotent_replay: bool = False  # x-idempotent-replay: this is the first answer, replayed
    attempts: int = 1  # HTTP attempts made, retries included


@dataclass(frozen=True)
class Response(Generic[T]):
    """A successful answer: the envelope, typed.

    `data` is the endpoint's model (a dict, see `socialscrape.models`). For
    lists it is a ListPage, and `cursor` / `has_more` are copies of its
    fields. `credits_charged` is 0 on a cache hit.
    """

    data: T
    credits_charged: int
    credits_remaining: int | None
    cached: bool
    cached_at: str | None
    request_id: str
    cursor: str | None
    has_more: bool | None
    http: HttpInfo
    raw: Any = None  # the platform's original object; only with raw=True
    ok: bool = field(default=True)
