"""Uruchomienie serwera deweloperskiego: `uv run specflow` albo `python -m specflow`."""

import uvicorn


def main() -> None:
    uvicorn.run("specflow.web.app:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
