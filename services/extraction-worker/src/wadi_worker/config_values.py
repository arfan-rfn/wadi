"""What a value from an analyzed project's config may be published as (§5.2.18).

The rule: a value read from the analyzed project's config is not published
unless a reader routes by it, and then without credentials. Everything the
worker stores is served by the REST API, the MCP server, the web UI and the
snapshot export, so "stored" and "published" are the same thing here.

Three things follow, and this module is the one place they are decided:

* ``spring.security.*`` settings publish their KEY only (auth evidence). The
  namespace holds client secrets and passwords beside harmless settings, and
  no reader routes by any of them.
* A JDBC URL is never published. Nothing routes HTTP by one, and its
  credentials have a spelling per vendor.
* A value the stitcher may route by (a URL, a host) is published with its
  user-info removed and its secret-bearing query values blanked. When what is
  left still holds an ``@`` the credentials could not be told apart from the
  address, and the value is withheld whole: a host built from half a password
  is a wrong route, and an honest gap is better than either that or a leak.

What this cannot see is a secret that is part of the address itself, such as
a token in a URL path. It is published, because the path is what routes.
"""

import re
from collections.abc import Iterable

#: Query (or ``;`` matrix) parameters whose VALUE is blanked. Matched loosely
#: on purpose: blanking ``?keyword=`` costs nothing, since no reader routes by
#: a query string, while missing ``?api_key=`` publishes a credential.
_SECRET_PARAMETER = re.compile(
    r"(?P<name>[?&;][^=&#;\s]*(?:pass|pwd|secret|token|key|sig|credential|auth)[^=&#;\s]*=)"
    r"[^&#;\s]*",
    re.IGNORECASE,
)

#: ``user:password@`` ahead of a host: after ``scheme://``, or opening a bare
#: ``host``-shaped value. Greedy to the LAST ``@`` of the authority, so a
#: password that itself holds an ``@`` goes with the rest.
_USER_INFO = re.compile(r"(?:(?<=://)|^)[^/?#\s]*@")

_JDBC = re.compile(r"\bjdbc:", re.IGNORECASE)

_SECURITY_NAMESPACE = "SPRING_SECURITY_"


def is_security_key(name: str) -> bool:
    """``spring.security.*``, in dotted or env-var spelling (relaxed binding)."""
    return name.upper().replace(".", "_").replace("-", "_").startswith(_SECURITY_NAMESPACE)


def is_jdbc_url(value: str) -> bool:
    """A JDBC URL anywhere in the value, a ``${KEY:default}`` default included."""
    return _JDBC.search(value) is not None


def strip_credentials(value: str) -> str | None:
    """``value`` without credentials, or None when they cannot be separated."""
    stripped = _SECRET_PARAMETER.sub(lambda match: match.group("name"), value)
    stripped = _USER_INFO.sub("", stripped)
    if "@" in stripped or not stripped.strip():
        return None
    return stripped


def publishable_entries(entries: Iterable[tuple[str, str]]) -> tuple[dict[str, str], list[str]]:
    """Routing entries as they may be published, and the keys withheld.

    Security keys and JDBC URLs are dropped by rule and are not gaps. A key
    lands in the withheld list only when its value was routing-shaped and its
    credentials could not be separated, which is a gap a reader should be able
    to count (P10).
    """
    published: dict[str, str] = {}
    withheld: list[str] = []
    for key, value in entries:
        if is_security_key(key) or is_jdbc_url(value):
            continue
        stripped = strip_credentials(value)
        if stripped is None:
            withheld.append(key)
        else:
            published[key] = stripped
    return published, withheld


def withheld_note(key: str) -> str:
    """The ``config_notes`` entry for a withheld value (the key, never the value)."""
    return f"config-value-withheld:{key}"
