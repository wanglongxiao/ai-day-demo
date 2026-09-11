"""Private Virtual Portrait Library client.

Uses Byteplus signed (AK/SK) universal OpenAPI calls to the `ark` service:
  - CreateAssetGroup  (project <-> asset-group one-to-one)
  - CreateAsset       (register a portrait image, returns asset-id)
  - GetAsset          (poll until Status == Active)

Reference: docs/PrivateVirtualPortraitLibrary.txt
"""
from __future__ import annotations

import time
from typing import Optional

from byteplussdkcore import ApiClient, Configuration, UniversalApi, UniversalInfo

from .config import settings

_API_VERSION = "2024-01-01"
_SERVICE = "ark"


class AssetLibraryError(RuntimeError):
    pass


class AssetLibraryClient:
    def __init__(self) -> None:
        conf = Configuration()
        conf.ak = settings.BYTEPLUS_AK
        conf.sk = settings.BYTEPLUS_SK
        conf.region = settings.ARK_OPENAPI_REGION
        conf.host = settings.ARK_OPENAPI_HOST
        # A single ApiClient is thread-safe enough for our signed POSTs.
        self._api = UniversalApi(ApiClient(conf))
        self._project = settings.ARK_ASSET_PROJECT

    def _call(self, action: str, body: dict) -> dict:
        info = UniversalInfo(
            method="POST",
            service=_SERVICE,
            version=_API_VERSION,
            action=action,
            content_type="application/json",
        )
        resp = self._api.do_call(info, body)
        if not isinstance(resp, dict):
            raise AssetLibraryError(f"{action}: unexpected response {resp!r}")
        return resp

    def create_asset_group(self, name: str, description: str = "") -> str:
        """Create an asset group; returns its group-id."""
        resp = self._call(
            "CreateAssetGroup",
            {
                "Name": name,
                "Description": description or f"Portrait group for {name}",
                "GroupType": "AIGC",
                "ProjectName": self._project,
            },
        )
        gid = resp.get("Id")
        if not gid:
            raise AssetLibraryError(f"CreateAssetGroup: no Id in {resp}")
        return gid

    def create_asset(self, group_id: str, image_url: str, name: str = "") -> str:
        """Register a portrait image into the group; returns its asset-id."""
        resp = self._call(
            "CreateAsset",
            {
                "GroupId": group_id,
                "URL": image_url,
                "AssetType": "Image",
                "Name": name,
                "ProjectName": self._project,
            },
        )
        aid = resp.get("Id")
        if not aid:
            raise AssetLibraryError(f"CreateAsset: no Id in {resp}")
        return aid

    def get_asset(self, asset_id: str) -> dict:
        return self._call(
            "GetAsset",
            {"Id": asset_id, "ProjectName": self._project},
        )

    def wait_for_active(
        self,
        asset_id: str,
        timeout: float = 300.0,
        interval: float = 5.0,
    ) -> str:
        """Poll GetAsset until Active. Returns the status; raises on Failed/timeout."""
        deadline = time.time() + timeout
        last = "Unknown"
        while time.time() < deadline:
            info = self.get_asset(asset_id)
            last = info.get("Status", "Unknown")
            if last == "Active":
                return last
            if last == "Failed":
                raise AssetLibraryError(f"Asset {asset_id} preprocessing Failed")
            time.sleep(interval)
        raise AssetLibraryError(f"Asset {asset_id} not Active within {timeout}s (last={last})")


asset_library = AssetLibraryClient()
