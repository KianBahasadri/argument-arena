"""Bounded HTTP clients for model requests and independently retrieved evidence."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import aiohttp


class ProviderError(RuntimeError):
    """A provider is unavailable, has exhausted a quota, or returned invalid data."""

    def __init__(self, message: str, status: str = "failed") -> None:
        super().__init__(message)
        self.status = status


def public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return ip.is_global and not ip.is_multicast and not ip.is_reserved
    except ValueError:
        return False


def validate_public_url(url: str) -> str:
    """Only uncredentialed public HTTPS URLs on the standard port are evidence."""
    try:
        if not isinstance(url, str) or len(url) > 4096:
            raise ValueError
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.port not in (None, 443)
            or any(ord(char) <= 32 for char in url)
            or "%" in parts.hostname
        ):
            raise ValueError
        try:
            ipaddress.ip_address(parts.hostname)
        except ValueError:
            pass  # The connector validates the actual DNS answers before connecting.
        else:
            if not public_address(parts.hostname):
                raise ValueError
        return url
    except (ValueError, TypeError) as exc:
        raise ProviderError("Evidence URLs must use public HTTPS on port 443.") from exc


class PublicResolver(aiohttp.abc.AbstractResolver):
    """Validate DNS answers at the connector, preventing a second unchecked lookup."""

    def __init__(self) -> None:
        self.resolver = aiohttp.resolver.DefaultResolver()

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        results = await self.resolver.resolve(host, port, family)
        if not results or any(not public_address(result["host"]) for result in results):
            raise ProviderError("Evidence hostname resolved to a non-public address.")
        return results

    async def close(self) -> None:
        await self.resolver.close()


class PageText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.skipped = 0
        self.in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.skipped += 1
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.skipped = max(0, self.skipped - 1)
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if not self.skipped:
            self.parts.append(data)
            if self.in_title:
                self.title_parts.append(data)


def plain_text(raw: str) -> tuple[str, str]:
    parser = PageText()
    parser.feed(raw)
    return " ".join(" ".join(parser.parts).split()), " ".join(parser.title_parts).strip()


class HTTPTransport:
    """No credentials, cookies or model instructions are sent to evidence sites."""

    def __init__(self, timeout: float = 45, max_bytes: int = 1_000_000) -> None:
        self.timeout = aiohttp.ClientTimeout(total=timeout, connect=10)
        self.max_bytes = max_bytes

    async def _body(self, response: aiohttp.ClientResponse) -> bytes:
        body = bytearray()
        async for chunk in response.content.iter_chunked(16_384):
            body.extend(chunk)
            if len(body) > self.max_bytes:
                raise ProviderError("Provider response exceeded the configured size limit.")
        return bytes(body)

    async def post_json(self, url: str, payload: dict, headers: dict) -> dict:
        # Endpoints are operator controlled; plaintext is intentionally rejected to
        # avoid transmitting provider credentials over an unencrypted connection.
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ProviderError("Provider endpoints must use uncredentialed HTTPS URLs.")
        try:
            async with aiohttp.ClientSession(timeout=self.timeout, trust_env=False) as session:
                async with session.post(url, json=payload, headers=headers, allow_redirects=False) as response:
                    if response.status >= 300:
                        raise ProviderError(f"Provider returned HTTP {response.status}.")
                    result = json.loads(await self._body(response))
                    if not isinstance(result, dict):
                        raise ProviderError("Provider returned a non-object JSON response.")
                    return result
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise ProviderError("Provider request failed or returned malformed JSON.") from exc

    async def fetch_source(self, url: str) -> dict:
        resolver = PublicResolver()
        connector = aiohttp.TCPConnector(resolver=resolver, use_dns_cache=False)
        try:
            async with aiohttp.ClientSession(
                timeout=self.timeout, connector=connector, trust_env=False,
                cookie_jar=aiohttp.DummyCookieJar(),
                headers={"User-Agent": "ArgumentArena/1.0 (evidence retrieval)", "Accept": "text/html,text/plain"},
            ) as session:
                for _ in range(4):
                    validate_public_url(url)
                    async with session.get(url, allow_redirects=False) as response:
                        if response.status in {301, 302, 303, 307, 308}:
                            location = response.headers.get("Location")
                            if not location:
                                raise ProviderError("Evidence redirect omitted its destination.")
                            url = urljoin(url, location)
                            continue
                        if response.status != 200:
                            raise ProviderError(f"Evidence source returned HTTP {response.status}.")
                        content_type = response.headers.get("Content-Type", "").lower()
                        if not any(value in content_type for value in ("text/html", "text/plain", "application/xhtml+xml")):
                            raise ProviderError("Evidence source is not an HTML or plain-text page.")
                        raw = (await self._body(response)).decode("utf-8", errors="replace")
                        text, title = plain_text(raw) if "html" in content_type else (raw, "")
                        text = re.sub(r"\s+", " ", text).strip()
                        if len(text) < 40:
                            raise ProviderError("Evidence source did not contain enough readable text.")
                        return {"url": url, "title": title or urlsplit(url).hostname, "content": text[:24_000], "inspected": True, "excerpt_truncated": len(text) > 24_000}
                raise ProviderError("Evidence source exceeded the redirect limit.")
        except (aiohttp.ClientError, TimeoutError, UnicodeError, ValueError) as exc:
            raise ProviderError("Evidence source could not be retrieved safely.") from exc
        finally:
            await resolver.close()
