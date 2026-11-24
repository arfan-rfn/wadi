"""What a value from an analyzed project's config may be published as (§5.2.18).

The rule: a value read from the analyzed project's config is not published
unless a reader routes by it, and then without credentials. Everything the
worker stores is served by the REST API, the MCP server, the web UI and the
snapshot export, so "stored" and "published" are the same thing here.

Four things follow, and this module is the one place they are decided:

* ``spring.security.*`` settings publish their KEY only (auth evidence). The
  namespace holds client secrets and passwords beside harmless settings, and
  no reader routes by any of them.
* A JDBC URL is never published. Nothing routes HTTP by one, and its
  credentials have a spelling per vendor.
* A value the stitcher may route by (a URL, a host) is published as its
  address only: scheme, host, port and path. Its user-info goes, and so does
  everything from the first ``?``, ``#`` or ``;``, because no reader routes by
  a query, a fragment or a matrix parameter, and a list of secret parameter
  names is never complete. A query runs to the end of the value. Only the
  ``}`` of the placeholders around it may follow it. Text alone cannot show
  where a query ends: in ``?cb=https://a/x,https://b/y`` the comma is inside
  it, and Spring joins ``${A:http://h?k=a}b`` into one query. So when anything
  else follows a query, or the query holds a comma, or what is left still
  holds an ``@``, an ``=``, a space inside one element of a comma list, or a
  brace that closes nothing, it is not an address this module can read, and
  the value is withheld whole: a host built from half a password is a wrong
  route, and an honest gap is better than either that or a leak.
* A key is published only when it reads as a key. A line the properties
  parser split in the wrong place can carry a value inside its "key".

What this cannot see is a secret that is part of the address itself, such as
a token in a URL path. It is published, because the path is what routes.
"""

import re
from collections.abc import Iterable

#: The first query, fragment or matrix parameter after the address, up to a
#: space or a brace. A ``${KEY}`` placeholder inside it is part of it, so
#: ``?apiKey=${API_KEY}`` goes whole. A closing brace it stops at is left alone,
#: so a ``${KEY:default}`` placeholder around it keeps its shape.
_AFTER_ADDRESS = re.compile(r"[?#;](?:\$\{[^{}\s]*\}|[^\s{}])*")

#: ``user:password@`` ahead of a host: after ``scheme://``, or opening a bare
#: ``host``-shaped value. Greedy to the LAST ``@`` of the authority, so a
#: password that itself holds an ``@`` goes with the rest. It never crosses a
#: comma: in ``http://a:80,u:p@b:80`` the first host is not user-info.
_USER_INFO = re.compile(r"(?:(?<=://)|^)[^/?#\s,]*@")

#: What a config key or an environment variable name is made of.
_KEY_NAME = re.compile(r"[A-Za-z0-9_.\-\[\]]+")

_JDBC = re.compile(r"\bjdbc:", re.IGNORECASE)

_SECURITY_NAMESPACE = "SPRING_SECURITY_"


def is_security_key(name: str) -> bool:
    """``spring.security.*``, in dotted or env-var spelling (relaxed binding)."""
    return name.upper().replace(".", "_").replace("-", "_").startswith(_SECURITY_NAMESPACE)


def is_jdbc_url(value: str) -> bool:
    """A JDBC URL anywhere in the value, a ``${KEY:default}`` default included."""
    return _JDBC.search(value) is not None


def is_key_name(name: str) -> bool:
    """Whether ``name`` reads as a config key, and so is safe to publish."""
    return _KEY_NAME.fullmatch(name) is not None


def strip_credentials(value: str) -> str | None:
    """The address in ``value``, or None when it cannot be told from the rest."""
    without_user = _USER_INFO.sub("", value)
    if "@" in without_user:
        # Checked before the query goes: in `https://user:pa?ss@host` the
        # password ends the authority early, and cutting at the `?` would
        # publish `https://user:pa`.
        return None
    address = without_user
    after = _AFTER_ADDRESS.search(without_user)
    if after is not None:
        rest = without_user[after.end() :]
        if "," in after.group() or rest.strip("}"):
            # The query may not have ended here. A comma in it can open the
            # next address of a list or sit inside the query, and text after
            # it can be more of the query, so no cut is known to be safe.
            return None
        address = without_user[: after.start()] + rest
    if not address.strip() or "=" in address:
        return None
    if any(len(element.split()) > 1 for element in address.split(",")):
        return None
    if not _braces_balanced(address):
        return None
    return address


def _braces_balanced(text: str) -> bool:
    """Every brace closes one opened before it, and none is left open.

    A ``${KEY}`` placeholder and a ``{id}`` path variable both count, so a
    route template keeps routing while a cut that split a placeholder is caught.
    """
    depth = 0
    for char in text:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def publishable_entries(entries: Iterable[tuple[str, str]]) -> tuple[dict[str, str], list[str]]:
    """Routing entries as they may be published, and the keys withheld.

    Security keys and JDBC URLs are dropped by rule and are not gaps. So is an
    entry whose key does not read as a key, since its name cannot be published
    either. A key lands in the withheld list only when its value could not be
    read as an address, which is a gap a reader should be able to count (P10).
    """
    published: dict[str, str] = {}
    withheld: list[str] = []
    for key, value in entries:
        if not is_key_name(key) or is_security_key(key) or is_jdbc_url(value):
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
