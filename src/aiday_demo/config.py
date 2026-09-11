"""Configuration loading from environment / .env file."""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"


def _load_env_file(path: Path) -> None:
    """Minimal .env loader (no external dependency)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        # strip inline comments and surrounding quotes
        value = value.split("#", 1)[0].strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file(ENV_PATH)


def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


class Settings:
    # TOS
    BYTEPLUS_AK: str = _get("BYTEPLUS_AK")
    BYTEPLUS_SK: str = _get("BYTEPLUS_SK")
    TOS_REGION: str = _get("TOS_REGION", "cn-hongkong")
    TOS_BUCKET: str = _get("TOS_BUCKET")
    TOS_ENDPOINT: str = _get("TOS_ENDPOINT")

    # LLM / video
    LLM_BASE_URL: str = _get("LLM_BASE_URL", "https://ark.ap-southeast.bytepluses.com/api/v3")
    ARK_API_KEY: str = _get("ARK_API_KEY")
    CHAT_MODEL: str = _get("CHAT_MODEL")
    IMAGE_MODEL: str = _get("IMAGE_MODEL")
    VIDEO_MODEL: str = _get("VIDEO_MODEL")

    # Asset library OpenAPI
    ARK_OPENAPI_HOST: str = _get("ARK_OPENAPI_HOST", "https://open.byteplusapi.com")
    ARK_OPENAPI_REGION: str = _get("ARK_OPENAPI_REGION", "ap-southeast-1")
    ARK_ASSET_PROJECT: str = _get("ARK_ASSET_PROJECT", "default")

    # Server
    HOST: str = _get("HOST", "0.0.0.0")
    PORT: int = int(_get("PORT", "8000") or "8000")
    ACCESS_PASSWORD: str = _get("ACCESS_PASSWORD", "")

    # Fixed visual references used as Image 2 and Image 3. Image 1 is always
    # the portrait registered for the current task. Configured via .env.
    REFERENCE_IMAGE_ASSETS: tuple[str, str] = (
        _get("REFERENCE_IMAGE_ASSET_2"),
        _get("REFERENCE_IMAGE_ASSET_3"),
    )

    @property
    def reference_image_refs(self) -> tuple[str, str]:
        return tuple(f"asset://{asset_id}" for asset_id in self.REFERENCE_IMAGE_ASSETS)

    @property
    def tos_public_base(self) -> str:
        """Public read URL prefix for objects in the bucket."""
        return f"https://{self.TOS_BUCKET}.{self.TOS_ENDPOINT}"


settings = Settings()
