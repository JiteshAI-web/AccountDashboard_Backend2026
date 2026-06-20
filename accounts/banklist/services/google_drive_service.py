from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from django.conf import settings
import calendar
from datetime import datetime
from googleapiclient.http import MediaIoBaseUpload
import io


class GoogleDriveService:
    """Service for managing Google Drive folders using OAuth"""

    SCOPES = ['https://www.googleapis.com/auth/drive']

    def __init__(self):
        """Initialize Google Drive service with OAuth"""
        try:
            # Create credentials from refresh token
            self.creds = Credentials(
                token=None,
                refresh_token=settings.GOOGLE_REFRESH_TOKEN,
                token_uri='https://oauth2.googleapis.com/token',
                client_id=settings.GOOGLE_CLIENT_ID,
                client_secret=settings.GOOGLE_CLIENT_SECRET,
                scopes=self.SCOPES
            )

            # Refresh the access token
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())

            self.service = build('drive', 'v3', credentials=self.creds)
            print("✅ Google Drive service initialized")

        except Exception as e:
            print(f"❌ Failed to initialize Google Drive service: {e}")
            self.service = None

    def create_folder(self, folder_name, parent_folder_id=None):
        """
        Create a folder in Google Drive

        Args:
            folder_name: Name of the folder
            parent_folder_id: ID of parent folder (optional)

        Returns:
            Folder ID if successful, None otherwise
        """
        if not self.service:
            return None

        try:
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }

            if parent_folder_id:
                file_metadata['parents'] = [parent_folder_id]

            folder = self.service.files().create(
                body=file_metadata,
                fields='id, name, webViewLink'
            ).execute()

            print(f"✅ Created folder: {folder_name} (ID: {folder.get('id')})")
            return folder.get('id')

        except HttpError as error:
            print(f"❌ Error creating folder {folder_name}: {error}")
            return None

    def folder_exists(self, folder_name, parent_folder_id=None):
        """
        Check if folder exists

        Args:
            folder_name: Name of the folder
            parent_folder_id: ID of parent folder (optional)

        Returns:
            Folder ID if exists, None otherwise
        """
        if not self.service:
            return None

        try:
            query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"

            if parent_folder_id:
                query += f" and '{parent_folder_id}' in parents"

            response = self.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name)',
                pageSize=1
            ).execute()

            files = response.get('files', [])

            if files:
                return files[0].get('id')
            return None

        except HttpError as error:
            print(f"❌ Error checking folder existence: {error}")
            return None

    def create_bank_folder_structure(self, bank_name, current_year=None):
        """
        Create folder structure for a bank.

        Current structure (fast — single subfolder):
        Bank Name/
          └── Statement/

        All uploaded files (PDF, Excel, images, etc.) go into this single
        'Statement' subfolder, regardless of which month they belong to.

        Args:
            bank_name: Name of the bank
            current_year: Unused now, kept for backward compatibility with
                          callers; will matter again if month-folder logic
                          below is restored.

        Returns:
            dict with folder IDs and status
        """
        if not self.service:
            return {
                'success': False,
                'message': 'Google Drive service not initialized',
                'bank_folder_id': None,
                'statement_folder_id': None,
                'month_folders': []
            }

        try:
            # Get parent folder ID from settings
            parent_folder_id = settings.GOOGLE_DRIVE_PARENT_FOLDER_ID

            # Step 1: Create/Get bank folder
            bank_folder_id = self.folder_exists(bank_name, parent_folder_id)

            if not bank_folder_id:
                bank_folder_id = self.create_folder(bank_name, parent_folder_id)
                print(f"📁 Created new bank folder: {bank_name}")
            else:
                print(f"📁 Bank folder already exists: {bank_name}")

            if not bank_folder_id:
                return {
                    'success': False,
                    'message': 'Failed to create bank folder',
                    'bank_folder_id': None,
                    'statement_folder_id': None,
                    'month_folders': []
                }

            # Step 2: Create single "Statement" subfolder (fast path)
            statement_folder_name = "Statement"
            statement_folder_id = self.folder_exists(statement_folder_name, bank_folder_id)

            if not statement_folder_id:
                statement_folder_id = self.create_folder(statement_folder_name, bank_folder_id)
                print(f"📁 Created Statement folder for: {bank_name}")
            else:
                print(f"📁 Statement folder already exists for: {bank_name}")

            if not statement_folder_id:
                return {
                    'success': False,
                    'message': 'Failed to create Statement folder',
                    'bank_folder_id': bank_folder_id,
                    'statement_folder_id': None,
                    'month_folders': []
                }

            # ------------------------------------------------------------------
            # OLD LOGIC (commented out for now — creates 12 month subfolders).
            # Restore this block (and remove the single-Statement-folder code
            # above) if per-month folders are needed again in the future.
            # ------------------------------------------------------------------
            # if current_year is None:
            #     current_year = datetime.now().year
            #
            # month_folders = []
            #
            # for month in range(1, 13):
            #     month_name = calendar.month_name[month]
            #     folder_name = f"{current_year}-{month:02d}-{month_name}"
            #
            #     # Check if month folder exists
            #     month_folder_id = self.folder_exists(folder_name, bank_folder_id)
            #
            #     if not month_folder_id:
            #         month_folder_id = self.create_folder(folder_name, bank_folder_id)
            #     else:
            #         print(f"📁 Month folder already exists: {folder_name}")
            #
            #     if month_folder_id:
            #         month_folders.append({
            #             'month': month,
            #             'name': folder_name,
            #             'folder_id': month_folder_id
            #         })
            # ------------------------------------------------------------------

            # Get bank folder link
            bank_folder = self.service.files().get(
                fileId=bank_folder_id,
                fields='webViewLink'
            ).execute()

            # Get statement folder link
            statement_folder = self.service.files().get(
                fileId=statement_folder_id,
                fields='webViewLink'
            ).execute()

            return {
                'success': True,
                'message': f'Successfully created folder structure for {bank_name}',
                'bank_folder_id': bank_folder_id,
                'bank_folder_link': bank_folder.get('webViewLink'),
                'statement_folder_id': statement_folder_id,
                'statement_folder_link': statement_folder.get('webViewLink'),
                'month_folders': [],  # kept for response-shape compatibility
                'total_folders_created': 2  # bank folder + Statement folder
            }

        except Exception as error:
            print(f"❌ Error creating bank folder structure: {error}")
            return {
                'success': False,
                'message': str(error),
                'bank_folder_id': None,
                'statement_folder_id': None,
                'month_folders': []
            }

    def get_folder_link(self, folder_id):
        """Get web view link for a folder"""
        if not self.service:
            return None

        try:
            folder = self.service.files().get(
                fileId=folder_id,
                fields='webViewLink'
            ).execute()
            return folder.get('webViewLink')
        except HttpError as error:
            print(f"❌ Error getting folder link: {error}")
            return None

    def upload_file(self, file_obj, file_name, folder_id, mime_type):
        """
        Upload a file to a specific Drive folder

        Args:
            file_obj: file object (from request.FILES)
            file_name: name to save as
            folder_id: target Drive folder ID
            mime_type: file's MIME type

        Returns:
            dict with file ID and link, or None on failure
        """
        if not self.service:
            return None

        try:
            file_metadata = {
                'name': file_name,
                'parents': [folder_id]
            }

            media = MediaIoBaseUpload(
                io.BytesIO(file_obj.read()),
                mimetype=mime_type,
                resumable=True
            )

            uploaded_file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, webViewLink'
            ).execute()

            print(f"✅ Uploaded file: {file_name} (ID: {uploaded_file.get('id')})")
            return {
                'file_id': uploaded_file.get('id'),
                'file_name': uploaded_file.get('name'),
                'file_link': uploaded_file.get('webViewLink')
            }

        except HttpError as error:
            print(f"❌ Error uploading file {file_name}: {error}")
            return None


# Singleton instance
drive_service = GoogleDriveService()