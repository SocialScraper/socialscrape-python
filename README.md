# socialscrape (Python)

Social media data as an API: profiles, posts, comments, search, ads and
transcripts across platforms, in one response shape. This is the official Python
client for the [SocialScrape API](https://socialscrape.dev/docs?utm_source=github&utm_medium=repo&utm_campaign=socialscrape-sdk).

- Sync (`SocialScrape`) and asyncio (`AsyncSocialScrape`) clients on `httpx`.
- Typed methods per endpoint, grouped by platform; responses typed with `TypedDict`s.
- Typed exceptions per error code, retries with backoff and `Retry-After`, timeouts.
- `credits_charged` and `credits_remaining` on every response.
- Cursor auto-pagination, long-job polling, batch calls.

```sh
pip install socialscrape-sdk
```

Python 3.11 or newer.

Your API key is a secret: keep it on your server, in an environment variable or a secrets manager, and never in client-side code, a public repository or a log.

## Quickstart

```sh
export SOCIALSCRAPE_API_KEY=ss_live_...
```

```python
from socialscrape import SocialScrape

client = SocialScrape()  # reads SOCIALSCRAPE_API_KEY

res = client.tiktok.profile(handle="khaby.lame")

print(res.data["followers"])    # the normalised profile (a plain dict)
print(res.credits_charged)      # 1
print(res.credits_remaining)    # what is left
```

Methods are grouped by platform and named after the endpoint, with the API's own
parameter names as keyword arguments: `client.tiktok.profile_videos(handle=...)`,
`client.instagram.post_comments(url=...)`, `client.youtube.video_transcript(url=...)`,
`client.apple_music.artist(...)`. `client.transcript(url=...)` takes a link from
any supported platform.

Async is the same, awaited:

```python
import asyncio
from socialscrape import AsyncSocialScrape

async def main():
    async with AsyncSocialScrape() as client:
        res = await client.tiktok.profile(handle="khaby.lame")
        print(res.data["followers"])

asyncio.run(main())
```

## The response

Every method returns a `Response` with the envelope fields, typed:

```python
res.data                 # the endpoint's model (Profile, Post, ListPage[Post], ...)
res.credits_charged      # 0 on a cache hit
res.credits_remaining    # the team's balance after this call, or None
res.cached, res.cached_at
res.request_id           # quote it to support
res.cursor, res.has_more # lists: copies of data["cursor"] / data["has_more"]
res.raw                  # only with raw=True: the platform's original object
res.http.status_code, res.http.headers, res.http.attempts
res.http.rate_limit_limit, res.http.rate_limit_remaining  # both None: the api sends no x-ratelimit-* headers
res.http.ignored_params
```

The client keeps count too: `client.credits_remaining` (last balance seen) and
`client.credits_charged_total`.

Every endpoint also accepts `trim=True` (smaller response), `raw=True` (adds the
platform's original object) and `max_age_days=7` (accept a cached result up to 7
days old for 0 credits). Models live in `socialscrape.models`.

## Errors

Failures are free (`credits_charged` is 0) and raise a class per error code. Branch
on the class or `code`, never on the message.

```python
from socialscrape import errors

try:
    client.tiktok.profile(handle="no-such-account-123")
except errors.NotFoundError as e:
    print(e.code, e.http_status, e.request_id, e.retryable)   # not_found 404 req_... False
except errors.InsufficientCreditsError:
    ...  # top up
except errors.APIError as e:
    print(e.code, e.retryable)
```

| Class | `code` | HTTP | Retryable |
|---|---|---|---|
| `InvalidParamsError` | `invalid_params` | 400 | no |
| `UnsupportedUrlError` | `unsupported_url` | 400 | no |
| `UnauthorizedError` | `unauthorized` | 401 | no |
| `InsufficientCreditsError` | `insufficient_credits` | 402 | no |
| `ForbiddenError` | `forbidden` | 403 | no |
| `PrivateError` | `private` | 403 | no |
| `AgeRestrictedError` | `age_restricted` | 403 | no |
| `NotFoundError` | `not_found` | 404 | no |
| `TranscriptUnavailableError` | `transcript_unavailable` | 404 | no |
| `ConflictError` | `conflict` | 409 | no |
| `RemovedError` | `removed` | 410 | no |
| `UnavailableInRegionError` | `unavailable_in_region` | 451 | no |
| `RateLimitedError` | `rate_limited` | 429 | yes |
| `UpstreamRateLimitedError` | `upstream_rate_limited` | 503 | yes |
| `UpstreamBlockedError` | `upstream_blocked` | 503 | yes |
| `OverloadedError` | `overloaded` | 503 | yes |
| `UpstreamErrorError` | `upstream_error` | 502 | yes |
| `UpstreamChangedError` | `upstream_changed` | 502 | no |
| `UpstreamTimeoutError` | `upstream_timeout` | 504 | yes |
| `InternalError` | `internal` | 500 | yes |
| `NotImplementedYetError` | `not_implemented` | 501 | no |

All extend `errors.APIError` (attributes `code`, `message`, `retryable`,
`http_status`, `request_id`, `retry_after`, `headers`, `body`, `credits_charged`).
A code this version does not know yet still arrives as a plain `APIError`. Beyond
the API: `SocialScrapeConnectionError`, `SocialScrapeTimeoutError` (and its
subclass `JobTimeoutError`), `UnexpectedResponseError` and `MissingApiKeyError`,
all extending `SocialScrapeError`.

## Retries, timeouts, idempotency

Retryable errors (the table above, network failures and client timeouts) are
retried up to `max_retries` times (default 2) with exponential backoff and jitter.
`Retry-After` is honoured; one longer than `max_retry_after` (60 s) is not waited
for and the error is raised. POST and DELETE calls carry an `Idempotency-Key`
(generated, and reused across retries) so a retried write never charges twice.

```python
client = SocialScrape(
    api_key="ss_live_...",                  # default: SOCIALSCRAPE_API_KEY
    base_url="https://api.socialscrape.dev", # default: SOCIALSCRAPE_BASE_URL, else this
    timeout=60.0,                           # seconds, per attempt
    max_retries=2,
    retry_initial_delay=0.5,
    retry_max_delay=8.0,
    max_retry_after=60.0,
    wait_for_jobs=True,
    job_timeout=600.0,
    http_client=my_httpx_client,            # optional: an httpx.Client you own
)

# Per call:
client.tiktok.profile(handle="khaby.lame", request_options={"timeout": 10, "max_retries": 0})
```

`request_options` takes `timeout`, `max_retries`, `idempotency_key`, `headers`,
`wait_for_job` and `job_timeout`.

## Pagination

List endpoints return `cursor` and `has_more`. Pass the cursor back, or let the
client walk it. **Every page is a request and costs what one call costs**, so cap
the walk with `max_items` or `max_pages`.

```python
for video in client.paginate(client.tiktok.profile_videos, handle="khaby.lame", max_items=100):
    print(video["id"], video["stats"]["views"])

# whole pages, with each page's credits and cursor
for page in client.paginate_pages(client.tiktok.profile_videos, handle="khaby.lame", max_pages=3):
    print(len(page.data["items"]), page.credits_charged, page.cursor)
```

Async: `async for video in client.paginate(client.tiktok.profile_videos, handle=...)`.
Iteration stops at `has_more` false, at a repeated cursor and at your caps, and
never fetches a page it does not need to reach `max_items`.

## Long jobs (AI transcription, deep listings)

When an answer is not ready within a few seconds the API replies `202` with a job
id. The client follows it for you (polling is free; the finished job is charged
once) and returns the final response. Switch it off per call or globally:

```python
pending = client.youtube.video_transcript(url=url, request_options={"wait_for_job": False})
# pending.http.status_code == 202, pending.data["job_id"]
done = client.wait_for_job(pending.data["job_id"])
```

A job that outlives `job_timeout` raises `JobTimeoutError` with its `job_id`; it
keeps running and can be fetched later with `client.jobs.get(job_id=...)`.

## Batch and monitors

```python
res = client.batch.run([
    {"endpoint": "tiktok.profile", "params": {"handle": "khaby.lame"}},
    {"endpoint": "tiktok.profile", "params": {"handle": "charlidamelio"}},
])
res.credits_charged                       # the sum of the items
res.data["results"][0]["response"]        # each item is a full envelope

monitor = client.monitors.create(
    endpoint="/v1/tiktok/profile/videos",
    params={"handle": "khaby.lame"},
    webhook_url="https://example.com/hooks/socialscrape",
)
```

## Account

```python
client.account.credits().data["credits_remaining"]   # free
for row in client.paginate(client.account.usage):    # request history
    ...
```

## Newer endpoints

Methods are generated from the API's endpoint registry, and only endpoints that
are built appear (coming-soon ones are hidden). To call a path this client version
does not know yet:

```python
res = client.request("GET", "/v1/some/new/endpoint", query={"handle": "x"})
```

`socialscrape.ENDPOINTS` lists every endpoint the installed version knows.
