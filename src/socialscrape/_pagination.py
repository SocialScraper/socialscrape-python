"""Cursor auto-pagination over any list method.

    for post in client.paginate(client.tiktok.profile_videos, handle="khaby.lame", max_items=200):
        ...

Every page is a separate request and costs what a single call costs, so cap
the walk with `max_items` or `max_pages` unless you really want everything.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Awaitable, Callable, Iterator, TypeVar

from ._response import Response

T = TypeVar("T")


def _next_cursor(resp: Response[Any], current: str | None) -> str | None:
    data = resp.data if isinstance(resp.data, dict) else {}
    has_more = resp.has_more if resp.has_more is not None else data.get("has_more")
    nxt = resp.cursor if resp.cursor is not None else data.get("cursor")
    if not has_more or not nxt or nxt == current:
        return None
    return str(nxt)


def paginate_pages(
    fn: Callable[..., Response[Any]], *, max_pages: int | None = None, **params: Any
) -> Iterator[Response[Any]]:
    cursor = params.pop("cursor", None)
    seen: set[str] = set()
    pages = 0
    while True:
        resp = fn(**params, **({"cursor": cursor} if cursor else {}))
        pages += 1
        yield resp
        nxt = _next_cursor(resp, cursor)
        if nxt is None or nxt in seen or (max_pages is not None and pages >= max_pages):
            return
        seen.add(nxt)
        cursor = nxt


def paginate_items(
    fn: Callable[..., Response[Any]], *, max_items: int | None = None, max_pages: int | None = None, **params: Any
) -> Iterator[Any]:
    count = 0
    if max_items is not None and max_items <= 0:
        return
    for page in paginate_pages(fn, max_pages=max_pages, **params):
        for item in page.data["items"]:
            yield item
            count += 1
            if max_items is not None and count >= max_items:
                return


async def apaginate_pages(
    fn: Callable[..., Awaitable[Response[Any]]], *, max_pages: int | None = None, **params: Any
) -> AsyncIterator[Response[Any]]:
    cursor = params.pop("cursor", None)
    seen: set[str] = set()
    pages = 0
    while True:
        resp = await fn(**params, **({"cursor": cursor} if cursor else {}))
        pages += 1
        yield resp
        nxt = _next_cursor(resp, cursor)
        if nxt is None or nxt in seen or (max_pages is not None and pages >= max_pages):
            return
        seen.add(nxt)
        cursor = nxt


async def apaginate_items(
    fn: Callable[..., Awaitable[Response[Any]]], *, max_items: int | None = None, max_pages: int | None = None, **params: Any
) -> AsyncIterator[Any]:
    count = 0
    if max_items is not None and max_items <= 0:
        return
    async for page in apaginate_pages(fn, max_pages=max_pages, **params):
        for item in page.data["items"]:
            yield item
            count += 1
            if max_items is not None and count >= max_items:
                return
