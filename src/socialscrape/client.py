"""`SocialScrape` (sync) and `AsyncSocialScrape`."""

from __future__ import annotations

from typing import Any, AsyncIterator, Awaitable, Callable, Iterator, TypeVar

from ._base_client import AsyncAPIClient, SyncAPIClient
from ._generated.models import ListPage
from ._generated.resources import AsyncResources, Resources
from ._pagination import apaginate_items, apaginate_pages, paginate_items, paginate_pages
from ._response import Response

T = TypeVar("T")


class SocialScrape(SyncAPIClient, Resources):
    """Blocking client.

        client = SocialScrape()                      # key from SOCIALSCRAPE_API_KEY
        res = client.tiktok.profile(handle="khaby.lame")
        print(res.data["followers"], res.credits_charged, res.credits_remaining)

    Options: api_key, base_url, timeout (s, per attempt), max_retries,
    retry_initial_delay, retry_max_delay, max_retry_after, default_headers,
    wait_for_jobs, job_timeout, job_poll_interval, http_client (an
    httpx.Client you own), sleep (test hook).
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._mount_resources()

    def paginate(
        self, fn: Callable[..., Response[ListPage[T]]], *, max_items: int | None = None, max_pages: int | None = None, **params: Any
    ) -> Iterator[T]:
        """Iterate the items of a list method across pages, following `cursor`."""
        return paginate_items(fn, max_items=max_items, max_pages=max_pages, **params)

    def paginate_pages(
        self, fn: Callable[..., Response[ListPage[T]]], *, max_pages: int | None = None, **params: Any
    ) -> Iterator[Response[ListPage[T]]]:
        """Iterate whole pages (each a Response with its own credits and cursor)."""
        return paginate_pages(fn, max_pages=max_pages, **params)


class AsyncSocialScrape(AsyncAPIClient, AsyncResources):
    """asyncio client; the same methods, awaited.

        async with AsyncSocialScrape() as client:
            res = await client.tiktok.profile(handle="khaby.lame")
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._mount_resources()

    def paginate(
        self, fn: Callable[..., Awaitable[Response[ListPage[T]]]], *, max_items: int | None = None,
        max_pages: int | None = None, **params: Any,
    ) -> AsyncIterator[T]:
        """`async for item in client.paginate(client.tiktok.profile_videos, handle=...)`."""
        return apaginate_items(fn, max_items=max_items, max_pages=max_pages, **params)

    def paginate_pages(
        self, fn: Callable[..., Awaitable[Response[ListPage[T]]]], *, max_pages: int | None = None, **params: Any
    ) -> AsyncIterator[Response[ListPage[T]]]:
        return apaginate_pages(fn, max_pages=max_pages, **params)
