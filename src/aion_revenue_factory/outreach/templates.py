"""Strict template rendering with ``{{variable}}`` substitution.

Design rule (from the spec): unknown variables must *fail validation* rather
than silently produce a broken email. So:

- ``required_variables(template)`` lists every ``{{name}}`` referenced.
- ``render(template, variables)`` raises :class:`TemplateError` if any
  referenced variable is missing (or is an unsupported/empty placeholder),
  instead of emitting ``{{first_name}}`` literally into a prospect's inbox.

Whitespace is allowed inside braces (``{{ first_name }}``). Variable names are
restricted to ``[A-Za-z0-9_]`` so stray braces in copy don't get misread as
merge fields.
"""

from __future__ import annotations

import re

_VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class TemplateError(ValueError):
    """Raised when a template references a variable that wasn't provided."""


def required_variables(template: str) -> list[str]:
    """Return the ordered, de-duplicated variable names a template references."""
    seen: list[str] = []
    for match in _VAR_RE.finditer(template):
        name = match.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def missing_variables(template: str, variables: dict) -> list[str]:
    """Variables the template needs but ``variables`` doesn't supply."""
    provided = {k for k, v in variables.items() if v not in (None, "")}
    return [name for name in required_variables(template) if name not in provided]


def validate(template: str, variables: dict) -> None:
    """Raise :class:`TemplateError` if the template can't be safely rendered."""
    missing = missing_variables(template, variables)
    if missing:
        raise TemplateError(
            f"template references undefined variable(s): {', '.join(missing)}"
        )


def render(template: str, variables: dict) -> str:
    """Substitute ``{{var}}`` from ``variables``; fail on any missing variable."""
    validate(template, variables)

    def _sub(match: re.Match) -> str:
        return str(variables[match.group(1)])

    return _VAR_RE.sub(_sub, template)
