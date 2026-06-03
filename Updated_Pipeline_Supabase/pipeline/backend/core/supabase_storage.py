"""
Supabase Storage Manager
=========================

Handles uploading and retrieving files from Supabase Storage buckets.
Provides signed URLs for secure access to private buckets.
"""
# Readability: Backend core: coordinate detection, persistence, and report workflow concerns.

import logging
import os
import time
import json
import threading
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import timedelta, datetime, timezone

import requests
from supabase import create_client, Client

# Protect this step so expected failures can fall back cleanly.
try:
    from postgrest.exceptions import APIError as PostgrestAPIError
except Exception:  # pragma: no cover - optional dependency shape
    # Prepare postgrest apierror for the next step.
    PostgrestAPIError = None

logger = logging.getLogger(__name__)

# When Supabase returns a project-level restriction (HTTP 402 "exceed_egress_quota",
# project paused, billing block), every subsequent upload will fail the same way.
# We short-circuit for this many seconds before re-probing, so the log isn't spammed.
_RESTRICTION_BACKOFF_SECONDS = 300
_GB_BYTES = 1024 ** 3
_EGRESS_STATE_LOCK = threading.Lock()
_DEFAULT_EGRESS_STATE_FILENAME = 'supabase_egress_state.json'


# Section: run the safe float env workflow with clear inputs and outputs.
def _safe_float_env(name: str, default: float = 0.0) -> float:
    # Protect this step so expected failures can fall back cleanly.
    try:
        # Return the prepared result to the caller.
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# Section: group supabase storage manager state and behaviour in one readable unit.
class SupabaseStorageManager:
    """
    Manages file uploads to Supabase Storage and generates signed URLs.
    
    Handles two private buckets:
    - violation-images: Original and annotated images
    - reports: HTML and PDF reports
    """
    
    # Section: run the init workflow with clear inputs and outputs.
    def __init__(
        self,
        supabase_url: str,
        supabase_key: str,
        images_bucket: str = 'violation-images',
        reports_bucket: str = 'reports',
        signed_url_ttl: int = 3600
    ):
        """
        Initialize Supabase Storage Manager.
        
        Args:
            supabase_url: Supabase project URL
            supabase_key: Supabase service role key
            images_bucket: Name of images bucket (default: 'violation-images')
            reports_bucket: Name of reports bucket (default: 'reports')
            signed_url_ttl: TTL for signed URLs in seconds (default: 3600 = 1 hour)
        """
        # Prepare supabase url for the next step.
        self.supabase_url = (supabase_url or '').rstrip('/')
        self.supabase_key = supabase_key
        self.images_bucket = images_bucket
        self.reports_bucket = reports_bucket
        self.signed_url_ttl = signed_url_ttl
        # Circuit breaker: if Supabase returns 402 / project restricted,
        # remember that for a short window so we don't keep retrying.
        self._restricted_until_ts: float = 0.0
        self._restriction_reason: str = ''
        self.egress_budget_bytes = int(
            max(0.0, _safe_float_env('SUPABASE_EGRESS_BUDGET_GB', 0.0)) * _GB_BYTES
        )
        self.egress_state_path = Path(
            os.getenv(
                'SUPABASE_EGRESS_STATE_PATH',
                str(Path('.runtime') / _DEFAULT_EGRESS_STATE_FILENAME)
            )
        )
        self._egress_block_reason: str = ''
        # Prepare precheck exists before upload for the next step.
        self.precheck_exists_before_upload = str(
            os.getenv('SUPABASE_STORAGE_PRECHECK_EXISTS', 'false') or 'false'
        ).strip().lower() in ('1', 'true', 'yes', 'on')
        
        # Initialize Supabase client
        try:
            self.client: Client = create_client(supabase_url, supabase_key)
            logger.info(f"Supabase Storage Manager initialized")
            logger.info(f"Images bucket: {images_bucket}")
            logger.info(f"Reports bucket: {reports_bucket}")
            logger.info(f"Signed URL TTL: {signed_url_ttl}s")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}")
            raise
    
    # =========================================================================
    # UPLOAD OPERATIONS
    # =========================================================================

    def _current_month_key(self) -> str:
        return datetime.now(timezone.utc).strftime('%Y-%m')

    # Section: run the load egress state locked workflow with clear inputs and outputs.
    def _load_egress_state_locked(self) -> Dict[str, Any]:
        default_state = {
            'month': self._current_month_key(),
            'bytes_downloaded': 0,
            'updated_at': None,
        }
        try:
            # Choose the correct branch before the workflow continues.
            if not self.egress_state_path.exists():
                # Return the prepared result to the caller.
                return default_state
            with open(self.egress_state_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
            if not isinstance(state, dict):
                return default_state
            month = str(state.get('month') or default_state['month'])
            if month != default_state['month']:
                return default_state
            # Prepare bytes downloaded for the next step.
            bytes_downloaded = int(state.get('bytes_downloaded') or 0)
            return {
                'month': month,
                'bytes_downloaded': max(0, bytes_downloaded),
                'updated_at': state.get('updated_at'),
            }
        except Exception as e:
            logger.debug(f"Failed to read egress state: {e}")
            return default_state

    # Section: run the save egress state locked workflow with clear inputs and outputs.
    def _save_egress_state_locked(self, state: Dict[str, Any]) -> None:
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Trigger the side effect required for this stage.
            self.egress_state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.egress_state_path.with_suffix('.tmp')
            with open(tmp_path, 'w', encoding='utf-8') as f:
                # Trigger the side effect required for this stage.
                json.dump(state, f, ensure_ascii=False, indent=2)
            tmp_path.replace(self.egress_state_path)
        except Exception as e:
            logger.debug(f"Failed to persist egress state: {e}")

    # Section: run the egress budget active workflow with clear inputs and outputs.
    def _egress_budget_active(self) -> bool:
        # Return the prepared result to the caller.
        return self.egress_budget_bytes > 0

    # Section: run the record egress bytes workflow with clear inputs and outputs.
    def _record_egress_bytes(self, size_bytes: int) -> None:
        if not self._egress_budget_active():
            # Return the prepared result to the caller.
            return
        if size_bytes <= 0:
            return
        with _EGRESS_STATE_LOCK:
            state = self._load_egress_state_locked()
            state['bytes_downloaded'] = int(state.get('bytes_downloaded') or 0) + int(size_bytes)
            state['updated_at'] = datetime.now(timezone.utc).isoformat()
            self._save_egress_state_locked(state)

        # Choose the correct branch before the workflow continues.
        if state['bytes_downloaded'] >= self.egress_budget_bytes:
            # Prepare budget gb for the next step.
            budget_gb = self.egress_budget_bytes / _GB_BYTES
            used_gb = state['bytes_downloaded'] / _GB_BYTES
            self._egress_block_reason = (
                f"Monthly egress budget exceeded ({used_gb:.2f}GB / {budget_gb:.2f}GB)."
            )

    # Section: run the get egress usage workflow with clear inputs and outputs.
    def get_egress_usage(self) -> Dict[str, Any]:
        if not self._egress_budget_active():
            return {
                'month': self._current_month_key(),
                'budget_bytes': 0,
                'bytes_downloaded': 0,
                'remaining_bytes': None,
                'blocked': False,
                'blocked_reason': None,
            }

        # Open the managed resource only for the block that needs it.
        with _EGRESS_STATE_LOCK:
            # Prepare state for the next step.
            state = self._load_egress_state_locked()
            remaining = max(0, self.egress_budget_bytes - int(state.get('bytes_downloaded') or 0))
            blocked = remaining <= 0
            blocked_reason = None
            if blocked:
                # Prepare budget gb for the next step.
                budget_gb = self.egress_budget_bytes / _GB_BYTES
                used_gb = int(state.get('bytes_downloaded') or 0) / _GB_BYTES
                blocked_reason = (
                    f"Monthly egress budget exceeded ({used_gb:.2f}GB / {budget_gb:.2f}GB)."
                )
            # Return the prepared result to the caller.
            return {
                'month': state.get('month') or self._current_month_key(),
                'budget_bytes': self.egress_budget_bytes,
                'bytes_downloaded': int(state.get('bytes_downloaded') or 0),
                'remaining_bytes': remaining,
                'blocked': blocked,
                'blocked_reason': blocked_reason,
            }

    # Section: run the object exists workflow with clear inputs and outputs.
    def _object_exists(self, bucket_name: str, storage_key: str) -> bool:
        """Best-effort check for object presence to keep uploads idempotent."""
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Prepare normalized key for the next step.
            normalized_key = str(storage_key or '').strip().strip('/')
            if not normalized_key:
                # Return the prepared result to the caller.
                return False

            if '/' in normalized_key:
                folder, target_name = normalized_key.rsplit('/', 1)
            else:
                folder, target_name = '', normalized_key

            # Prepare list result for the next step.
            list_result = self.client.storage.from_(bucket_name).list(path=folder)
            if isinstance(list_result, dict):
                # Some supabase-py versions return {'data': [...]} wrappers.
                # Prepare list result for the next step.
                list_result = list_result.get('data')

            if not isinstance(list_result, list):
                return False

            for entry in list_result:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get('name') or '').strip()
                # Choose the correct branch before the workflow continues.
                if name == target_name:
                    # Return the prepared result to the caller.
                    return True
            # Return the prepared result to the caller.
            return False
        except Exception as e:
            logger.debug(f"Storage existence check failed for {bucket_name}/{storage_key}: {e}")
            return False

    # Section: run the restriction active workflow with clear inputs and outputs.
    def _restriction_active(self) -> bool:
        # Return the prepared result to the caller.
        return time.time() < self._restricted_until_ts

    # Section: run the trip restriction workflow with clear inputs and outputs.
    def _trip_restriction(self, reason: str) -> None:
        self._restricted_until_ts = time.time() + _RESTRICTION_BACKOFF_SECONDS
        self._restriction_reason = reason
        logger.error(
            "Supabase project is restricted (%s). Suppressing further upload "
            "attempts for %ds. Visit your Supabase dashboard / billing.",
            reason, _RESTRICTION_BACKOFF_SECONDS,
        )

    # Section: run the probe restriction workflow with clear inputs and outputs.
    def _probe_restriction(self, bucket_name: str, storage_key: str, *, method: str = 'POST') -> bool:
        """After an opaque SDK error, do a direct REST probe to learn the real
        HTTP status. If Supabase responds with 402 / project restriction, trip
        the breaker and return True."""
        # Choose the correct branch before the workflow continues.
        if not self.supabase_url or not self.supabase_key:
            # Return the prepared result to the caller.
            return False
        try:
            url = f"{self.supabase_url}/storage/v1/object/{bucket_name}/{storage_key}"
            method_upper = (method or 'POST').upper()
            headers = {
                'Authorization': f'Bearer {self.supabase_key}',
                'apikey': self.supabase_key,
            }
            data = None
            # Choose the correct branch before the workflow continues.
            if method_upper in ('POST', 'PUT', 'PATCH'):
                # Trigger the side effect required for this stage.
                headers.update({
                    'Content-Type': 'application/octet-stream',
                    'x-upsert': 'true',
                })
                data = b''
            resp = requests.request(
                method_upper,
                url,
                headers=headers,
                data=data,
                timeout=10,
            )
        except Exception as probe_err:
            # Trigger the side effect required for this stage.
            logger.debug(f"Restriction probe failed: {probe_err}")
            return False

        # Prepare body for the next step.
        body = (resp.text or '')[:300]
        if resp.status_code == 402 or 'exceed_egress_quota' in body or 'project is restricted' in body.lower():
            self._trip_restriction(f"HTTP {resp.status_code}: {body}")
            return True
        return False

    # Section: run the upload image workflow with clear inputs and outputs.
    def upload_image(
        self,
        local_path: Path,
        report_id: str,
        filename: str,
        upsert: bool = False
    ) -> Optional[str]:
        """
        Upload an image to the violation-images bucket.
        
        Args:
            local_path: Path to local image file
            report_id: Report ID (used as folder name)
            filename: Filename (e.g., 'original.jpg', 'annotated.jpg')
            upsert: If True, overwrite existing files
        
        Returns:
            Storage key (e.g., 'violation-images/20231205_143022/original.jpg')
            or None if upload failed
        """
        # Choose the correct branch before the workflow continues.
        if not local_path.exists():
            # Trigger the side effect required for this stage.
            logger.error(f"Local file not found: {local_path}")
            return None
        
        storage_key = f"{report_id}/{filename}"
        full_key = f"{self.images_bucket}/{storage_key}"

        if self._restriction_active():
            logger.debug(f"Skip image upload (project restricted): {full_key}")
            return None

        # Choose the correct branch before the workflow continues.
        if self.precheck_exists_before_upload and not upsert and self._object_exists(self.images_bucket, storage_key):
            # Trigger the side effect required for this stage.
            logger.info(f"Image already exists in storage, reusing key: {full_key}")
            return full_key
        
        try:
            with open(local_path, 'rb') as f:
                # Prepare file data for the next step.
                file_data = f.read()
            
            # Upload to Supabase Storage
            result = self.client.storage.from_(self.images_bucket).upload(
                path=storage_key,
                file=file_data,
                file_options={"content-type": "image/jpeg", "upsert": 'true' if upsert else 'false'}
            )
            
            # Trigger the side effect required for this stage.
            logger.info(f"Uploaded image: {full_key}")
            return full_key
            
        except Exception as e:
            # Known supabase-py / storage3 quirk: when the storage backend
            # returns a JSON error body (e.g. 409 "resource already exists",
            # 402 "project restricted"), the SDK's error parser tries
            # response.text on what is already a parsed dict, raising
            # AttributeError("'dict' object has no attribute 'text'").
            # Probe directly to find out the real cause.
            err_text = str(e)
            if "'dict' object has no attribute 'text'" in err_text or 'already exists' in err_text.lower():
                if self._object_exists(self.images_bucket, storage_key):
                    # Trigger the side effect required for this stage.
                    logger.info(
                        f"Image upload reported duplicate; treating as already-uploaded: {full_key}"
                    )
                    return full_key
                # Not a duplicate — find out what Supabase actually returned.
                if self._probe_restriction(self.images_bucket, storage_key):
                    return None
            logger.error(f"Failed to upload image {storage_key}: {e}")
            return None
    
    # Section: run the upload report workflow with clear inputs and outputs.
    def upload_report(
        self,
        local_path: Path,
        report_id: str,
        filename: str,
        content_type: str = 'text/html',
        upsert: bool = False
    ) -> Optional[str]:
        """
        Upload a report file to the reports bucket.
        
        Args:
            local_path: Path to local report file
            report_id: Report ID (used as folder name)
            filename: Filename (e.g., 'report.html', 'report.pdf')
            content_type: MIME type ('text/html' or 'application/pdf')
            upsert: If True, overwrite existing files
        
        Returns:
            Storage key or None if upload failed
        """
        # Choose the correct branch before the workflow continues.
        if not local_path.exists():
            # Trigger the side effect required for this stage.
            logger.error(f"Local file not found: {local_path}")
            return None
        
        storage_key = f"{report_id}/{filename}"
        full_key = f"{self.reports_bucket}/{storage_key}"

        if self._restriction_active():
            logger.debug(f"Skip report upload (project restricted): {full_key}")
            return None

        # Choose the correct branch before the workflow continues.
        if self.precheck_exists_before_upload and not upsert and self._object_exists(self.reports_bucket, storage_key):
            # Trigger the side effect required for this stage.
            logger.info(f"Report already exists in storage, reusing key: {full_key}")
            return full_key
        
        try:
            with open(local_path, 'rb') as f:
                # Prepare file data for the next step.
                file_data = f.read()
            
            # Upload to Supabase Storage
            result = self.client.storage.from_(self.reports_bucket).upload(
                path=storage_key,
                file=file_data,
                file_options={"content-type": content_type, "upsert": 'true' if upsert else 'false'}
            )
            
            # Trigger the side effect required for this stage.
            logger.info(f"Uploaded report: {full_key}")
            return full_key
            
        except Exception as e:
            # See upload_image: storage3 raises AttributeError on opaque
            # error responses (409 duplicate, 402 project restricted, ...).
            err_text = str(e)
            if "'dict' object has no attribute 'text'" in err_text or 'already exists' in err_text.lower():
                if self._object_exists(self.reports_bucket, storage_key):
                    # Trigger the side effect required for this stage.
                    logger.info(
                        f"Report upload reported duplicate; treating as already-uploaded: {full_key}"
                    )
                    return full_key
                if self._probe_restriction(self.reports_bucket, storage_key):
                    return None
            # Trigger the side effect required for this stage.
            logger.error(f"Failed to upload report {storage_key}: {e}")
            return None
    
    # =========================================================================
    # SIGNED URL GENERATION
    # =========================================================================
    
    def get_signed_url(self, storage_key: str, expires_in: Optional[int] = None) -> Optional[str]:
        """
        Generate a signed URL for accessing a private storage object.
        
        Args:
            storage_key: Full storage key (e.g., 'violation-images/20231205_143022/original.jpg')
            expires_in: Expiration time in seconds (defaults to self.signed_url_ttl)
        
        Returns:
            Signed URL or None if generation failed
        """
        # Choose the correct branch before the workflow continues.
        if not storage_key:
            # Trigger the side effect required for this stage.
            logger.warning("Empty storage key provided")
            return None
        
        # Parse bucket and path from storage key
        parts = storage_key.split('/', 1)
        if len(parts) != 2:
            logger.error(f"Invalid storage key format: {storage_key}")
            return None
        
        # Prepare values needed by the next step.
        bucket_name, path = parts
        expires_in = expires_in or self.signed_url_ttl
        
        try:
            # Generate signed URL
            # Prepare result for the next step.
            result = self.client.storage.from_(bucket_name).create_signed_url(
                path=path,
                expires_in=expires_in
            )
            
            if result:
                # Prepare signed url for the next step.
                signed_url = result.get('signedURL')
                logger.debug(f"Generated signed URL for: {storage_key}")
                return signed_url
            else:
                logger.error(f"No signed URL returned for: {storage_key}")
                return None
                
        except Exception as e:
            # Trigger the side effect required for this stage.
            logger.error(f"Failed to generate signed URL for {storage_key}: {e}")
            return None
    
    # Section: run the download file content workflow with clear inputs and outputs.
    def download_file_content(self, storage_key: str) -> Optional[bytes]:
        """
        Download file content from storage.
        
        Args:
            storage_key: Full storage key (e.g., 'reports/20231205_143022/report.html')
        
        Returns:
            File content as bytes or None if download failed
        """
        # Choose the correct branch before the workflow continues.
        if not storage_key:
            # Trigger the side effect required for this stage.
            logger.warning("Empty storage key provided")
            return None
        
        # Parse bucket and path from storage key
        parts = storage_key.split('/', 1)
        if len(parts) != 2:
            logger.error(f"Invalid storage key format: {storage_key}")
            return None
        
        # Prepare values needed by the next step.
        bucket_name, path = parts

        if self._egress_budget_active():
            # Prepare usage for the next step.
            usage = self.get_egress_usage()
            if usage.get('blocked'):
                # Prepare egress block reason for the next step.
                self._egress_block_reason = usage.get('blocked_reason') or 'Monthly egress budget exceeded.'
                logger.warning(self._egress_block_reason)
                return None

        # Choose the correct branch before the workflow continues.
        if self._restriction_active():
            logger.debug(f"Skip download (project restricted): {storage_key}")
            return None
        
        try:
            # Download file content
            # Prepare result for the next step.
            result = self.client.storage.from_(bucket_name).download(path)
            if result is None:
                logger.error(f"No content returned for: {storage_key}")
                self._probe_restriction(bucket_name, path, method='GET')
                return None

            size_bytes = 0
            if isinstance(result, (bytes, bytearray)):
                size_bytes = len(result)
            # Choose the correct branch before the workflow continues.
            elif isinstance(result, str):
                size_bytes = len(result.encode('utf-8'))
            else:
                # Protect this step so expected failures can fall back cleanly.
                try:
                    # Prepare size bytes for the next step.
                    size_bytes = len(result)
                except Exception:
                    size_bytes = 0
            if size_bytes:
                self._record_egress_bytes(size_bytes)
            # Trigger the side effect required for this stage.
            logger.debug(f"Downloaded content from: {storage_key}")
            return result
                
        except Exception as e:
            err_text = str(e)
            status_code = None
            if PostgrestAPIError and isinstance(e, PostgrestAPIError):
                # Prepare status code for the next step.
                status_code = getattr(e, 'status_code', None) or getattr(e, 'code', None)
                try:
                    # Prepare status code for the next step.
                    status_code = int(status_code)
                except Exception:
                    status_code = None
            # Choose the correct branch before the workflow continues.
            if (
                status_code == 402
                or '402' in err_text
                or 'exceed_egress_quota' in err_text
                or 'restricted' in err_text.lower()
            ):
                # Trigger the side effect required for this stage.
                self._trip_restriction(f"HTTP {status_code or '402'}: {err_text[:240]}")
                return None
            if self._probe_restriction(bucket_name, path, method='GET'):
                return None
            # Trigger the side effect required for this stage.
            logger.error(f"Failed to download file from {storage_key}: {e}")
            return None
    
    # Section: run the get image signed url workflow with clear inputs and outputs.
    def get_image_signed_url(self, report_id: str, filename: str) -> Optional[str]:
        """
        Generate signed URL for an image.
        
        Args:
            report_id: Report ID
            filename: Image filename ('original.jpg' or 'annotated.jpg')
        
        Returns:
            Signed URL or None if failed
        """
        # Prepare storage key for the next step.
        storage_key = f"{self.images_bucket}/{report_id}/{filename}"
        return self.get_signed_url(storage_key)
    
    # Section: run the get report signed url workflow with clear inputs and outputs.
    def get_report_signed_url(self, report_id: str, filename: str) -> Optional[str]:
        """
        Generate signed URL for a report file.
        
        Args:
            report_id: Report ID
            filename: Report filename ('report.html' or 'report.pdf')
        
        Returns:
            Signed URL or None if failed
        """
        # Prepare storage key for the next step.
        storage_key = f"{self.reports_bucket}/{report_id}/{filename}"
        return self.get_signed_url(storage_key)
    
    # =========================================================================
    # BATCH OPERATIONS
    # =========================================================================
    
    def upload_violation_artifacts(
        self,
        report_id: str,
        original_image_path: Optional[Path] = None,
        annotated_image_path: Optional[Path] = None,
        report_html_path: Optional[Path] = None,
        report_pdf_path: Optional[Path] = None,
        upsert: bool = False
    ) -> Dict[str, Optional[str]]:
        """
        Upload all violation artifacts for a report.
        
        Args:
            report_id: Report ID
            original_image_path: Path to original image
            annotated_image_path: Path to annotated image
            report_html_path: Path to HTML report
            report_pdf_path: Path to PDF report (optional)
            upsert: If True, overwrite existing files
        
        Returns:
            Dictionary with storage keys for each uploaded file
        """
        # Prepare results for the next step.
        results = {
            'original_image_key': None,
            'annotated_image_key': None,
            'report_html_key': None,
            'report_pdf_key': None
        }
        
        # Upload original image
        if original_image_path:
            results['original_image_key'] = self.upload_image(
                original_image_path, report_id, 'original.jpg', upsert
            )
        
        # Upload annotated image
        # Choose the correct branch before the workflow continues.
        if annotated_image_path:
            results['annotated_image_key'] = self.upload_image(
                annotated_image_path, report_id, 'annotated.jpg', upsert
            )
        
        # Upload HTML report
        if report_html_path:
            results['report_html_key'] = self.upload_report(
                report_html_path, report_id, 'report.html', 'text/html', upsert
            )
        
        # Upload PDF report (optional)
        # Choose the correct branch before the workflow continues.
        if report_pdf_path and report_pdf_path.exists():
            results['report_pdf_key'] = self.upload_report(
                report_pdf_path, report_id, 'report.pdf', 'application/pdf', upsert
            )
        
        logger.info(f"Uploaded artifacts for report: {report_id}")
        return results
    
    # =========================================================================
    # DELETION OPERATIONS
    # =========================================================================
    
    def delete_violation_artifacts(self, report_id: str) -> bool:
        """
        Delete all artifacts for a violation report.
        
        Args:
            report_id: Report ID
        
        Returns:
            True if successful, False otherwise
        """
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Delete images
            # Trigger the side effect required for this stage.
            self.client.storage.from_(self.images_bucket).remove([
                f"{report_id}/original.jpg",
                f"{report_id}/annotated.jpg"
            ])
            
            # Delete reports
            self.client.storage.from_(self.reports_bucket).remove([
                f"{report_id}/report.html",
                f"{report_id}/report.pdf"
            ])
            
            # Trigger the side effect required for this stage.
            logger.info(f"Deleted artifacts for report: {report_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete artifacts for {report_id}: {e}")
            return False


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_storage_manager_from_env() -> SupabaseStorageManager:
    """
    Create SupabaseStorageManager from environment variables.
    
    Required environment variables:
        - SUPABASE_URL
        - SUPABASE_SERVICE_ROLE_KEY
    
    Optional environment variables:
        - SUPABASE_IMAGES_BUCKET (default: 'violation-images')
        - SUPABASE_REPORTS_BUCKET (default: 'reports')
        - SUPABASE_SIGNED_URL_TTL_SECONDS (default: 3600)
    
    Returns:
        SupabaseStorageManager instance
    """
    # Prepare supabase url for the next step.
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

    normalized_url = str(supabase_url or '').strip().lower()
    normalized_key = str(supabase_key or '').strip().lower()
    placeholder_markers = (
        'your-project-id',
        'your-service-role-key',
        'example.supabase.co',
    )
    
    # Choose the correct branch before the workflow continues.
    if (
        not supabase_url
        or not supabase_key
        or any(marker in normalized_url for marker in placeholder_markers)
        or any(marker in normalized_key for marker in placeholder_markers)
    ):
        # Surface the failure with enough context for the caller.
        raise ValueError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set to real project values"
        )
    
    # Prepare images bucket for the next step.
    images_bucket = os.getenv('SUPABASE_IMAGES_BUCKET', 'violation-images')
    reports_bucket = os.getenv('SUPABASE_REPORTS_BUCKET', 'reports')
    signed_url_ttl = int(os.getenv('SUPABASE_SIGNED_URL_TTL_SECONDS', '3600'))
    
    return SupabaseStorageManager(
        supabase_url=supabase_url,
        supabase_key=supabase_key,
        images_bucket=images_bucket,
        reports_bucket=reports_bucket,
        signed_url_ttl=signed_url_ttl
    )


# =============================================================================
# TESTING
# =============================================================================

if __name__ == '__main__':
    import sys
    from dotenv import load_dotenv
    
    # Trigger the side effect required for this stage.
    logging.basicConfig(level=logging.INFO)
    
    # Load environment variables
    load_dotenv()
    
    print("=" * 70)
    print("SUPABASE STORAGE MANAGER TEST")
    print("=" * 70)
    
    # Protect this step so expected failures can fall back cleanly.
    try:
        # Prepare manager for the next step.
        manager = create_storage_manager_from_env()
        print(f"\n[OK] Storage manager initialized")
        print(f"Images bucket: {manager.images_bucket}")
        print(f"Reports bucket: {manager.reports_bucket}")
        print(f"Signed URL TTL: {manager.signed_url_ttl}s")
        
        print("\n[OK] All tests passed!")
    except Exception as e:
        print(f"\n[X] Test failed: {e}")
        # Trigger the side effect required for this stage.
        sys.exit(1)
    
    # Trigger the side effect required for this stage.
    print("=" * 70)
