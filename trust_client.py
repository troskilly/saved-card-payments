import json
import uuid
import urllib.request
import base64
import ssl

TRUST_URL = "https://webservices.securetrading.net/json/"

# Explicit TLS context: certificate verification + hostname check + TLS 1.2 minimum
# Trust Payments requires TLSv1.2 or higher per their API docs
_ssl_context = ssl.create_default_context()
_ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2


def call_trust_api(request_data: dict, username: str, password: str) -> dict:
    ref = "A" + uuid.uuid4().hex[:8]
    payload = json.dumps({
        "alias": username,
        "version": "1.00",
        "request": [{**request_data, "requestreference": ref}],
    }).encode("utf-8")

    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    req = urllib.request.Request(
        TRUST_URL,
        data=payload,
        headers={
            "Content-Type": "application/json;charset=utf-8",
            "Accept": "application/json",
            "Authorization": f"Basic {token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60, context=_ssl_context) as resp:
        result = json.loads(resp.read())

    return {
        "requestreference": result["requestreference"],
        "version": result["version"],
        "responses": result["response"],
    }
