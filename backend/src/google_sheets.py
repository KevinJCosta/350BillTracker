from __future__ import print_function

import json
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from sqlalchemy.orm import selectinload

from . import settings, twitter
from .bill.models import CityBill
from .models import UUID
from .person.models import CouncilMember, OfficeContact, Person
from .sponsorship.models import CitySponsorship

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

COLUMN_TITLES = [
    "",
    "Name",
    "Email",
    "Party",
    "Borough",
    "District Phone",
    "Legislative Phone",
    "Twitter",
    "Twitter search\nNote: Due to a Twitter bug, the Twitter search sometimes displays 0 results even when there should be should be matching tweets. Refreshing the Twitter page often fixes this.",
    "Staffers",
]
COLUMN_TITLE_SET = set(COLUMN_TITLES)

BOROUGH_SORT_TABLE = {
    "Brooklyn": 0,
    "Manhattan": 1,
    "Manhattan and Bronx": 2,
    "Queens": 3,
    "Bronx": 4,
    "Staten Island": 5,
}
BOROUGH_DEFAULT_SORT = 6

# Width in pixels for each column. We can't dynamically set it to match the,
# contents via the API, so instead we just hardcode them as best we can.
COLUMN_WIDTHS = [
    150,
    150,
    200,
    50,
    100,
    100,
    150,
    200,
    250,
    250,
]


# TODO: Make this a dataclass
class Cell:
    value = None  # str
    link_url = None  # str
    bold = False

    def __init__(self, value, *, link_url=None, bold=False):
        self.value = value
        self.link_url = link_url
        self.bold = bold


@dataclass
class PowerHourImportData:
    """Data about a previous power hour that will be copied into a new sheet."""

    extra_column_titles: List[str]
    column_data_by_legislator_id: Dict[id, Dict[str, str]]
    import_messages: List[str]


def _get_google_credentials():
    return Credentials.from_service_account_info(
        json.loads(settings.GOOGLE_CREDENTIALS)
    )


def _get_sheets_service(credentials):
    return build("sheets", "v4", credentials=credentials)


def _get_drive_service(credentials):
    return build("drive", "v3", credentials=credentials)


def _create_cell_data(cell):
    text_format_runs = None
    if cell.link_url:
        text_format_runs = [
            {"startIndex": 0, "format": {"link": {"uri": cell.link_url}}}
        ]
    return {
        "textFormatRuns": text_format_runs,
        "userEnteredValue": {"stringValue": str(cell.value)},
        "userEnteredFormat": {
            "wrapStrategy": "WRAP",
            "textFormat": {"bold": cell.bold},
        },
    }


def _create_row_data(cells):
    return {"values": [_create_cell_data(cell) for cell in cells]}


def _get_staffer_display_string(staffer: Person):
    contact_methods = [c.phone for c in staffer.office_contacts] + [
        staffer.email,
        staffer.display_twitter,
    ]
    contact_methods = [c for c in contact_methods if c]
    contact_string = ", ".join(contact_methods)
    if not contact_string:
        contact_string = "No contact info"
    title_string = f"{staffer.title} - " if staffer.title else ""
    return f"{title_string}{staffer.name} ({contact_string})"


def _create_legislator_row(
    council_member: CouncilMember,
    city_bill: CityBill,
    import_data: Optional[PowerHourImportData],
    is_lead_sponsor: bool = False,
):
    staffer_strings = [
        _get_staffer_display_string(s)
        for s in council_member.person.staffer_persons
    ]
    staffer_text = "\n\n".join(staffer_strings)

    twitter_search_url = twitter.get_bill_twitter_search_url(
        city_bill.bill, council_member.person
    )

    legislative_phone = ", ".join(
        (
            c.phone
            for c in council_member.person.office_contacts
            if c.phone
            and c.type == OfficeContact.OfficeContactType.CENTRAL_OFFICE
        )
    )
    district_phone = ", ".join(
        (
            c.phone
            for c in council_member.person.office_contacts
            if c.phone
            and c.type == OfficeContact.OfficeContactType.DISTRICT_OFFICE
        )
    )
    cells = [
        Cell(""),
        Cell(
            _get_sponsor_name_text(council_member.person.name, is_lead_sponsor)
        ),
        Cell(council_member.person.email),
        Cell(council_member.person.party),
        Cell(council_member.borough),
        Cell(district_phone),
        Cell(legislative_phone),
        Cell(
            council_member.person.display_twitter or "",
            link_url=council_member.person.twitter_url,
        ),
        Cell(
            "Relevant tweets" if twitter_search_url else "",
            link_url=twitter_search_url,
        ),
        Cell(staffer_text),
    ]
    if import_data:
        legislator_data = import_data.column_data_by_legislator_id.get(
            council_member.person_id
        )
        if legislator_data is not None:
            for extra_column in import_data.extra_column_titles:
                text = legislator_data.get(extra_column, "")
                cells.append(Cell(text))
        else:
            logging.warning(
                f"No legislator data for {council_member.person.name} in import data"
            )
    return _create_row_data(cells)


def _create_title_row_data(raw_values):
    cells = [Cell(value, bold=True) for value in raw_values]
    return _create_row_data(cells)


def _create_phone_bank_spreadsheet_data(
    city_bill: CityBill,
    sheet_title: str,
    sponsorships: List[CitySponsorship],
    non_sponsors: List[CitySponsorship],
    import_data: Optional[PowerHourImportData],
):
    """Generates the full body payload that the Sheets API requires for a
    phone bank spreadsheet."""

    extra_titles = import_data.extra_column_titles if import_data else []
    rows = [
        _create_title_row_data(
            COLUMN_TITLES + extra_titles,
        ),
        _create_title_row_data(["NON-SPONSORS"]),
    ]
    for non_sponsor in non_sponsors:
        rows.append(
            _create_legislator_row(non_sponsor, city_bill, import_data)
        )

    rows.append(_create_title_row_data([]))
    rows.append(_create_title_row_data(["SPONSORS"]))

    for sponsorship in sponsorships:
        rows.append(
            _create_legislator_row(
                sponsorship.council_member,
                city_bill,
                import_data,
                sponsorship.sponsor_sequence == 0,
            )
        )

    column_metadata = [{"pixelSize": size} for size in COLUMN_WIDTHS]
    return {
        "properties": {"title": sheet_title},
        "sheets": [
            {
                "properties": {"gridProperties": {"frozenRowCount": 1}},
                "data": {"rowData": rows, "columnMetadata": column_metadata},
            }
        ],
    }


def get_sort_key(council_member):
    sort_key = BOROUGH_SORT_TABLE.get(
        council_member.borough, BOROUGH_DEFAULT_SORT
    )
    return (sort_key, council_member.person.name)


def _get_sponsor_name_text(legislator_name, is_lead):
    return f"{legislator_name}{' (lead)' if is_lead else ''}"


def create_power_hour(
    bill_id: UUID, title: str, old_spreadsheet_to_import: str
) -> Tuple[Dict, List[str]]:
    """Creates a spreadsheet that's a template to run a phone bank
    for a specific bill, based on its current sponsors. The sheet will be
    owned by a robot Google account and will be made publicly editable by
    anyone with the link."""
    logging.info(
        f"Creating new power hour titled {title}, importing old spreadsheet {old_spreadsheet_to_import}"
    )
    city_bill = (
        CityBill.query.filter_by(bill_id=bill_id)
        .options(
            selectinload(CityBill.sponsorships),
        )
        .one()
    )

    sponsorships = city_bill.sponsorships
    sponsorships = sorted(
        sponsorships, key=lambda s: get_sort_key(s.council_member)
    )

    sponsor_ids = [s.council_member_id for s in sponsorships]
    non_sponsors = CouncilMember.query.filter(
        CouncilMember.person_id.not_in(sponsor_ids)
    ).all()
    non_sponsors = sorted(non_sponsors, key=get_sort_key)

    if old_spreadsheet_to_import:
        import_data = _extract_data_from_previous_power_hour(
            old_spreadsheet_to_import
        )
    else:
        import_data = None

    spreadsheet_data = _create_phone_bank_spreadsheet_data(
        city_bill, title, sponsorships, non_sponsors, import_data
    )

    google_credentials = _get_google_credentials()
    sheets_service = _get_sheets_service(google_credentials)

    spreadsheet_result = (
        sheets_service.spreadsheets().create(body=spreadsheet_data).execute()
    )

    # That sheet is initially only accessible to our robot account, so make it public.
    drive_service = _get_drive_service(google_credentials)
    user_permission = {
        "type": "anyone",
        "role": "writer",
    }
    drive_service.permissions().create(
        fileId=spreadsheet_result["spreadsheetId"],
        body=user_permission,
        fields="id",
    ).execute()

    output_messages = import_data.import_messages if import_data else []
    output_messages.append("Spreadsheet was created")

    return (spreadsheet_result, output_messages)


def _get_raw_cell_data(spreadsheet):
    """Takes in a deeply nested Google Spreadsheet object and simplifies it into a
    2D array of cell data strings."""
    row_data = spreadsheet["sheets"][0]["data"][0]["rowData"]

    def get_data(cell):
        if "formattedValue" in cell:
            return cell["formattedValue"]
        return ""

    def get_columns(row):
        if "values" in row:
            return [get_data(cell) for cell in row["values"]]
        return []

    return [get_columns(row) for row in row_data]


def _extract_data_from_previous_spreadsheet(
    spreadsheet_cells,
) -> PowerHourImportData:
    import_messages = []

    if not spreadsheet_cells:
        return PowerHourImportData(None, None, ["Old spreadsheet was empty"])

    title_row = spreadsheet_cells[0]
    data_rows = spreadsheet_cells[1:]

    # Look through the column titles, pick out the Name column and any other
    # columns that aren't part of the standard set. We'll copy those over.
    extra_column_title_indices: Tuple[int, str] = []
    name_column_index = None
    for i, title in enumerate(title_row):
        if title not in COLUMN_TITLE_SET:
            extra_column_title_indices.append((i, title))
        elif title == "Name":
            name_column_index = i

    if name_column_index is None:
        import_messages.append(
            "Could not find a 'Name' column at the top of the old spreadsheet, so nothing was copied over"
        )
        logging.warning(
            f"Could not find Name column in spreadsheet. Title columns were {','.join(title_row)}"
        )
        return PowerHourImportData(None, None, import_messages)

    extra_columns_by_council_member_name: Dict[str, Dict[str, str]] = {}
    for row in data_rows:
        # Ignore empty rows, which may have fewer cells in the array
        if (
            name_column_index < len(row)
            and (name := row[name_column_index]) is not None
        ):
            legislator_extra_columns: Dict[str, str] = {}
            for index, extra_column_title in extra_column_title_indices:
                if index < len(row):
                    legislator_extra_columns[extra_column_title] = row[index]
            extra_columns_by_council_member_name[
                name
            ] = legislator_extra_columns

    titles = [column[1] for column in extra_column_title_indices]
    if titles:
        for title in titles:
            import_messages.append(f"Copied column '{title}' to new sheet")
    else:
        import_messages.append(
            "Did not find any extra columns in the old sheet to import"
        )

    # Now rekey by legislator ID
    council_members = CouncilMember.query.all()
    column_data_by_council_member_id: Dict[UUID, Dict[str, str]] = {}
    for council_member in council_members:
        council_member_data = extra_columns_by_council_member_name.get(
            council_member.person.name
        )
        if council_member_data is None:
            council_member_data = extra_columns_by_council_member_name.get(
                _get_sponsor_name_text(council_member.person.name, True)
            )
        if council_member_data is not None:
            column_data_by_council_member_id[
                council_member.person_id
            ] = council_member_data
        else:
            import_messages.append(
                f"Could not find {council_member.person.name} under the Name column in the old sheet. Make sure the name matches exactly."
            )

    return PowerHourImportData(
        extra_column_titles=titles,
        column_data_by_legislator_id=column_data_by_council_member_id,
        import_messages=import_messages,
    )


def _extract_data_from_previous_power_hour(
    spreadsheet_id,
) -> Optional[PowerHourImportData]:
    """Reads cells from the spreadsheet of a previous power hour and extracts
    some data that should be copied into the next power hour, to preserve context
    for new callers. It follows these rules:
      * First it seeks to find the row for each legislator. It searches for a Name
        column, and then does an exact string match of the legislator name within
        that column.
      * For each legislator, it imports data for all *extra columns* that aren't one
        of the autogenerated ones. In other words, columns that were added when
        customizing the spreadsheet after it was generated.
    """
    google_credentials = _get_google_credentials()
    sheets_service = _get_sheets_service(google_credentials)

    # TODO: Use a field mask instead of includeGridData=true to return less data
    spreadsheet = (
        sheets_service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, includeGridData=True)
        .execute()
    )

    raw_cell_data = _get_raw_cell_data(spreadsheet)
    return _extract_data_from_previous_spreadsheet(raw_cell_data)
