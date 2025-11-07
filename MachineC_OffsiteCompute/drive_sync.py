
from __future__ import print_function
import os, io, time
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
from dotenv import load_dotenv

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

def get_service():
    creds = None
    # Load sensitive paths from .env
    TOKEN_PATH = os.getenv('GOOGLE_TOKEN_PATH', 'creds/token.pickle')
    CREDS_PATH = os.getenv('GOOGLE_CREDS_PATH', 'creds/credentials.json')
    try:
        if os.path.exists(TOKEN_PATH):
            with open(TOKEN_PATH, 'rb') as token:
                creds = pickle.load(token)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDS_PATH, SCOPES)
                # Use open_browser=True to force browser launch
                creds = flow.run_local_server(port=0, open_browser=True)
            with open(TOKEN_PATH, 'wb') as token:
                pickle.dump(creds, token)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"[!] Google Drive authentication failed: {e}")
        raise

def get_folder_id_by_name(service, folder_name):
    """Return the first folder ID matching folder_name. Returns None if not found.

    Note: If multiple folders share the same name this returns the first match.
    """
    try:
        # Search for folders with the given name (not trashed)
        query = (
            f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder'"
            " and trashed = false"
        )
        resp = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        items = resp.get('files', [])
        if not items:
            print(f"[!] No Drive folder named '{folder_name}' found.")
            return None
        # Return the first match
        folder_id = items[0]['id']
        print(f"[+] Resolved folder '{folder_name}' to ID: {folder_id}")
        return folder_id
    except Exception as e:
        print(f"[!] Error resolving folder name '{folder_name}': {e}")
        return None

def list_new_files(service, folder_id):
    results = service.files().list(
        q=f"'{folder_id}' in parents and (name contains '.dslog' or name contains '.dsevents')",
        spaces='drive',
        fields='files(id, name, modifiedTime)',
    ).execute()
    return results.get('files', [])

def download_file(service, file_id, dest_path):
    request = service.files().get_media(fileId=file_id)
    with io.FileIO(dest_path, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
    return dest_path

# --- TEST BLOCK ---
if __name__ == "__main__":
    print("[TEST] Authenticating with Google Drive...")
    service = get_service()
    folder_id = os.getenv('TEST_DRIVE_FOLDER_ID', 'YOUR_DRIVE_FOLDER_ID')
    print(f"[TEST] Listing files in folder: {folder_id}")
    try:
        files = list_new_files(service, folder_id)
        print("[TEST] Files found:")
        for f in files:
            print(f"  - {f['name']}")
    except Exception as e:
        print(f"[!] Error listing files: {e}")
