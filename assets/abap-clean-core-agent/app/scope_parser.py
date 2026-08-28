"""Scope parsing for ABAP Clean Core analysis.

Parses a raw scope string into a normalised :class:`Scope`. Supported inputs:

- a single package name (e.g. ``ZMYPACKAGE``)
- a comma-separated list of package names
- a transport request number (``<SID>K<6-digit-number>``, e.g. ``S4DK900123``)
- a comma-separated list of individual object names, each optionally type-prefixed
  (e.g. ``PROG:ZMYPROGRAM``, ``CLAS:ZCL_MY_CLASS``)
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

Edition = Literal["on-premise", "private-cloud", "public-cloud"]
ScopeType = Literal["package", "transport", "objects"]

# Transport request: 3-char system id (SID), literal 'K', then exactly 6 digits.
_TRANSPORT_RE = re.compile(r"^[A-Z0-9]{3}K[0-9]{6}$")
# A single object token, optionally 'TYPE:' prefixed. Names are SAP identifiers.
_OBJECT_RE = re.compile(r"^(?:(?P<type>[A-Z]{3,4}):)?(?P<name>[A-Z_/][A-Z0-9_/]*)$")
# A package name (customer or SAP namespace identifier). No ':' allowed.
_PACKAGE_RE = re.compile(r"^[A-Z_/][A-Z0-9_/]*$")

_VALID_EDITIONS: tuple[Edition, ...] = ("on-premise", "private-cloud", "public-cloud")


class ScopeParseError(ValueError):
    """Raised when a scope string cannot be parsed into a known form."""


@dataclass
class Scope:
    """A normalised analysis scope."""

    scope_type: ScopeType
    identifiers: list[str] = field(default_factory=list)
    edition: Edition | None = None
    # For object lists, the parsed type prefix per identifier (name -> type or None).
    object_types: dict[str, str | None] = field(default_factory=dict)

    @property
    def scope_id(self) -> str:
        """A stable, filename-safe identifier for this scope."""
        joined = "-".join(self.identifiers)
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", joined).strip("_")
        return safe or self.scope_type


def _normalise_edition(edition: str | None) -> Edition | None:
    if edition is None:
        return None
    value = edition.strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "on-premise": "on-premise",
        "onpremise": "on-premise",
        "on-prem": "on-premise",
        "private": "private-cloud",
        "private-cloud": "private-cloud",
        "cloud-private": "private-cloud",
        "public": "public-cloud",
        "public-cloud": "public-cloud",
        "cloud-public": "public-cloud",
    }
    resolved = aliases.get(value)
    if resolved is None:
        raise ScopeParseError(
            f"Unrecognised S/4HANA edition '{edition}'. "
            f"Expected one of: on-premise, private-cloud, public-cloud."
        )
    return resolved  # type: ignore[return-value]


def parse_scope(raw: str, edition: str | None = None) -> Scope:
    """Parse a raw scope string into a :class:`Scope`.

    Raises :class:`ScopeParseError` with a descriptive message for unrecognised input.
    """
    if raw is None or not raw.strip():
        raise ScopeParseError("Scope input is empty. Provide a package, transport, or object list.")

    resolved_edition = _normalise_edition(edition)
    tokens = [t.strip() for t in raw.split(",") if t.strip()]
    if not tokens:
        raise ScopeParseError("Scope input contains no usable identifiers.")

    upper = [t.upper() for t in tokens]

    # A single transport request.
    if len(upper) == 1 and _TRANSPORT_RE.match(upper[0]):
        return Scope(scope_type="transport", identifiers=[upper[0]], edition=resolved_edition)

    # If any token carries a TYPE: prefix, treat the whole input as an object list.
    if any(":" in t for t in upper):
        return _parse_object_list(upper, resolved_edition)

    # Otherwise: all tokens must be valid package names -> package scope.
    if all(_PACKAGE_RE.match(t) for t in upper):
        return Scope(scope_type="package", identifiers=upper, edition=resolved_edition)

    # Fall back to object list if every token is a bare object name.
    if all(_OBJECT_RE.match(t) for t in upper):
        return _parse_object_list(upper, resolved_edition)

    bad = [t for t in upper if not _PACKAGE_RE.match(t) and not _OBJECT_RE.match(t)]
    raise ScopeParseError(
        f"Unrecognised scope input. Could not parse: {', '.join(bad)}. "
        f"Expected a package name, a transport request (<SID>K<6 digits>), "
        f"or object names (optionally 'TYPE:NAME')."
    )


def _parse_object_list(tokens: list[str], edition: Edition | None) -> Scope:
    identifiers: list[str] = []
    object_types: dict[str, str | None] = {}
    for tok in tokens:
        m = _OBJECT_RE.match(tok)
        if not m:
            raise ScopeParseError(
                f"Invalid object token '{tok}'. Expected 'NAME' or 'TYPE:NAME' "
                f"(e.g. 'CLAS:ZCL_MY_CLASS')."
            )
        name = m.group("name")
        identifiers.append(name)
        object_types[name] = m.group("type")
    return Scope(
        scope_type="objects",
        identifiers=identifiers,
        edition=edition,
        object_types=object_types,
    )
