from __future__ import annotations

from datetime import date

import httpx
import respx

from heimdall._contracts import FetchRequest
from heimdall.providers.sec import FORM13F_HOLDINGS, SecProvider
from heimdall.providers.sec.form13f import parse_form_index

_CIK = "0001067983"
_SUBMISSIONS = f"https://data.sec.gov/submissions/CIK{_CIK}.json"
_NEW, _OLD = "0000950123-26-011111", "0000950123-22-002222"


def _base(acc: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/1067983/{acc.replace('-', '')}"


def _table(shares: int, value: int, put: str = "") -> str:
    put_el = f"<putCall>{put}</putCall>" if put else ""
    return f"""<?xml version="1.0"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip><value>{value}</value>
    <shrsOrPrnAmt><sshPrnamt>{shares}</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    {put_el}
  </infoTable>
</informationTable>"""


def _mock(router: respx.MockRouter) -> None:
    router.get(_SUBMISSIONS).mock(
        return_value=httpx.Response(
            200,
            json={
                "filings": {
                    "recent": {
                        "accessionNumber": [_NEW, "0000950123-26-033333", _OLD],
                        "filingDate": ["2026-08-14", "2026-08-20", "2022-11-14"],
                        "reportDate": ["2026-06-30", "2026-06-30", "2022-09-30"],
                        "form": ["13F-HR", "13F-HR/A", "13F-HR"],
                    }
                }
            },
        )
    )
    for acc, xml in ((_NEW, _table(300, 60_000_000)), (_OLD, _table(100, 15_000))):
        router.get(f"{_base(acc)}/index.json").mock(
            return_value=httpx.Response(
                200,
                json={
                    "directory": {
                        "item": [
                            {"name": "primary_doc.xml", "size": "9000"},
                            {"name": "infotable.xml", "size": "20000"},
                        ]
                    }
                },
            )
        )
        router.get(f"{_base(acc)}/infotable.xml").mock(
            return_value=httpx.Response(200, text=xml)
        )


@respx.mock
def test_13f_rows_skip_amendments_and_scale_old_values_to_dollars() -> None:
    _mock(respx)
    result = SecProvider(user_agent="t t@x.com").fetch(
        FetchRequest(_CIK.lstrip("0"), kind="13f_holdings", params={"limit": 10})
    )
    FORM13F_HOLDINGS.validate(result.frame)
    rows = result.frame.to_dicts()
    assert [r["accession_number"] for r in rows] == [_OLD, _NEW]
    assert rows[0]["value"] == 15_000_000  # thousands before 2023
    assert rows[1]["value"] == 60_000_000
    assert rows[1]["period"] == date(2026, 6, 30) and rows[1]["cusip"] == "037833100"


def test_form_index_keeps_only_originals() -> None:
    text = (
        "Form Type   Company Name                                                  CIK         Date Filed  File Name\n"  # noqa: E501
        "-----------------------------------------------------------------------------\n"
        "13F-HR          BERKSHIRE HATHAWAY INC                                        1067983     2026-08-14  edgar/data/1067983/x.txt\n"  # noqa: E501
        "13F-HR/A        BERKSHIRE HATHAWAY INC                                        1067983     2026-08-20  edgar/data/1067983/y.txt\n"  # noqa: E501
    )
    assert parse_form_index(text) == [
        {
            "cik": "0001067983",
            "name": "BERKSHIRE HATHAWAY INC",
            "filing_date": "2026-08-14",
        }
    ]
