import time
from typing import Optional, Dict, Any, List
from googleapiclient.discovery import build

from app.google_integration.oauth_service import get_workspace_credentials
from app.google_integration.drive_service import get_drive_client

def get_sheets_client(workspace_id: int = 1):
    """Builds and returns the authenticated Google Sheets API client."""
    creds = get_workspace_credentials(workspace_id=workspace_id)
    if not creds:
        raise PermissionError(f"Workspace {workspace_id} does not have an active Google connection.")
    return build("sheets", "v4", credentials=creds, cache_discovery=False)

def create_institution_response_sheet(
    workspace_id: int,
    institution_name: str,
    folder_id: str = None,
    column_headers: List[str] = None
) -> dict:
    """
    Creates a new Google Spreadsheet in the institution's folder for clean record-keeping.
    Initializes column headers for student details and uploaded photos.
    """
    sheets_service = get_sheets_client(workspace_id=workspace_id)
    drive_service = get_drive_client(workspace_id=workspace_id)

    sheet_title = f"{institution_name} - ID Card Responses"
    spreadsheet_body = {
        "properties": {
            "title": sheet_title
        },
        "sheets": [
            {
                "properties": {
                    "title": "Submissions",
                    "gridProperties": {
                        "frozenRowCount": 1
                    }
                }
            }
        ]
    }

    spreadsheet = sheets_service.spreadsheets().create(
        body=spreadsheet_body,
        fields="spreadsheetId,spreadsheetUrl"
    ).execute()

    spreadsheet_id = spreadsheet.get("spreadsheetId")
    sheet_url = spreadsheet.get("spreadsheetUrl")

    # Move spreadsheet into the institution folder
    if folder_id and spreadsheet_id:
        try:
            drive_service.files().update(
                fileId=spreadsheet_id,
                addParents=folder_id,
                fields="id, parents"
            ).execute()
        except Exception as e:
            print(f"[Sheets folder move warning]: {e}")

    # Set up column headers
    default_headers = [
        "Submission ID", "Timestamp", "শিক্ষার্থীর নাম", "পিতার নাম",
        "মাতার নাম", "শ্রেণি / জামাত", "শাখা", "রোল", "আইডি",
        "জন্মতারিখ", "রক্তের গ্রুপ", "মোবাইল নম্বর", "ঠিকানা", "ছবির লিংক (Google Drive)"
    ]
    final_headers = column_headers or default_headers

    try:
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range="Submissions!A1",
            valueInputOption="RAW",
            body={"values": [final_headers]}
        ).execute()
    except Exception as e:
        print(f"[Sheets header write warning]: {e}")

    return {
        "spreadsheet_id": spreadsheet_id,
        "sheet_url": sheet_url,
        "title": sheet_title
    }

def append_submission_row(workspace_id: int, spreadsheet_id: str, row_data: List[Any]) -> bool:
    """Appends a new submission row to the Google Sheet."""
    if not spreadsheet_id or not row_data:
        return False
    try:
        sheets_service = get_sheets_client(workspace_id=workspace_id)
        sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range="Submissions!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row_data]}
        ).execute()
        return True
    except Exception as e:
        print(f"[Sheets append_submission_row Warning]: {e}")
        return False
