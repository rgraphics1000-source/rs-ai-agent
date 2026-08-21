import time
from typing import Optional, Dict, Any, Tuple
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.google_integration.oauth_service import get_workspace_credentials
from app.database import get_google_connection, update_google_master_ids

def get_drive_client(workspace_id: int = 1):
    """Builds and returns the authenticated Google Drive API client."""
    creds = get_workspace_credentials(workspace_id=workspace_id)
    if not creds:
        raise PermissionError(f"Workspace {workspace_id} does not have an active Google connection.")
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def verify_file_accessible(workspace_id: int, file_id: str) -> Tuple[bool, dict]:
    """
    Verifies that a Google Form or File exists and is accessible.
    Returns (is_accessible, metadata_dict).
    """
    if not file_id:
        return False, {"error": "File ID is empty"}
    try:
        drive = get_drive_client(workspace_id=workspace_id)
        file_meta = drive.files().get(
            fileId=str(file_id).strip(),
            fields="id, name, mimeType, webViewLink, parents, owners, trashed"
        ).execute()
        
        if file_meta.get("trashed"):
            return False, {"error": "File is in Google Drive trash bin."}
            
        return True, file_meta
    except HttpError as err:
        status_code = err.resp.status if hasattr(err, "resp") else 500
        print(f"[Drive verify_file_accessible HttpError]: {status_code} - {err}")
        return False, {"error": f"Google API Error {status_code}: {err.reason if hasattr(err, 'reason') else str(err)}"}
    except Exception as ex:
        print(f"[Drive verify_file_accessible Exception]: {ex}")
        return False, {"error": str(ex)}

def get_or_create_workspace_root_folder(workspace_id: int, workspace_name: str = "RS Graphics") -> str:
    """Creates or retrieves the main root folder for the workspace in Google Drive."""
    conn = get_google_connection(workspace_id=workspace_id)
    existing_folder_id = conn.get("drive_root_folder_id") if conn else None
    
    if existing_folder_id:
        valid, meta = verify_file_accessible(workspace_id, existing_folder_id)
        if valid and meta.get("mimeType") == "application/vnd.google-apps.folder":
            return existing_folder_id

    drive = get_drive_client(workspace_id=workspace_id)
    folder_name = f"{workspace_name} - Forms & ID Cards (Workspace {workspace_id})"
    
    # Search if folder with this name already exists
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    res = drive.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    files = res.get("files", [])
    if files:
        folder_id = files[0]["id"]
        update_google_master_ids(workspace_id=workspace_id, drive_root_folder_id=folder_id)
        return folder_id

    # Create new root folder
    folder_metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder"
    }
    folder = drive.files().create(body=folder_metadata, fields="id, name").execute()
    folder_id = folder.get("id")
    update_google_master_ids(workspace_id=workspace_id, drive_root_folder_id=folder_id)
    return folder_id

def get_or_create_institution_folder(
    workspace_id: int,
    institution_name: str,
    institution_mobile: str = None,
    parent_folder_id: str = None
) -> str:
    """Creates or retrieves a dedicated subfolder for the specific institution with mobile identifier."""
    drive = get_drive_client(workspace_id=workspace_id)
    
    if not parent_folder_id:
        parent_folder_id = get_or_create_workspace_root_folder(workspace_id=workspace_id)

    clean_name = str(institution_name).strip()
    if institution_mobile:
        from app.database import normalize_bd_mobile
        canonical = normalize_bd_mobile(institution_mobile)
        folder_name = f"{clean_name} - {canonical}" if canonical else clean_name
    else:
        folder_name = clean_name

    query = f"name = '{folder_name}' and '{parent_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    res = drive.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]

    folder_metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_folder_id]
    }
    folder = drive.files().create(body=folder_metadata, fields="id, name").execute()
    return folder.get("id")

def copy_master_form_file(
    workspace_id: int,
    master_form_id: str,
    new_title: str,
    destination_folder_id: str = None
) -> dict:
    """
    Clones the Master Form using Google Drive API files.copy().
    This preserves the pre-configured File Upload item and Drive upload binding!
    Moves the newly cloned Form into the institution's folder.
    """
    drive = get_drive_client(workspace_id=workspace_id)
    
    # 1. Verify Master Form is accessible
    is_valid, master_meta = verify_file_accessible(workspace_id, master_form_id)
    if not is_valid:
        raise ValueError(f"Master Form ({master_form_id}) is not accessible: {master_meta.get('error')}")

    # 2. Clone the form file
    copy_body = {
        "name": new_title
    }
    if destination_folder_id:
        copy_body["parents"] = [destination_folder_id]

    max_retries = 3
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            cloned_file = drive.files().copy(
                fileId=str(master_form_id).strip(),
                body=copy_body,
                fields="id, name, webViewLink, parents"
            ).execute()
            
            form_id = cloned_file.get("id")
            web_link = cloned_file.get("webViewLink", "")
            
            # Ensure permissions allow responder access if needed
            try:
                drive.permissions().create(
                    fileId=form_id,
                    body={"role": "reader", "type": "anyone"},
                    fields="id"
                ).execute()
            except Exception:
                pass  # Ignore if domain policy already handles responder permissions

            return {
                "success": True,
                "form_id": form_id,
                "title": new_title,
                "drive_link": web_link,
                "folder_id": destination_folder_id
            }
        except HttpError as h_err:
            last_err = h_err
            status = h_err.resp.status if hasattr(h_err, "resp") else 500
            if status in [429, 500, 502, 503, 504] and attempt < max_retries:
                time.sleep(attempt * 2.0)
                continue
            raise h_err
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(attempt * 1.5)
                continue
            raise e

    raise RuntimeError(f"Failed to copy master form after {max_retries} attempts: {last_err}")
