"""Complete Drive listings and checksum-validated atomic downloads."""
import os
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from artifacts import atomic_output, digest

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']


def get_service(interactive=False):
    token = Path(os.getenv('GOOGLE_TOKEN_PATH', 'creds/token.json'))
    if token.suffix == '.pickle':
        raise ValueError('Reauthorize to token.json; daemon will not unpickle executable credentials')
    creds = Credentials.from_authorized_user_file(token, SCOPES) if token.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif interactive:
            flow = InstalledAppFlow.from_client_secrets_file(os.environ['GOOGLE_CREDS_PATH'], SCOPES)
            creds = flow.run_local_server(port=0)
        else:
            raise RuntimeError('Drive authorization missing/expired: run drive_sync.py --authorize interactively')
        with atomic_output(token) as output:
            output.write(creds.to_json())
        token.chmod(0o600)
    return build('drive', 'v3', credentials=creds, cache_discovery=False)


def _escape(value):
    return value.replace('\\', '\\\\').replace("'", "\\'")


def _list(service, query, fields):
    items, token = [], None
    while True:
        kwargs = dict(q=query, spaces='drive', fields=f'nextPageToken,files({fields})', pageSize=1000)
        if token:
            kwargs['pageToken'] = token
        result = service.files().list(**kwargs).execute(num_retries=3)
        items.extend(result.get('files', []))
        token = result.get('nextPageToken')
        if not token:
            return items


def get_folder_id_by_name(service, folder_name):
    items = _list(service, f"name = '{_escape(folder_name)}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false", 'id,name')
    if len(items) != 1:
        raise ValueError('Folder name is absent/ambiguous; configure DRIVE_FOLDER_ID')
    return items[0]['id']


def list_new_files(service, folder_id):
    files = _list(service, f"'{_escape(folder_id)}' in parents and trashed=false", 'id,name,modifiedTime,md5Checksum,size')
    return [f for f in files if f.get('name', '').lower().endswith(('.dslog', '.dsevents'))]


def download_file(service, file_id, dest_path, metadata=None):
    request = service.files().get_media(fileId=file_id)
    with atomic_output(dest_path, 'w+b') as output:
        downloader = MediaIoBaseDownload(output, request)
        done = False
        while not done:
            _, done = downloader.next_chunk(num_retries=3)
        output.flush()
        if metadata and metadata.get('size') is not None and output.tell() != int(metadata['size']):
            raise OSError('Drive download size mismatch')
        if metadata and metadata.get('md5Checksum'):
            output.seek(0)
            import hashlib
            checksum = hashlib.md5()
            for chunk in iter(lambda: output.read(1024 * 1024), b''):
                checksum.update(chunk)
            if checksum.hexdigest() != metadata['md5Checksum']:
                raise OSError('Drive download checksum mismatch')
    return dest_path


if __name__ == '__main__':
    import argparse
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument('--authorize', action='store_true')
    args = parser.parse_args()
    get_service(interactive=args.authorize)
