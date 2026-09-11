"""aiday-demo entrypoint."""
from __future__ import annotations


def main() -> None:
    import uvicorn

    from .config import settings

    uvicorn.run(
        "aiday_demo.server:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
