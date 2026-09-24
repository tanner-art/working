"""Command-line entry point for the read-only live observation adapter."""

from .live_observation import main


if __name__ == "__main__":
    raise SystemExit(main())
