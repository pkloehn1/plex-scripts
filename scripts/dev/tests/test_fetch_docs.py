"""Tests for scripts.dev.fetch_docs."""

from __future__ import annotations

from email.message import Message
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.fetch_docs import (
    HTMLToMarkdown,
    fetch_url,
    html_to_markdown,
    main,
)


class TestHTMLToMarkdown:
    def test_headings(self) -> None:
        parser = HTMLToMarkdown()
        parser.feed("<h1>Title</h1><h2>Sub</h2><h3>Deep</h3>")
        markup = parser.get_markdown()
        assert "# Title" in markup
        assert "## Sub" in markup
        assert "### Deep" in markup

    def test_paragraph(self) -> None:
        parser = HTMLToMarkdown()
        parser.feed("<p>Hello world</p>")
        assert "Hello world" in parser.get_markdown()

    def test_line_break(self) -> None:
        parser = HTMLToMarkdown()
        parser.feed("line1<br>line2")
        markup = parser.get_markdown()
        assert "line1" in markup
        assert "line2" in markup

    def test_list_items(self) -> None:
        parser = HTMLToMarkdown()
        parser.feed("<ul><li>one</li><li>two</li></ul>")
        markup = parser.get_markdown()
        assert "- one" in markup
        assert "- two" in markup

    def test_links(self) -> None:
        parser = HTMLToMarkdown()
        parser.feed('<a href="https://example.com">click</a>')
        assert "[click](https://example.com)" in parser.get_markdown()

    def test_pre_code_block(self) -> None:
        parser = HTMLToMarkdown()
        parser.feed("<pre>some code</pre>")
        markup = parser.get_markdown()
        assert "```" in markup
        assert "some code" in markup

    def test_inline_code(self) -> None:
        parser = HTMLToMarkdown()
        parser.feed("use <code>foo</code> here")
        markup = parser.get_markdown()
        assert "`foo`" in markup

    def test_code_inside_pre_not_double_backticked(self) -> None:
        parser = HTMLToMarkdown()
        parser.feed("<pre><code>block</code></pre>")
        markup = parser.get_markdown()
        assert "```" in markup
        assert "`block`" not in markup

    def test_skip_script_tag(self) -> None:
        parser = HTMLToMarkdown()
        parser.feed("<script>alert('xss')</script><p>visible</p>")
        markup = parser.get_markdown()
        assert "alert" not in markup
        assert "visible" in markup

    def test_skip_style_tag(self) -> None:
        parser = HTMLToMarkdown()
        parser.feed("<style>.red{color:red}</style><p>text</p>")
        markup = parser.get_markdown()
        assert "red" not in markup
        assert "text" in markup

    def test_skip_nav_footer_header(self) -> None:
        parser = HTMLToMarkdown()
        parser.feed("<nav>menu</nav><footer>copy</footer><header>top</header><p>body</p>")
        markup = parser.get_markdown()
        assert "menu" not in markup
        assert "copy" not in markup
        assert "top" not in markup
        assert "body" in markup

    def test_nested_skip_tags(self) -> None:
        parser = HTMLToMarkdown()
        parser.feed("<nav><div><p>nested skip</p></div></nav><p>visible</p>")
        markup = parser.get_markdown()
        assert "nested skip" not in markup
        assert "visible" in markup

    def test_multiple_blank_lines_collapsed(self) -> None:
        parser = HTMLToMarkdown()
        parser.feed("<p>a</p><p></p><p></p><p>b</p>")
        markup = parser.get_markdown()
        assert "\n\n\n" not in markup

    def test_endtag_inside_skip(self) -> None:
        parser = HTMLToMarkdown()
        parser.feed("<nav><pre>code</pre></nav><p>ok</p>")
        markup = parser.get_markdown()
        assert "code" not in markup
        assert "ok" in markup

    def test_starttag_inside_skip(self) -> None:
        parser = HTMLToMarkdown()
        parser.feed("<script><div>inner</div></script><p>safe</p>")
        markup = parser.get_markdown()
        assert "inner" not in markup
        assert "safe" in markup

    def test_h4_h5_h6(self) -> None:
        parser = HTMLToMarkdown()
        parser.feed("<h4>h4</h4><h5>h5</h5><h6>h6</h6>")
        markup = parser.get_markdown()
        assert "#### h4" in markup
        assert "##### h5" in markup
        assert "###### h6" in markup

    def test_link_without_href(self) -> None:
        parser = HTMLToMarkdown()
        parser.feed("<a>text</a>")
        markup = parser.get_markdown()
        assert "[text]()" in markup

    def test_endtag_code_during_pre(self) -> None:
        parser = HTMLToMarkdown()
        parser.feed("<pre>line</pre>")
        markup = parser.get_markdown()
        assert "```" in markup
        assert "`line`" not in markup


class TestFetchUrl:
    def test_successful_fetch(self) -> None:
        mock_response = MagicMock()
        mock_response.read.return_value = b"<html>test</html>"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        with patch("scripts.dev.fetch_docs.urlopen", return_value=mock_response):
            result = fetch_url("https://example.com")
            assert result == "<html>test</html>"

    def test_http_error_exits(self) -> None:
        from urllib.error import HTTPError

        exc = HTTPError("https://example.com", 404, "Not Found", Message(), BytesIO(b""))
        with (
            patch("scripts.dev.fetch_docs.urlopen", side_effect=exc),
            pytest.raises(SystemExit),
        ):
            fetch_url("https://example.com")

    def test_url_error_exits(self) -> None:
        from urllib.error import URLError

        exc = URLError("Connection refused")
        with (
            patch("scripts.dev.fetch_docs.urlopen", side_effect=exc),
            pytest.raises(SystemExit),
        ):
            fetch_url("https://example.com")


class TestHtmlToMarkdown:
    def test_converts_html(self) -> None:
        result = html_to_markdown("<h1>Hello</h1><p>World</p>")
        assert "# Hello" in result
        assert "World" in result


class TestMain:
    def test_stdout_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("scripts.dev.fetch_docs.fetch_url", return_value="<h1>Title</h1>"),
            patch("sys.argv", ["fetch_docs", "https://example.com"]),
        ):
            result = main()
        assert result == 0
        assert "# Title" in capsys.readouterr().out

    def test_raw_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("scripts.dev.fetch_docs.fetch_url", return_value="<h1>Raw</h1>"),
            patch("sys.argv", ["fetch_docs", "--raw", "https://example.com"]),
        ):
            result = main()
        assert result == 0
        assert "<h1>Raw</h1>" in capsys.readouterr().out

    def test_file_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        outfile = str(tmp_path) + "/out.md"
        with (
            patch("scripts.dev.fetch_docs.fetch_url", return_value="<p>Content</p>"),
            patch("sys.argv", ["fetch_docs", "--output", outfile, "https://example.com"]),
        ):
            result = main()
        assert result == 0
        with open(outfile, encoding="utf-8") as fobj:
            assert "Content" in fobj.read()
        assert "Written to" in capsys.readouterr().err

    def test_timeout_arg(self) -> None:
        with (
            patch("scripts.dev.fetch_docs.fetch_url", return_value="<p>ok</p>") as mock_fetch,
            patch("sys.argv", ["fetch_docs", "--timeout", "5", "https://example.com"]),
        ):
            main()
        mock_fetch.assert_called_once_with("https://example.com", 5)
