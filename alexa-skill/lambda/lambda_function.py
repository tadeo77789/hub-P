"""AWS Lambda behind a Function URL that turns hub alerts into Alexa notifications.

Environment variables:
  AGENT_SHARED_SECRET    same secret as the hub, to verify the request signature
  ALEXA_CLIENT_ID        skill's Login with Amazon client id (Alexa developer console > Permissions)
  ALEXA_CLIENT_SECRET    skill's client secret
  ALEXA_EVENTS_STAGE     "development" (default) or "live"
  ALEXA_API_ENDPOINT     defaults to https://api.amazonalexa.com (NA region)

Standard library only, so it deploys as a single file.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta

LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
MAX_AGE_SECONDS = 300


def _verify(headers: dict[str, str], body: bytes) -> bool:
    secret = os.environ["AGENT_SHARED_SECRET"].encode()
    signature = headers.get("x-paula-signature", "")
    sent_at = headers.get("x-paula-sent-at", "")
    expected = hmac.new(secret, sent_at.encode() + b"." + body, hashlib.sha256).hexdigest()
    try:
        fresh = abs(time.time() - int(sent_at)) <= MAX_AGE_SECONDS
    except ValueError:
        return False
    return fresh and hmac.compare_digest(signature, expected)


def _access_token() -> str:
    data = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": os.environ["ALEXA_CLIENT_ID"],
            "client_secret": os.environ["ALEXA_CLIENT_SECRET"],
            "scope": "alexa::proactive_events",
        }
    ).encode()
    with urllib.request.urlopen(urllib.request.Request(LWA_TOKEN_URL, data=data)) as response:
        return json.load(response)["access_token"]


def _proactive_event(alert: dict) -> dict:
    now = datetime.now(UTC)
    return {
        "timestamp": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "referenceId": str(uuid.uuid4()),
        "expiryTime": (now + timedelta(hours=1))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "event": {
            "name": "AMAZON.MessageAlert.Activated",
            "payload": {
                "state": {"status": "UNREAD", "freshness": "NEW"},
                "messageGroup": {
                    "creator": {"name": alert.get("title") or "Paula"},
                    "count": 1,
                    "urgency": "URGENT",
                },
            },
        },
        "audience": {"type": "Multicast", "payload": {}},
    }


def lambda_handler(event, context):
    body = event.get("body") or ""
    raw = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode()
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if not _verify(headers, raw):
        return {"statusCode": 401, "body": "invalid signature"}

    alert = json.loads(raw)
    endpoint = os.environ.get("ALEXA_API_ENDPOINT", "https://api.amazonalexa.com")
    stage = os.environ.get("ALEXA_EVENTS_STAGE", "development")
    path = "/v1/proactiveEvents" if stage == "live" else "/v1/proactiveEvents/stages/development"
    request = urllib.request.Request(
        endpoint + path,
        data=json.dumps(_proactive_event(alert)).encode(),
        headers={
            "Authorization": f"Bearer {_access_token()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return {"statusCode": 202, "body": json.dumps({"alexa_status": response.status})}
