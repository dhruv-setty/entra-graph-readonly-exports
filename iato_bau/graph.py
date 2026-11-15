"""Shared Microsoft Graph client: trusted-host checks, retries and paging.

Standard library only. The bearer token is only ever sent to
https://graph.microsoft.com/v1.0/, including on @odata.nextLink pages.
"""

import json
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
GRAPH_HOST = "graph.microsoft.com"
MAX_RETRIES = 5
MAX_RETRY_DELAY_SECONDS = 60


def validate_graph_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != GRAPH_HOST or not parsed.path.startswith("/v1.0/"):
        raise ValueError("Refusing to send the Graph bearer token to an untrusted URL")


def _retry_delay(attempt, retry_after=None):
    if retry_after:
        try:
            return min(MAX_RETRY_DELAY_SECONDS, max(0.0, float(retry_after)))
        except ValueError:
            try:
                seconds = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
                return min(MAX_RETRY_DELAY_SECONDS, max(0.0, seconds))
            except (TypeError, ValueError, OverflowError):
                pass
    return min(MAX_RETRY_DELAY_SECONDS, (2**attempt) + random.uniform(0, 1))


def request_json(url, token):
    validate_graph_url(url)
    request = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    for attempt in range(MAX_RETRIES + 1):
        try:
            with urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            retryable = error.code == 429 or 500 <= error.code < 600
            if not retryable or attempt == MAX_RETRIES:
                raise
            time.sleep(_retry_delay(attempt, error.headers.get("Retry-After")))
        except URLError:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(_retry_delay(attempt))
    raise RuntimeError("Graph request retry loop exited unexpectedly")


def paged(url, token):
    while url:
        validate_graph_url(url)
        data = request_json(url, token)
        yield from data.get("value", [])
        url = data.get("@odata.nextLink")
