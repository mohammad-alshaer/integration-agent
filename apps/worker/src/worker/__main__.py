"""Allow `python -m worker ...` to route to the typer CLI."""

from worker.cli import app

if __name__ == "__main__":
    app()
