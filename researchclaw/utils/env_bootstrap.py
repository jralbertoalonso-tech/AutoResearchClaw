"""Central environment bootstrap for ResearchClaw.

Loads variables from the project's ``.env`` file into ``os.environ``
**before** any API client is instantiated.  All modules that need
environment variables (S2_API_KEY, SCITE_API_KEY, …) should call
``bootstrap_env()`` at import time or at the top of their entry-point.

Design decisions
----------------
* Uses ``override=True`` so ``.env`` values always win over stale
  empty-string shell exports (e.g. ``export SCITE_API_KEY=`` followed
  by sourcing a new ``.env``).
* Walks up the directory tree to find ``.env``, so it works from any
  working directory (tests, subprocess, installed package).
* Logs which keys are present/absent (without printing values).
* Safe to call multiple times — idempotent because dotenv skips
  already-set keys when ``override=False`` and re-sets them when
  ``override=True`` (no side-effect if value doesn't change).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Keys that the pipeline uses — logged for diagnostics (never their values).
_MONITORED_KEYS: tuple[str, ...] = (
    "S2_API_KEY",
    "SEMANTIC_SCHOLAR_API_KEY",
    "SCITE_API_KEY",
    "OPENAI_API_KEY",
    "EMAIL_USER",
)

_bootstrapped: bool = False  # guard against redundant INFO logs on re-import


def _find_dotenv(start: Path | None = None) -> Path | None:
    """Walk up from *start* (default: this file's grandparent = project root)
    until a ``.env`` file is found.  Returns ``None`` if not found.
    """
    if start is None:
        # researchclaw/utils/env_bootstrap.py  →  ../../  →  project root
        start = Path(__file__).resolve().parent.parent.parent
    for directory in [start, *start.parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


def bootstrap_env(*, override: bool = True, dotenv_path: Path | None = None) -> None:
    """Load ``.env`` into ``os.environ``.

    Parameters
    ----------
    override:
        If ``True`` (default), values in ``.env`` overwrite any existing
        entries in ``os.environ``.  Set to ``False`` to let shell
        environment take precedence.
    dotenv_path:
        Explicit path to a ``.env`` file.  Auto-detected if ``None``.
    """
    global _bootstrapped  # noqa: PLW0603

    try:
        from dotenv import load_dotenv  # type: ignore[import]
    except ImportError:
        logger.debug("env_bootstrap: python-dotenv not installed — skipping .env load")
        return

    path = dotenv_path or _find_dotenv()
    if path is None:
        logger.debug("env_bootstrap: no .env file found in directory tree")
        return

    loaded = load_dotenv(path, override=override)

    if not _bootstrapped:
        _bootstrapped = True
        present = [k for k in _MONITORED_KEYS if os.environ.get(k, "").strip()]
        absent  = [k for k in _MONITORED_KEYS if not os.environ.get(k, "").strip()]
        if loaded:
            logger.info(
                "env_bootstrap: loaded %s (override=%s) — present: [%s]  absent: [%s]",
                path,
                override,
                ", ".join(present) if present else "—",
                ", ".join(absent)  if absent  else "—",
            )
        else:
            logger.debug("env_bootstrap: %s already in sync with os.environ", path)
