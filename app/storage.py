import asyncio
import logging
import os

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

load_dotenv()

AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME", "receipts")

if not AZURE_STORAGE_CONNECTION_STRING:
    raise ValueError("ERROR: AZURE_STORAGE_CONNECTION_STRING not found in .env!")

blob_service_client = BlobServiceClient.from_connection_string(
    AZURE_STORAGE_CONNECTION_STRING
)


def ensure_container_exists():
    """Ensure Azure Blob Storage container exists, create if not."""
    try:
        container_client = blob_service_client.get_container_client(
            AZURE_CONTAINER_NAME
        )
        container_client.create_container()
        logging.info(f"Container '{AZURE_CONTAINER_NAME}' created successfully.")
    except ResourceExistsError:
        logging.info(f"Container '{AZURE_CONTAINER_NAME}' already exists.")
    except Exception as e:
        logging.error(f"Error creating container: {e}")


async def upload_receipt_photo(blob_name: str, data: bytes) -> None:
    """Uploads a receipt photo to Azure Blob Storage, overwriting an existing blob with the same name."""
    blob_client = blob_service_client.get_blob_client(container=AZURE_CONTAINER_NAME, blob=blob_name)
    await asyncio.to_thread(blob_client.upload_blob, data, overwrite=True)


async def delete_receipt_photo(blob_name: str) -> None:
    """Deletes a receipt photo from Azure Blob Storage; failures are logged, not raised."""
    try:
        blob_client = blob_service_client.get_blob_client(container=AZURE_CONTAINER_NAME, blob=blob_name)
        await asyncio.to_thread(blob_client.delete_blob)
    except ResourceNotFoundError:
        logging.warning(f"Receipt photo already missing in storage: {blob_name}")
    except Exception:
        logging.exception(f"Failed to delete receipt photo from storage: {blob_name}")
