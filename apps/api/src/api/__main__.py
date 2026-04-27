"""Entry point: `python -m api` or `integration-agent-api`."""

from __future__ import annotations


def main() -> None:
    import uvicorn

    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
