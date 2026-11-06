"""The HTTP core: auth, retries with backoff, job polling, envelope parsing.

Sync and async clients share every decision (`_Core`), and differ only in how
they send a request and sleep.
"""

from __future__ import annotations

import asyncio
import email.utils
import json
import os
import random
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Protocol
from urllib.parse import quote

import httpx

from ._errors_base import (
    APIError,
    JobTimeoutError,
    MissingApiKeyError,
    SocialScrapeConnectionError,
    SocialScrapeError,
    SocialScrapeTimeoutError,
    UnexpectedResponseError,
)
from ._generated.errors import ERROR_CLASSES, ERROR_INFO
from ._response import HttpInfo, RequestOptions, Response
from ._version import __version__

DEFAULT_BASE_URL = "https://api.socialscrape.dev"
ENV_API_KEY = "SOCIALSCRAPE_API_KEY"
ENV_BASE_URL = "SOCIALSCRAPE_BASE_URL"

# Used when a gateway answers an error without our envelope (a 502 from nginx).
_STATUS_CODES = {
    400: "invalid_params", 401: "unauthorized", 402: "insufficient_credits", 403: "forbidden", 404: "not_found",
    409: "conflict", 429: "rate_limited", 500: "internal", 501: "not_implemented", 502: "upstream_error",
    503: "overloaded", 504: "upstream_timeout",
}


class RequestSender(Protocol):
    """What a generated resource needs from its client."""

    def _request(self, method: str, path: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class Config:
    api_key: str
    base_url: str
    timeout: float
    max_retries: int
    retry_initial_delay: float
    retry_max_delay: float
    max_retry_after: float
    headers: Mapping[str, str]
    wait_for_jobs: bool
    job_timeout: float
    job_poll_interval: float
    job_poll_max_interval: float


@dataclass
class Prepared:
    method: str
    url: str
    params: list[tuple[str, str]]
    content: bytes | None
    headers: dict[str, str]
    timeout: float
    max_retries: int


def resolve_config(
    *,
    api_key: str | None,
    base_url: str | None,
    timeout: float,
    max_retries: int,
    retry_initial_delay: float,
    retry_max_delay: float,
    max_retry_after: float,
    default_headers: Mapping[str, str] | None,
    wait_for_jobs: bool,
    job_timeout: float,
    job_poll_interval: float,
) -> Config:
    key = api_key or os.environ.get(ENV_API_KEY)
    if not key:
        raise MissingApiKeyError(f"no API key: pass api_key=... or set {ENV_API_KEY}")
    url = (base_url or os.environ.get(ENV_BASE_URL) or DEFAULT_BASE_URL).rstrip("/")
    return Config(
        api_key=key, base_url=url, timeout=timeout, max_retries=max_retries, retry_initial_delay=retry_initial_delay,
        retry_max_delay=retry_max_delay, max_retry_after=max_retry_after, headers=dict(default_headers or {}),
        wait_for_jobs=wait_for_jobs, job_timeout=job_timeout, job_poll_interval=job_poll_interval,
        job_poll_max_interval=max(job_poll_interval, 5.0),
    )


def _wire_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple, dict)):
        return json.dumps(v, separators=(",", ":"))
    return str(v)


def prepare(
    cfg: Config,
    method: str,
    path: str,
    *,
    path_params: Mapping[str, Any] | None,
    query: Mapping[str, Any] | None,
    body: Mapping[str, Any] | None,
    options: RequestOptions | None,
) -> Prepared:
    options = options or {}
    if path_params:
        path = path.format(**{k: quote(str(v), safe="") for k, v in path_params.items()})
    params = [(k, _wire_value(v)) for k, v in (query or {}).items() if v is not None]
    headers = {
        "x-api-key": cfg.api_key,
        "accept": "application/json",
        "user-agent": f"socialscrape-python/{__version__}",
    }
    # Header names are case-insensitive on the wire: merge in lower case so an
    # override such as "Idempotency-Key" replaces ours instead of sitting beside it.
    for source in (cfg.headers, options.get("headers") or {}):
        headers.update({str(k).lower(): v for k, v in source.items()})
    content: bytes | None = None
    if body is not None:
        content = json.dumps({k: v for k, v in body.items() if v is not None}, separators=(",", ":")).encode()
        headers["content-type"] = "application/json"
    if method in ("POST", "DELETE"):
        # One key for every attempt: a retry returns the first answer instead of charging twice.
        headers.setdefault("idempotency-key", options.get("idempotency_key") or str(uuid.uuid4()))
    if options.get("idempotency_key"):
        headers["idempotency-key"] = options["idempotency_key"]
    return Prepared(
        method=method, url=cfg.base_url + path, params=params, content=content, headers=headers,
        timeout=options.get("timeout", cfg.timeout), max_retries=options.get("max_retries", cfg.max_retries),
    )


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - time.time())


def _int_or_none(v: str | None) -> int | None:
    try:
        return int(v) if v is not None else None
    except ValueError:
        return None


def interpret(status: int, headers: Mapping[str, str], content: bytes, attempts: int) -> Response[Any] | SocialScrapeError:
    """An answer -> a Response, or the exception to raise (returned, not raised)."""
    lowered = {k.lower(): v for k, v in headers.items()}
    try:
        body = json.loads(content) if content else None
    except ValueError:
        body = None
    retry_after = _parse_retry_after(lowered.get("retry-after"))
    if isinstance(body, dict) and body.get("ok") is True and status < 400:
        info = HttpInfo(
            status_code=status, headers=lowered, request_id=body.get("request_id") or lowered.get("x-request-id"),
            rate_limit_limit=_int_or_none(lowered.get("x-ratelimit-limit")),
            rate_limit_remaining=_int_or_none(lowered.get("x-ratelimit-remaining")),
            ignored_params=tuple(p for p in lowered.get("x-ignored-params", "").split(",") if p),
            idempotent_replay=lowered.get("x-idempotent-replay") == "true", attempts=attempts,
        )
        return Response(
            data=body.get("data"), credits_charged=int(body.get("credits_charged") or 0),
            credits_remaining=body.get("credits_remaining"), cached=bool(body.get("cached")), cached_at=body.get("cached_at"),
            request_id=info.request_id or "", cursor=body.get("cursor"), has_more=body.get("has_more"), http=info,
            raw=body.get("raw"),
        )
    if isinstance(body, dict) and body.get("ok") is False and isinstance(body.get("error"), dict):
        err = body["error"]
        code = str(err.get("code") or "internal")
        cls = ERROR_CLASSES.get(code, APIError)
        retryable = err.get("retryable")
        return cls(
            str(err.get("message") or code), retryable=bool(retryable) if retryable is not None else ERROR_INFO.get(code, (0, False))[1],
            http_status=status, request_id=body.get("request_id") or lowered.get("x-request-id"), retry_after=retry_after,
            headers=lowered, body=body, **({} if cls is not APIError else {"code": code}),
        )
    code = _STATUS_CODES.get(status)
    if status >= 400 and code is not None:
        return ERROR_CLASSES[code](
            f"HTTP {status} without a SocialScrape error body", retryable=ERROR_INFO[code][1], http_status=status,
            request_id=lowered.get("x-request-id"), retry_after=retry_after, headers=lowered, body=content[:500].decode("utf-8", "replace"),
        )
    return UnexpectedResponseError(f"unexpected HTTP {status} response", http_status=status,
                                   body=content[:500].decode("utf-8", "replace"))


def retry_delay(cfg: Config, attempt: int, err: SocialScrapeError, max_retries: int) -> float | None:
    """Seconds to wait before retry number `attempt`, or None to give up."""
    if attempt > max_retries or not getattr(err, "retryable", False):
        return None
    after = getattr(err, "retry_after", None)
    if after is not None:
        return after if after <= cfg.max_retry_after else None
    base = min(cfg.retry_max_delay, cfg.retry_initial_delay * (2 ** (attempt - 1)))
    return base * (0.5 + random.random() / 2)


def is_job(resp: Response[Any]) -> bool:
    return resp.http.status_code == 202 and isinstance(resp.data, dict) and resp.data.get("object") == "job"


def job_options(options: RequestOptions | None) -> RequestOptions:
    out: RequestOptions = {}
    for k in ("timeout", "max_retries", "headers"):
        if options and k in options:
            out[k] = options[k]  # type: ignore[literal-required]
    return out


class _Stats:
    """Last-seen balance and a running total, updated after every answer."""

    credits_remaining: int | None = None
    credits_charged_total: int = 0

    def _record(self, resp: Response[Any]) -> None:
        if resp.credits_remaining is not None:
            self.credits_remaining = resp.credits_remaining
        self.credits_charged_total += resp.credits_charged


class SyncAPIClient(_Stats):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 2,
        retry_initial_delay: float = 0.5,
        retry_max_delay: float = 8.0,
        max_retry_after: float = 60.0,
        default_headers: Mapping[str, str] | None = None,
        wait_for_jobs: bool = True,
        job_timeout: float = 600.0,
        job_poll_interval: float = 1.0,
        http_client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._cfg = resolve_config(
            api_key=api_key, base_url=base_url, timeout=timeout, max_retries=max_retries,
            retry_initial_delay=retry_initial_delay, retry_max_delay=retry_max_delay, max_retry_after=max_retry_after,
            default_headers=default_headers, wait_for_jobs=wait_for_jobs, job_timeout=job_timeout,
            job_poll_interval=job_poll_interval,
        )
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client()
        self._sleep = sleep

    # ---- lifecycle
    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ---- requests
    def _send(self, prep: Prepared, attempt: int) -> Response[Any]:
        try:
            r = self._http.request(prep.method, prep.url, params=prep.params or None, content=prep.content,
                                   headers=prep.headers, timeout=prep.timeout)
        except httpx.TimeoutException as e:
            raise SocialScrapeTimeoutError(f"{prep.method} {prep.url} timed out after {prep.timeout}s") from e
        except httpx.TransportError as e:
            raise SocialScrapeConnectionError(f"{prep.method} {prep.url} failed: {e}") from e
        result = interpret(r.status_code, r.headers, r.content, attempt)
        if isinstance(result, SocialScrapeError):
            raise result
        return result

    def _request(
        self,
        method: str,
        path: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        options: RequestOptions | None = None,
        wait_for_job: bool = True,
    ) -> Response[Any]:
        resp = self._execute(method, path, path_params, query, body, options)
        want = (options or {}).get("wait_for_job", self._cfg.wait_for_jobs)
        if wait_for_job and want and is_job(resp):
            resp = self._poll_job(resp.data["job_id"], options)
        self._record(resp)
        return resp

    def _execute(self, method: str, path: str, path_params: Mapping[str, Any] | None, query: Mapping[str, Any] | None,
                 body: Mapping[str, Any] | None, options: RequestOptions | None) -> Response[Any]:
        """One call with retries; no job following, no stats."""
        cfg = self._cfg
        prep = prepare(cfg, method, path, path_params=path_params, query=query, body=body, options=options)
        attempt = 0
        while True:
            attempt += 1
            try:
                return self._send(prep, attempt)
            except (APIError, SocialScrapeConnectionError, SocialScrapeTimeoutError) as e:
                delay = retry_delay(cfg, attempt, e, prep.max_retries)
                if delay is None:
                    raise
                self._sleep(delay)

    def _poll_job(self, job_id: str, options: RequestOptions | None) -> Response[Any]:
        cfg = self._cfg
        limit = (options or {}).get("job_timeout", cfg.job_timeout)
        deadline = time.monotonic() + limit
        interval = cfg.job_poll_interval
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise JobTimeoutError(f"job {job_id} did not finish within {limit}s; it keeps running", job_id=job_id)
            self._sleep(min(interval, remaining))
            interval = min(interval * 1.5, cfg.job_poll_max_interval)
            resp = self._execute("GET", "/v1/jobs/{job_id}", {"job_id": job_id}, None, None, job_options(options))
            if not is_job(resp):
                return resp

    def wait_for_job(self, job_id: str, *, request_options: RequestOptions | None = None) -> Response[Any]:
        """Poll a job (free) until it finishes and return its final answer."""
        resp = self._poll_job(job_id, request_options)
        self._record(resp)
        return resp

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        request_options: RequestOptions | None = None,
    ) -> Response[Any]:
        """Call any path directly (a newer endpoint than this client knows)."""
        return self._request(method.upper(), path, query=query, body=body, options=request_options)


class AsyncAPIClient(_Stats):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 2,
        retry_initial_delay: float = 0.5,
        retry_max_delay: float = 8.0,
        max_retry_after: float = 60.0,
        default_headers: Mapping[str, str] | None = None,
        wait_for_jobs: bool = True,
        job_timeout: float = 600.0,
        job_poll_interval: float = 1.0,
        http_client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._cfg = resolve_config(
            api_key=api_key, base_url=base_url, timeout=timeout, max_retries=max_retries,
            retry_initial_delay=retry_initial_delay, retry_max_delay=retry_max_delay, max_retry_after=max_retry_after,
            default_headers=default_headers, wait_for_jobs=wait_for_jobs, job_timeout=job_timeout,
            job_poll_interval=job_poll_interval,
        )
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient()
        self._sleep = sleep

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self):  # noqa: ANN204
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def _send(self, prep: Prepared, attempt: int) -> Response[Any]:
        try:
            r = await self._http.request(prep.method, prep.url, params=prep.params or None, content=prep.content,
                                         headers=prep.headers, timeout=prep.timeout)
        except httpx.TimeoutException as e:
            raise SocialScrapeTimeoutError(f"{prep.method} {prep.url} timed out after {prep.timeout}s") from e
        except httpx.TransportError as e:
            raise SocialScrapeConnectionError(f"{prep.method} {prep.url} failed: {e}") from e
        result = interpret(r.status_code, r.headers, r.content, attempt)
        if isinstance(result, SocialScrapeError):
            raise result
        return result

    async def _request(
        self,
        method: str,
        path: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        options: RequestOptions | None = None,
        wait_for_job: bool = True,
    ) -> Response[Any]:
        resp = await self._execute(method, path, path_params, query, body, options)
        want = (options or {}).get("wait_for_job", self._cfg.wait_for_jobs)
        if wait_for_job and want and is_job(resp):
            resp = await self._poll_job(resp.data["job_id"], options)
        self._record(resp)
        return resp

    async def _execute(self, method: str, path: str, path_params: Mapping[str, Any] | None,
                       query: Mapping[str, Any] | None, body: Mapping[str, Any] | None,
                       options: RequestOptions | None) -> Response[Any]:
        """One call with retries; no job following, no stats."""
        cfg = self._cfg
        prep = prepare(cfg, method, path, path_params=path_params, query=query, body=body, options=options)
        attempt = 0
        while True:
            attempt += 1
            try:
                return await self._send(prep, attempt)
            except (APIError, SocialScrapeConnectionError, SocialScrapeTimeoutError) as e:
                delay = retry_delay(cfg, attempt, e, prep.max_retries)
                if delay is None:
                    raise
                await self._sleep(delay)

    async def _poll_job(self, job_id: str, options: RequestOptions | None) -> Response[Any]:
        cfg = self._cfg
        limit = (options or {}).get("job_timeout", cfg.job_timeout)
        deadline = time.monotonic() + limit
        interval = cfg.job_poll_interval
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise JobTimeoutError(f"job {job_id} did not finish within {limit}s; it keeps running", job_id=job_id)
            await self._sleep(min(interval, remaining))
            interval = min(interval * 1.5, cfg.job_poll_max_interval)
            resp = await self._execute("GET", "/v1/jobs/{job_id}", {"job_id": job_id}, None, None, job_options(options))
            if not is_job(resp):
                return resp

    async def wait_for_job(self, job_id: str, *, request_options: RequestOptions | None = None) -> Response[Any]:
        """Poll a job (free) until it finishes and return its final answer."""
        resp = await self._poll_job(job_id, request_options)
        self._record(resp)
        return resp

    async def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        request_options: RequestOptions | None = None,
    ) -> Response[Any]:
        """Call any path directly (a newer endpoint than this client knows)."""
        return await self._request(method.upper(), path, query=query, body=body, options=request_options)
