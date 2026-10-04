"""Credential redaction and correlated, lossless agent event delivery."""

import json
import re
import uuid


def activity_log(event, **fields):
    allowed = {
        "run_id",
        "mode",
        "engine",
        "status",
        "elapsed_seconds",
        "error_type",
        "tool_count",
        "step",
        "checks_passed",
        "push_confirmed",
    }
    print(
        json.dumps(
            {
                "service": "coding-harness",
                "event": event,
                **{key: value for key, value in fields.items() if key in allowed},
            }
        ),
        flush=True,
    )


def redact(text, token=""):
    if token:
        text = text.replace(token, "[REDACTED]")
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[JWT]", text)
    text = re.sub(
        r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|(?:AKIA|ASIA)[A-Z0-9]{16})\b",
        "[CREDENTIAL]",
        text,
    )
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9_.+/=-]+", "Bearer [REDACTED]", text)
    text = re.sub(
        r'(https://[^\s"<>]+)[?][^\s"<>]*(?:request_uri|session_uri|code|state)=[^\s"<>]*',
        r"\1?[REDACTED]",
        text,
    )
    return text


def opencode_log(run_id, event, token=""):
    """Deliver every CLI event, preserving large outputs in numbered log chunks."""

    def scrub(value):
        if isinstance(value, dict):
            return {
                key: (
                    "[REDACTED]"
                    if key.lower()
                    in {
                        "authorization",
                        "access_token",
                        "refresh_token",
                        "client_secret",
                        "aws_secret_access_key",
                        "aws_session_token",
                        "password",
                        "api_key",
                    }
                    else scrub(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, str):
            return redact(value, token)
        return value

    clean = scrub(event)
    serialized = json.dumps(clean, ensure_ascii=True)
    base = {
        "service": "coding-harness",
        "event": "opencode_event",
        "run_id": run_id,
        "event_id": uuid.uuid4().hex,
        "opencode_type": clean.get("type", "unknown"),
    }
    # ASCII serialization makes each chunk bounded in bytes, even for Unicode
    # command output. Joining chunk_data in chunk_index order restores the JSON.
    chunk_size = 48_000
    if len(serialized) <= chunk_size:
        print(json.dumps({**base, "data": clean}), flush=True)
    else:
        count = (len(serialized) + chunk_size - 1) // chunk_size
        for index in range(count):
            print(
                json.dumps(
                    {
                        **base,
                        "chunk_index": index,
                        "chunk_count": count,
                        "chunk_data": serialized[
                            index * chunk_size : (index + 1) * chunk_size
                        ],
                    }
                ),
                flush=True,
            )
