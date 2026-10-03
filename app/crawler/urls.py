"""URL normalization, hashing and scoping helpers."""

from __future__ import annotations

import hashlib
import posixpath
import re
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "gclsrc", "msclkid", "yclid", "mc_cid", "mc_eid", "_ga", "_gl",
    "igshid", "ocid", "cmpid", "cmp", "ncid", "ito", "smid", "smtyp", "sr_share", "share",
    "src", "ref", "ref_src", "ref_url", "spm", "rss", "feed", "outputtype", "taid", "at_medium",
    "at_campaign", "at_custom1", "at_custom2", "at_custom3", "at_custom4", "__twitter_impression",
}
TRACKING_PREFIXES = ("utm_", "pk_", "mtm_", "hsa_", "vero_", "oly_", "__s", "_hs")
DEFAULT_PORTS = {"http": 80, "https": 443}
_SAFE_PATH = "/:@!$&'()*+,;=-._~%"
_SAFE_QUERY = "/?:@!$'()*+,;-._~%"

NON_HTML_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".tif", ".tiff", ".avif",
    ".mp3", ".mp4", ".m4a", ".m4v", ".mov", ".avi", ".wmv", ".webm", ".ogg", ".wav", ".flac",
    ".pdf", ".zip", ".gz", ".tgz", ".rar", ".7z", ".tar", ".exe", ".dmg", ".apk", ".msi",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".css", ".js", ".json", ".woff", ".woff2",
    ".ttf", ".eot", ".otf",
}


def _is_tracking(key: str) -> bool:
    k = key.lower()
    return k in TRACKING_PARAMS or k.startswith(TRACKING_PREFIXES)


def _normalize_host(host: str) -> str:
    host = host.strip().rstrip(".").lower()
    if not host or host.startswith("["):
        return host
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return host


def normalize_url(url: str, base: str | None = None, *, strip_tracking: bool = True) -> str:
    """Return a canonical form of `url` (resolved against `base` if relative).

    Lower-cases scheme/host, IDNA-encodes the host, drops default ports, fragments and
    tracking parameters, resolves dot-segments, collapses duplicate slashes, normalizes
    percent-encoding and sorts query parameters.
    """
    url = url.strip()
    if base:
        url = urljoin(base, url)
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = _normalize_host(parts.hostname or "")
    port = parts.port
    netloc = host
    if port and DEFAULT_PORTS.get(scheme) != port:
        netloc = f"{host}:{port}"

    path = parts.path or "/"
    path = re.sub(r"/{2,}", "/", path)
    trailing = path.endswith("/")
    path = posixpath.normpath(path)
    if path in (".", ""):
        path = "/"
    if trailing and not path.endswith("/"):
        path += "/"
    if not path.startswith("/"):
        path = "/" + path
    path = quote(unquote(path), safe=_SAFE_PATH)

    query_items = parse_qsl(parts.query, keep_blank_values=True)
    if strip_tracking:
        query_items = [(k, v) for k, v in query_items if not _is_tracking(k)]
    query_items.sort()
    query = urlencode(query_items, doseq=True, safe=_SAFE_QUERY)
    return urlunsplit((scheme, netloc, path, query, ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def host_of(url: str) -> str:
    return _normalize_host(urlsplit(url).hostname or "")


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def is_same_site(url: str, domains: list[str]) -> bool:
    """True if url's host equals or is a subdomain of any of `domains`."""
    host = host_of(url)
    for d in domains:
        d = _normalize_host(d)
        if host == d or host.endswith("." + d):
            return True
    return False


def looks_like_non_html(url: str) -> bool:
    path = urlsplit(url).path.lower()
    ext = posixpath.splitext(path)[1]
    return ext in NON_HTML_EXTENSIONS


def has_trap_pattern(url: str, max_repeat: int = 3, max_segments: int = 15) -> bool:
    """Heuristics against crawler traps: repeating path segments, very deep paths,
    calendar pagination far in the past/future, session-id params."""
    parts = urlsplit(url)
    segments = [s for s in parts.path.split("/") if s]
    if len(segments) > max_segments:
        return True
    counts: dict[str, int] = {}
    for s in segments:
        counts[s] = counts.get(s, 0) + 1
        if counts[s] > max_repeat:
            return True
    # repeated multi-segment sequences, e.g. /a/b/a/b/a/b
    for size in (2, 3):
        seqs = [tuple(segments[i : i + size]) for i in range(0, len(segments) - size + 1)]
        if any(seqs.count(seq) >= max_repeat for seq in set(seqs)):
            return True
    q = parts.query.lower()
    if re.search(r"(^|&)(phpsessid|jsessionid|sid|sessionid)=", q):
        return True
    return bool(re.search(r"(^|&)(page|p)=\d{4,}", q))
