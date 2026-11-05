"""Form 4 (insider transaction) schema and XML parsing for the `sec` provider."""

from __future__ import annotations

from xml.etree import ElementTree

import polars as pl

from heimdall._contracts import ColumnSpec, SchemaSpec
from heimdall.schemas import Kind

FORM4_TRANSACTIONS = SchemaSpec(
    name=Kind.INSIDER_TRADING.value,
    columns=(
        ColumnSpec("accession_number", pl.String, nullable=False),
        ColumnSpec("filing_date", pl.Date, nullable=False),
        ColumnSpec("issuer", pl.String, nullable=False),
        ColumnSpec("ticker", pl.String, nullable=False),
        ColumnSpec("owner", pl.String, nullable=False),
        ColumnSpec("position", pl.String),
        ColumnSpec(
            "kind",
            pl.String,
            nullable=False,
            description="derivative or non-derivative",
        ),
        ColumnSpec("security", pl.String),
        ColumnSpec("transaction_date", pl.Date, nullable=False),
        ColumnSpec(
            "code",
            pl.String,
            description="raw SEC transaction code, e.g. S/P/A/M/F/G/C/X",
        ),
        ColumnSpec("shares", pl.Float64),
        ColumnSpec(
            "price", pl.Float64, description="per-share price; often null for grants"
        ),
        ColumnSpec(
            "acquired_disposed", pl.String, description="A = acquired, D = disposed"
        ),
        ColumnSpec("shares_owned_after", pl.Float64),
        ColumnSpec("ownership", pl.String, description="D = direct, I = indirect"),
    ),
    time_column="transaction_date",
)


def _val(el: ElementTree.Element, tag: str) -> str | None:
    """Most Form 4 leaf fields are `<tag><value>...</value></tag>`; a missing
    value (e.g. no price on a grant) leaves whitespace, not "" - strip it.
    """
    for candidate in (el.findtext(f"{tag}/value"), el.findtext(tag)):
        if candidate is not None and candidate.strip():
            return candidate.strip()
    return None


def parse_form4_xml(xml_text: str) -> dict:
    root = ElementTree.fromstring(xml_text)
    owner_el = root.find("reportingOwner")
    relationship = (
        owner_el.find("reportingOwnerRelationship") if owner_el is not None else None
    )

    tables = (
        ("nonDerivativeTable", "non-derivative"),
        ("derivativeTable", "derivative"),
    )
    transactions = []
    for table, kind in tables:
        table_el = root.find(table)
        if table_el is None:
            continue
        # Only transactions: a table also lists holdings (positions, no date).
        for txn in table_el.findall(f"{table.removesuffix('Table')}Transaction"):
            transactions.append(
                {
                    "kind": kind,
                    "security": _val(txn, "securityTitle"),
                    "date": _val(txn, "transactionDate"),
                    "code": _val(txn, "transactionCoding/transactionCode"),
                    "shares": _val(txn, "transactionAmounts/transactionShares"),
                    "price": _val(txn, "transactionAmounts/transactionPricePerShare"),
                    "acquired_disposed": _val(
                        txn, "transactionAmounts/transactionAcquiredDisposedCode"
                    ),
                    "shares_owned_after": _val(
                        txn, "postTransactionAmounts/sharesOwnedFollowingTransaction"
                    ),
                    "ownership": _val(txn, "ownershipNature/directOrIndirectOwnership"),
                }
            )

    def _flag(tag: str) -> bool:
        return relationship is not None and relationship.findtext(tag) == "true"

    roles = []
    if _flag("isDirector"):
        roles.append("director")
    if _flag("isOfficer"):
        title = (
            relationship.findtext("officerTitle") if relationship is not None else None
        )
        roles.append(f"officer ({title})" if title else "officer")
    if _flag("isTenPercentOwner"):
        roles.append("10% owner")
    if _flag("isOther"):
        roles.append("other")

    return {
        "issuer": root.findtext("issuer/issuerName"),
        "ticker": root.findtext("issuer/issuerTradingSymbol"),
        "owner": (
            owner_el.findtext("reportingOwnerId/rptOwnerName")
            if owner_el is not None
            else None
        ),
        "position": ", ".join(roles) if roles else "unknown",
        "transactions": transactions,
    }
