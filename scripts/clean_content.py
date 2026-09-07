#!/usr/bin/env python3
"""Strip a fetched page down to its content. Discover's step 6.

Two paths:

  HTML  -> stdlib parse, drop chrome (nav/header/footer/script/...), emit a
           minimal markdown rendering. No dependencies.
  PDF /
  DOCX  -> markitdown (`pip install markitdown`), imported lazily so the HTML
           path works whether or not it is installed.

Output must be DETERMINISTIC. It feeds hash_compare.py, and any instability
here — reordered whitespace, a timestamp, an unstable attribute — turns every
run into a false "changed". Given the same bytes in, this must produce the
same bytes out, forever.

What it does NOT do: interpret, summarize, or decide what matters. That is
Extract's job, and this script running before Extract is the whole point of
the split.

Usage:
    python clean_content.py FILE [--out FILE] [--format html|auto]
    cat page.html | python clean_content.py - --format html
"""

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

# Dropped wholesale, contents included. Page furniture, not content.
CHROME_TAGS = {
    "head", "title", "script", "style", "noscript", "nav", "header", "footer",
    "aside", "form", "svg", "iframe", "template", "button", "select", "dialog",
}

# Attribute values that mark a container as chrome even when its tag doesn't.
CHROME_HINTS = re.compile(
    r"\b(nav|navbar|menu|breadcrumb|sidebar|footer|header|cookie|consent|"
    r"banner|subscribe|newsletter|social|share|related|advert|promo)\b",
    re.I,
)

BLOCK_TAGS = {"p", "div", "section", "article", "main", "br", "tr", "blockquote"}
HEADINGS = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}
MARKITDOWN_SUFFIXES = {".pdf", ".docx", ".pptx", ".xlsx", ".doc", ".ppt", ".xls", ".epub"}


class ContentExtractor(HTMLParser):
    """Emit text content, skipping chrome subtrees."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._skip_tag: str | None = None
        self._list_depth = 0

    def _is_chrome(self, tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if tag in CHROME_TAGS:
            return True
        for name, value in attrs:
            if name in ("class", "id", "role", "aria-label") and value:
                if CHROME_HINTS.search(value):
                    return True
        return False

    def handle_starttag(self, tag, attrs):
        if self._skip_depth:
            if tag == self._skip_tag:
                self._skip_depth += 1
            return
        if self._is_chrome(tag, attrs):
            self._skip_depth = 1
            self._skip_tag = tag
            return
        if tag in HEADINGS:
            self.parts.append("\n\n" + HEADINGS[tag] + " ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in ("ul", "ol"):
            self._list_depth += 1
            self.parts.append("\n")
        elif tag in BLOCK_TAGS:
            self.parts.append("\n\n" if tag != "br" else "\n")
        elif tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if self._skip_depth:
            if tag == self._skip_tag:
                self._skip_depth -= 1
                if self._skip_depth == 0:
                    self._skip_tag = None
            return
        if tag in HEADINGS or tag in BLOCK_TAGS:
            self.parts.append("\n\n")
        elif tag in ("ul", "ol"):
            self._list_depth = max(0, self._list_depth - 1)
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth:
            return
        if data.strip():
            self.parts.append(re.sub(r"\s+", " ", data))

    def text(self) -> str:
        return "".join(self.parts)


def normalize(text: str) -> str:
    """Deterministic whitespace normalization. Same in, same out, always."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\n +", "\n", text)
    return text.strip() + "\n"


def clean_html(html: str) -> str:
    parser = ContentExtractor()
    parser.feed(html)
    parser.close()
    return normalize(parser.text())


def clean_document(path: Path) -> str:
    """PDF/DOCX/etc via markitdown. Imported lazily — HTML never needs it."""
    try:
        from markitdown import MarkItDown
    except ImportError:
        sys.exit(
            f"error: {path.suffix} input requires markitdown.\n"
            "       pip install markitdown"
        )
    return normalize(MarkItDown().convert(str(path)).text_content)


def main() -> int:
    ap = argparse.ArgumentParser(description="Strip fetched content to its substance.")
    ap.add_argument("file", help="input file, or - for stdin")
    ap.add_argument("--out", help="write here instead of stdout")
    ap.add_argument("--format", choices=["auto", "html"], default="auto")
    args = ap.parse_args()

    if args.file == "-":
        cleaned = clean_html(sys.stdin.read())
    else:
        path = Path(args.file)
        if args.format == "auto" and path.suffix.lower() in MARKITDOWN_SUFFIXES:
            cleaned = clean_document(path)
        else:
            cleaned = clean_html(path.read_text(encoding="utf-8", errors="replace"))

    if args.out:
        Path(args.out).write_text(cleaned, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(cleaned)
    return 0


if __name__ == "__main__":
    sys.exit(main())
