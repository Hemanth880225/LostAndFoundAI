"""Strict Server-Side Request Forgery (SSRF) Protection and URL Validation."""

import ipaddress
import socket
import urllib.parse
from fastapi import HTTPException, status


ALLOWED_SCHEMES = {"http", "https"}

FORBIDDEN_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "169.254.169.254",  # AWS/GCP/Azure instance metadata
    "metadata.google.internal",
    "instance-data",
}


def validate_safe_url(url_str: str) -> urllib.parse.ParseResult:
    """
    Validate that a URL is safe to fetch:
    1. Scheme must be HTTP or HTTPS.
    2. Hostname must be present and not in forbidden hostnames list.
    3. Hostname cannot resolve to loopback, private, link-local, or reserved IPs.
    """
    clean_url = url_str.strip()
    try:
        parsed = urllib.parse.urlparse(clean_url)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed URL: {exc}",
        )

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported scheme '{parsed.scheme}'. Only HTTP and HTTPS are permitted.",
        )

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL is missing a valid hostname.",
        )

    hostname_lower = hostname.lower()
    if hostname_lower in FORBIDDEN_HOSTS or hostname_lower.endswith(".local") or hostname_lower.endswith(".internal"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Access to internal, local, or loopback addresses is forbidden.",
        )

    # Resolve IP addresses and inspect for private/local subnets
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not resolve host '{hostname}': {exc}",
        )

    for entry in addr_info:
        sockaddr = entry[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"URL resolves to a restricted or private network address ({ip_str}).",
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid IP address representation ({ip_str}).",
            )

    return parsed
