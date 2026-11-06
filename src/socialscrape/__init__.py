"""SocialScrape: public social media data as an API.

    from socialscrape import SocialScrape

    client = SocialScrape()  # reads SOCIALSCRAPE_API_KEY
    profile = client.tiktok.profile(handle="khaby.lame")
    print(profile.data["followers"], profile.credits_charged, profile.credits_remaining)

See https://socialscrape.dev/docs.
"""

from . import errors, models
from ._batch import BatchRequest
from ._generated.endpoints import ENDPOINTS
from ._response import HttpInfo, RequestOptions, Response
from ._version import __version__
from .client import AsyncSocialScrape, SocialScrape
from .errors import (
    APIError,
    JobTimeoutError,
    MissingApiKeyError,
    SocialScrapeConnectionError,
    SocialScrapeError,
    SocialScrapeTimeoutError,
    UnexpectedResponseError,
)

__all__ = [
    "SocialScrape", "AsyncSocialScrape", "Response", "HttpInfo", "RequestOptions", "BatchRequest", "ENDPOINTS",
    "APIError", "SocialScrapeError", "MissingApiKeyError", "UnexpectedResponseError", "SocialScrapeConnectionError",
    "SocialScrapeTimeoutError", "JobTimeoutError", "errors", "models", "__version__",
]
