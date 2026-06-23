from celery import shared_task

from .services.google_drive_service import drive_service


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def create_drive_folder_task(self, folder_name, company_name=None):
    return drive_service.create_bank_folder_structure(folder_name, company_name=company_name)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def upload_to_drive_task(self, file_bytes, file_name, folder_id, mime_type):
    class InMemoryFile:
        def __init__(self, data):
            self._data = data

        def read(self):
            return self._data

    file_obj = InMemoryFile(file_bytes)
    return drive_service.upload_file(
        file_obj=file_obj,
        file_name=file_name,
        folder_id=folder_id,
        mime_type=mime_type,
    )

