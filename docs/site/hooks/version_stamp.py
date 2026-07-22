"""Stamp the built site with the ProveKit version it was built from.

A docs site with no version on it is the failure mode #33 is about: a reader lands on a page,
follows it, and has no way to know whether it describes the release they installed. There is
only one place that number is authoritative — `backend/pyproject.toml` — so the site reads it
at build time rather than carrying a second copy that drifts.

This is the *stamp*, not multi-version publishing. Serving `/0.6/` alongside `/latest/` needs
`mike` and somewhere to publish to, and neither is set up (see docs/site/README.md).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger("mkdocs.hooks.version_stamp")

PYPROJECT = Path(__file__).resolve().parents[3] / "backend" / "pyproject.toml"
_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def _version() -> str | None:
    """The `version` from backend/pyproject.toml, or None if it has moved.

    Parsed by regex on purpose: `tomllib` is 3.11+, and requiring a TOML backend (or a Python
    floor higher than the SDK's own 3.11) to render documentation is a worse trade than reading
    one unambiguous line. The [project] table is the only one in that file with a `version` key.
    """
    try:
        m = _VERSION_RE.search(PYPROJECT.read_text())
    except OSError:
        return None
    return m.group(1) if m else None


def on_config(config):
    version = _version()
    if not version:
        # Under `--strict` (how CI builds) this fails the job, which is the intent: an
        # unlabelled build of a versioned docs site is the thing we are trying not to ship.
        log.warning("could not read version from %s — the site will not be version-stamped",
                    PYPROJECT)
        return config
    config.copyright = (f"ProveKit {version} — built from the repository working tree. "
                        "No hosted docs site is published; see docs/site/README.md.")
    return config
