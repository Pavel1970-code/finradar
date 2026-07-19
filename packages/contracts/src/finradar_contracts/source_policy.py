"""Shared deny-by-default policy for official public sources."""

from urllib.parse import urlsplit


OFFICIAL_SOURCE_HOSTS = frozenset(
    {
        "matsne.gov.ge",
        "www.matsne.gov.ge",
        "rs.ge",
        "www.rs.ge",
        "mof.ge",
        "www.mof.ge",
        "nbg.gov.ge",
        "www.nbg.gov.ge",
        "services.nbg.gov.ge",
    }
)


class SourcePolicyError(ValueError):
    """A source URL violates the outbound and inbound source policy."""


def validate_official_source_url(url: str) -> str:
    """Validate a URL before requests, after redirects, and during Core import."""
    if not isinstance(url, str) or not url.strip():
        raise SourcePolicyError("source URL must be non-empty text")

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise SourcePolicyError("source URL is malformed") from error

    if parsed.scheme.casefold() != "https":
        raise SourcePolicyError("only HTTPS sources are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise SourcePolicyError("credentials are not allowed in source URLs")
    if port not in {None, 443}:
        raise SourcePolicyError("only the standard HTTPS port is allowed")

    hostname = (parsed.hostname or "").casefold().rstrip(".")
    if hostname not in OFFICIAL_SOURCE_HOSTS:
        raise SourcePolicyError("source host is not on the official allowlist")
    if not parsed.path.startswith("/"):
        raise SourcePolicyError("source URL path is malformed")
    return url
