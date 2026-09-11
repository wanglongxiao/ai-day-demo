"""TOS object storage helper.

- Uploads objects as public-read.
- Normalizes Content-Type (esp. video/mp4) for Web playback.
- Stores/reads per-task JSON state under tasks/<task_id>/.
"""
from __future__ import annotations

import io
import json
import mimetypes
from typing import Optional

import requests
import tos
from tos import ACLType

from .config import settings

# Content-Type mapping by extension for normalization.
_CT_MAP = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".json": "application/json; charset=utf-8",
}


def _guess_content_type(key: str, fallback: str = "application/octet-stream") -> str:
    lower = key.lower()
    for ext, ct in _CT_MAP.items():
        if lower.endswith(ext):
            return ct
    guessed, _ = mimetypes.guess_type(key)
    return guessed or fallback


class TOSStore:
    def __init__(self) -> None:
        self._client = tos.TosClientV2(
            settings.BYTEPLUS_AK,
            settings.BYTEPLUS_SK,
            settings.TOS_ENDPOINT,
            settings.TOS_REGION,
        )
        self._bucket = settings.TOS_BUCKET

    def public_url(self, key: str) -> str:
        return f"{settings.tos_public_base}/{key}"

    def put_bytes(
        self,
        key: str,
        data: bytes,
        content_type: Optional[str] = None,
        content_disposition: Optional[str] = None,
    ) -> str:
        ct = content_type or _guess_content_type(key)
        self._client.put_object(
            self._bucket,
            key,
            content=io.BytesIO(data),
            content_length=len(data),
            content_type=ct,
            content_disposition=content_disposition,
            acl=ACLType.ACL_Public_Read,
        )
        return self.public_url(key)

    def put_json(self, key: str, obj: dict, if_match: str | None = None) -> str:
        data = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self._client.put_object(
            self._bucket,
            key,
            content=io.BytesIO(data),
            content_length=len(data),
            content_type="application/json; charset=utf-8",
            acl=ACLType.ACL_Public_Read,
            if_match=if_match,
        )
        return self.public_url(key)

    def get_json(self, key: str) -> Optional[dict]:
        result = self.get_json_with_etag(key)
        return result[0] if result else None

    def get_json_with_etag(self, key: str) -> Optional[tuple[dict, str]]:
        try:
            resp = self._client.get_object(self._bucket, key)
            raw = resp.read()
            return json.loads(raw.decode("utf-8")), resp.etag
        except tos.exceptions.TosServerError as e:
            if e.status_code == 404:
                return None
            raise

    def delete_prefix(self, prefix: str, keep: set[str] | None = None) -> None:
        """Delete all objects under a prefix except explicitly retained keys."""
        retained = keep or set()
        marker = None
        while True:
            result = self._client.list_objects(
                self._bucket,
                prefix=prefix,
                marker=marker,
                max_keys=1000,
            )
            for item in result.contents:
                if item.key not in retained:
                    self._client.delete_object(self._bucket, item.key)
            if not result.is_truncated:
                return
            marker = result.next_marker

    def upload_from_url(
        self,
        key: str,
        url: str,
        content_type: Optional[str] = None,
        content_disposition: Optional[str] = None,
    ) -> str:
        """Download a (signed) remote URL and re-upload to our public bucket."""
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        ct = content_type or _guess_content_type(key, r.headers.get("Content-Type", "application/octet-stream"))
        return self.put_bytes(key, r.content, content_type=ct, content_disposition=content_disposition)

    def verify_readable(self, url: str) -> bool:
        """Confirm an uploaded object is publicly readable."""
        try:
            r = requests.head(url, timeout=30)
            if r.status_code == 200:
                return True
            # some endpoints reject HEAD; fall back to a ranged GET
            r = requests.get(url, headers={"Range": "bytes=0-0"}, timeout=30)
            return r.status_code in (200, 206)
        except requests.RequestException:
            return False


tos_store = TOSStore()
