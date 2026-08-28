"""Versioned Clean Core rules configuration.

Loads the rule-set version and edition strictness from the classification skill's
companion reference (``app/skills/clean-core-classification/references/clean-core-rules.md``).
The rule *patterns* live in :mod:`classification.engine`; this module owns the
metadata that governs how those patterns map to levels per edition.
"""

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from scope_parser import Edition

logger = logging.getLogger(__name__)

_RULES_MD = (
    Path(__file__).resolve().parent.parent
    / "skills" / "clean-core-classification" / "references" / "clean-core-rules.md"
)

_DEFAULT_VERSION = "0.0.0-unknown"
_VERSION_RE = re.compile(r"\*\*Rule set version:\*\*\s*([0-9]+\.[0-9]+\.[0-9]+)")


@dataclass(frozen=True)
class EditionPolicy:
    """How an edition treats non-released (but non-forbidden) API usage."""

    edition: Edition
    # Level assigned to "non-released API" usage when no forbidden construct is present.
    non_released_level: str  # "C" or "D"
    released_only: bool      # True => any non-released usage escalates to D


# Public Cloud enforces Released-only; on-prem / private treat non-released as C.
_EDITION_POLICIES: dict[Edition, EditionPolicy] = {
    "on-premise": EditionPolicy("on-premise", non_released_level="C", released_only=False),
    "private-cloud": EditionPolicy("private-cloud", non_released_level="C", released_only=False),
    "public-cloud": EditionPolicy("public-cloud", non_released_level="D", released_only=True),
}

DEFAULT_EDITION: Edition = "on-premise"


@lru_cache(maxsize=1)
def get_rules_version() -> str:
    """Read the rule-set version from the reference markdown (cached)."""
    try:
        text = _RULES_MD.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not read Clean Core rules reference at %s: %s", _RULES_MD, exc)
        return _DEFAULT_VERSION
    m = _VERSION_RE.search(text)
    return m.group(1) if m else _DEFAULT_VERSION


def get_edition_policy(edition: Edition | None) -> EditionPolicy:
    """Return the strictness policy for an edition (defaults to on-premise)."""
    return _EDITION_POLICIES.get(edition or DEFAULT_EDITION, _EDITION_POLICIES[DEFAULT_EDITION])


def log_rules_version() -> str:
    """Log the active rule-set version for traceability (call on agent start)."""
    version = get_rules_version()
    logger.info("Clean Core rule set version %s loaded from %s", version, _RULES_MD.name)
    return version
