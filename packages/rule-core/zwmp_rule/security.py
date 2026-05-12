from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class URLSafetyError(ValueError):
    pass


BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}


def assert_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise URLSafetyError("only http and https URLs are allowed")
    if not parsed.hostname:
        raise URLSafetyError("URL must include a hostname")
    hostname = parsed.hostname.lower()
    if hostname in BLOCKED_HOSTS:
        raise URLSafetyError("localhost URLs are not allowed")
    try:
        ip = ipaddress.ip_address(hostname)
        _assert_public_ip(ip)
        return
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise URLSafetyError("hostname could not be resolved") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        _assert_public_ip(ip)


def _assert_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise URLSafetyError(f"non-public address is not allowed: {ip}")

