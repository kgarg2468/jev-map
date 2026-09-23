"""Opt-in TypeSafe transport. Credentials never enter receipts or exception text."""

import json
import math
import os
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"
MAX_REQUEST_BYTES = 200_000
MAX_RESPONSE_BYTES = 1_000_000


class ProviderError(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_response(payload: dict, response: dict) -> dict[str, float]:
    try:
        values = {key: response["answers"][key]["noul"] for key in payload["questions"]}
    except (KeyError, TypeError) as exc:
        raise ProviderError("Invalid Jev answer schema") from exc
    if any(type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1
           for value in values.values()):
        raise ProviderError("Invalid Jev score; expected a finite number in [0, 1]")
    return values


class JevClient:
    def __init__(self, api_key: str | None = None, timeout: float = 30, env_file: Path | None = None):
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY")
        if not self.api_key and env_file is not None:
            for line in env_file.read_text().splitlines():
                name, separator, value = line.partition("=")
                if separator and name.strip() == "TYPESAFE_API_KEY":
                    value = value.strip()
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                        value = value[1:-1]
                    self.api_key = value
        self.timeout = timeout
        if not self.api_key:
            raise ProviderError("TYPESAFE_API_KEY is missing. Use tokenstash need TYPESAFE_API_KEY.")

    def __call__(self, payload: dict) -> dict:
        body = json.dumps(payload).encode()
        if len(body) > MAX_REQUEST_BYTES:
            raise ProviderError("Jev request exceeds the 200000-byte limit")
        request = urllib.request.Request(ENDPOINT, data=body, headers={
            "Authorization": "Bearer " + self.api_key, "Content-Type": "application/json",
        })
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ProviderError("Jev response exceeds the 1000000-byte limit")
            value = json.loads(raw)
            validate_response(payload, value)
            return value
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            raise ProviderError(f"Jev HTTP {code}; no automatic retry") from None
        except (OSError, ValueError) as exc:
            if isinstance(exc, ProviderError):
                raise
            raise ProviderError("Jev transport or JSON error; no automatic retry") from None
