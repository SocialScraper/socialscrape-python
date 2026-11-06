"""Every exception this package raises.

    SocialScrapeError                    base of all of them
      MissingApiKeyError                 no key given and SOCIALSCRAPE_API_KEY unset
      APIError                           the API answered with an error (code, retryable, request_id, ...)
        InvalidParamsError, NotFoundError, RateLimitedError, ...   one class per error code
      UnexpectedResponseError            not a SocialScrape answer at all
      SocialScrapeConnectionError        no answer (retryable)
      SocialScrapeTimeoutError           client-side timeout (retryable)
        JobTimeoutError                  a long job outlived job_timeout (it keeps running)
"""

from ._errors_base import (  # noqa: F401
    APIError,
    JobTimeoutError,
    MissingApiKeyError,
    SocialScrapeConnectionError,
    SocialScrapeError,
    SocialScrapeTimeoutError,
    UnexpectedResponseError,
)
from ._generated.errors import *  # noqa: F401,F403
from ._generated.errors import ERROR_CLASSES, ERROR_INFO  # noqa: F401
