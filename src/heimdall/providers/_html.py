"""Stdlib HTML table extraction, for providers that read a web page."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

__all__ = ["Table", "parse_tables"]

_HEADINGS = ("h2", "h3", "h4")
_SKIP = ("style", "script")
_FOOTNOTE = re.compile(r"\[(?:\d+|[a-z]|note \d+)\]")


@dataclass
class Table:
    """One `<table>`: its `id`, the text of the last heading before it, its
    first all-`<th>` row as `header`, and every row with a `<td>` as `rows`."""

    id: str | None
    heading: str
    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


def parse_tables(html: str) -> list[Table]:
    """Every top-level table in `html`, in document order. Cell text is
    whitespace-collapsed, with Wikipedia footnote marks (`[3]`) stripped; a
    table nested in a cell just adds its text to that cell."""
    parser = _TableParser()
    parser.feed(html)
    return parser.tables


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[Table] = []
        self._table: Table | None = None
        self._row: list[str] | None = None
        self._row_has_td = False
        self._text: list[str] | None = None  # the cell or heading being read
        self._nested = 0  # tables inside a cell: their text joins the cell
        self._skip = 0
        self._heading = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skip += 1
        elif tag == "table" and (self._nested or self._text is not None):
            self._nested += 1
        elif self._nested:
            return
        elif tag == "table":
            self._table = Table(dict(attrs).get("id"), self._heading)
        elif self._table is None:
            if tag in _HEADINGS:
                self._text = []
        elif tag == "tr":
            self._end_row()
            self._row, self._row_has_td = [], False
        elif tag in ("td", "th") and self._row is not None:
            self._row_has_td |= tag == "td"
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
        elif self._nested:
            self._nested -= tag == "table"
        elif tag == "table" and self._table is not None:
            self._end_row()
            self.tables.append(self._table)
            self._table = None
        elif tag == "tr":
            self._end_row()
        elif self._text is None:
            return
        elif tag in _HEADINGS and self._table is None:
            self._heading = _clean(self._text)
            self._text = None
        elif tag in ("td", "th") and self._row is not None:
            self._row.append(_clean(self._text))
            self._text = None

    def handle_data(self, data: str) -> None:
        if self._text is not None and not self._skip:
            self._text.append(data)

    def _end_row(self) -> None:
        if self._table is not None and self._row is not None:
            if self._row_has_td:
                self._table.rows.append(self._row)
            elif self._row and not self._table.header:
                self._table.header = self._row
        self._row = None


def _clean(parts: list[str]) -> str:
    return " ".join(_FOOTNOTE.sub("", "".join(parts)).split())
