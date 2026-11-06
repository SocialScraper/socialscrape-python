"""Error base classes. The per-code subclasses are generated (`_generated/errors.py`)."""

from __future__ import annotations

from typing import Any, Mapping


class SocialScrapeError(Exception):
    """Base class of everything this package raises."""


class MissingApiKeyError(SocialScrapeError):
    """No API key: pass `api_key=` or set SOCIALSCRAPE_API_KEY."""


class APIError(SocialScrapeError):
    """The API answered with an error envelope (or an HTTP error without one).

    Branch on `code`, never on `message`. Every failure is free:
    `credits_charged` is always 0. `retryable` says whether the same request
    may succeed later; the client already retried when it was set and the
    retry budget allowed.
    """

    code: str = "internal"

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        http_status: int | None = None,
        request_id: str | None = None,
        retry_after: float | None = None,
        headers: Mapping[str, str] | None = None,
        body: Any = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        self.message = message
        self.retryable = retryable
        self.http_status = http_status
        self.request_id = request_id
        self.retry_after = retry_after
        self.headers: Mapping[str, str] = dict(headers or {})
        self.body = body
        self.credits_charged = 0

    def __str__(self) -> str:
        bits = [f"{self.code}: {self.message}"]
        if self.http_status:
            bits.append(f"HTTP {self.http_status}")
        if self.request_id:
            bits.append(f"request {self.request_id}")
        return " | ".join(bits)


class UnexpectedResponseError(SocialScrapeError):
    """The server answered something that is not a SocialScrape envelope."""

    retryable = False

    def __init__(self, message: str, *, http_status: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.body = body


class SocialScrapeConnectionError(SocialScrapeError):
    """The request never got an answer (DNS, refused, reset). Retryable."""

    retryable = True


class SocialScrapeTimeoutError(SocialScrapeError):
    """The request timed out on the client side. Retryable."""

    retryable = True


class JobTimeoutError(SocialScrapeTimeoutError):
    """A long job did not finish inside `job_timeout`. It keeps running:
    fetch it later with `client.jobs.get(job_id=...)` (free to poll)."""

    def __init__(self, message: str, *, job_id: str) -> None:
        super().__init__(message)
        self.job_id = job_id
