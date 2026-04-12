#!/usr/bin/env python3
"""Fetch web documentation with browser user-agent.

Many documentation sites block AI/bot user agents but allow standard browsers.
This tool fetches content using a Chrome user-agent for dev research purposes.

Usage:
    python -m scripts.dev.fetch_docs <url> [--output file.md]
    python -m scripts.dev.fetch_docs https://www.truenas.com/docs/scale/25.10/
"""

from __future__ import annotations

import argparse
import html.parser
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class HTMLToMarkdown(html.parser.HTMLParser):
    """Simple HTML to Markdown converter for documentation pages."""

    def __init__(self) -> None:
        super().__init__()
        self.output: list[str] = []
        self.in_pre = False
        self.in_code = False
        self.current_tag: str | None = None
        self.skip_tags = {"script", "style", "nav", "footer", "header"}
        self.skip_depth = 0
        self._pending_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.skip_tags:
            self.skip_depth += 1
            return
        if self.skip_depth > 0:
            return

        self.current_tag = tag
        if tag == "pre":
            self.in_pre = True
            self.output.append("\n```\n")
        elif tag == "code" and not self.in_pre:
            self.in_code = True
            self.output.append("`")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            self.output.append(f"\n{'#' * level} ")
        elif tag == "p":
            self.output.append("\n\n")
        elif tag == "br":
            self.output.append("\n")
        elif tag == "li":
            self.output.append("\n- ")
        elif tag == "a":
            attrs_dict = dict(attrs)
            href = attrs_dict.get("href", "")
            self.output.append("[")
            self._pending_href = href

    def handle_endtag(self, tag: str) -> None:
        if tag in self.skip_tags:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth > 0:
            return

        if tag == "pre":
            self.in_pre = False
            self.output.append("\n```\n")
        elif tag == "code" and not self.in_pre:
            self.in_code = False
            self.output.append("`")
        elif tag == "a" and self._pending_href is not None:
            self.output.append(f"]({self._pending_href})")
            self._pending_href = None

    def handle_data(self, data: str) -> None:
        if self.skip_depth > 0:
            return
        text = data if self.in_pre else data.strip()
        if text:
            self.output.append(text)

    def get_markdown(self) -> str:
        result = "".join(self.output)
        # Clean up multiple blank lines
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip()


def fetch_url(url: str, timeout_seconds: int = 30) -> str:
    """Fetch URL content with browser user-agent.

    Note: For filtering ads/malware, configure DNS to use Quad9 (9.9.9.9)
    or Cloudflare malware filter (1.1.1.2) at the system/network level.
    """
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            content: str = response.read().decode("utf-8", errors="replace")
            return content
    except HTTPError as http_error:
        print(
            f"HTTP Error {http_error.code}: {http_error.reason}",
            file=sys.stderr,
        )
        sys.exit(1)
    except URLError as url_error:
        print(f"URL Error: {url_error.reason}", file=sys.stderr)
        sys.exit(1)


def html_to_markdown(html_content: str) -> str:
    """Convert HTML to Markdown."""
    parser = HTMLToMarkdown()
    parser.feed(html_content)
    return parser.get_markdown()


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch web documentation with browser user-agent")
    parser.add_argument("url", help="URL to fetch")
    parser.add_argument(
        "--output",
        "-o",
        help="Output file (default: stdout)",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Output raw HTML instead of Markdown",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Request timeout in seconds (default: 30)",
    )

    args = parser.parse_args()

    html_content = fetch_url(args.url, args.timeout)

    if args.raw:
        output = html_content
    else:
        output = html_to_markdown(html_content)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as output_file:
            output_file.write(output)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output)

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
