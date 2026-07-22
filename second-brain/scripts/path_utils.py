"""Path helpers shared by second-brain scripts."""

import os


def resolve_path(value: str) -> str:
    """Expand environment variables and a leading user-home marker."""
    return os.path.expanduser(os.path.expandvars(value))
