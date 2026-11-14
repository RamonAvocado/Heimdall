"""Form 13F-HR (institutional holdings) schemas and parsing for the `sec` provider."""

from __future__ import annotations

import re
from xml.etree import ElementTree

import polars as pl

from heimdall._contracts import ColumnSpec, SchemaSpec
from heimdall.schemas import Kind

FORM13F_HOLDINGS = SchemaSpec(
    name=Kind.HOLDINGS_13F.value,
    columns=(
        ColumnSpec("accession_number", pl.String, nullable=False),
        ColumnSpec(
            "filing_date", pl.Date, nullable=False, description="When it became public"
        ),
        ColumnSpec(
            "period", pl.Date, nullable=False, description="Quarter end it reports"
        ),
        ColumnSpec("cusip", pl.String, nullable=False),
        ColumnSpec("issuer", pl.String),
        ColumnSpec("title", pl.String, description="Class of the security, e.g. COM"),
        ColumnSpec("shares", pl.Float64, nullable=False),
        ColumnSpec("share_type", pl.String, description="SH = shares, PRN = principal"),
        ColumnSpec(
            "value", pl.Float64, nullable=False, description="USD, at quarter end"
        ),
        ColumnSpec(
            "put_call", pl.String, description="Put or Call for options; else null"
        ),
    ),
    time_column="filing_date",
)

FORM13F_FILERS = SchemaSpec(
    name=Kind.FILERS_13F.value,
    columns=(
        ColumnSpec(
            "cik", pl.String, nullable=False, description="10 digits, zero-padded"
        ),
        ColumnSpec("name", pl.String, nullable=False),
        ColumnSpec("filing_date", pl.Date, nullable=False),
    ),
    time_column="filing_date",
)

#: Filings before this reported `value` in thousands of dollars; from it, in dollars.
DOLLAR_VALUES_FROM = "2023-01-03"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_information_table(xml_text: str) -> list[dict]:
    """One dict per `infoTable` line. Namespaces vary between filers, so tags are
    matched by local name."""
    rows = []
    for entry in ElementTree.fromstring(xml_text).iter():
        if _local(entry.tag) != "infoTable":
            continue
        fields: dict[str, str] = {}
        for el in entry.iter():
            if el.text and el.text.strip():
                fields[_local(el.tag)] = el.text.strip()
        rows.append(
            {
                "cusip": fields.get("cusip", "").upper(),
                "issuer": fields.get("nameOfIssuer"),
                "title": fields.get("titleOfClass"),
                "shares": fields.get("sshPrnamt"),
                "share_type": fields.get("sshPrnamtType"),
                "value": fields.get("value"),
                "put_call": fields.get("putCall"),
            }
        )
    return rows


def parse_form_index(text: str) -> list[dict]:
    """The `13F-HR` lines of an EDGAR `full-index/.../form.idx` (originals only)."""
    rows = []
    for line in text.splitlines():
        if not line.startswith("13F-HR "):
            continue
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 4:
            continue
        rows.append(
            {
                "cik": f"{int(parts[-3]):010d}",
                "name": parts[1],
                "filing_date": parts[-2],
            }
        )
    return rows
