"""
Supabase Storage Manager
=========================

Handles uploading and retrieving files from Supabase Storage buckets.
Provides signed URLs for secure access to private buckets.
"""

import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import timedelta

from supabase import create_client, Client

logger = logging.getLogger(__name__)


class SupabaseStorageManager:
    """
    Manages file uploads to Supabase Storage and generates signed URLs.
    
    Handles two private buckets:
    - violation-images: Original and annotated images
    - reports: HTML and PDF reports
    """
    
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
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key
        self.images_bucket = images_bucket
        self.reports_bucket = reports_bucket
        self.signed_url_ttl = signed_url_ttl
        
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
        if not local_path.exists():
            logger.error(f"Local file not found: {local_path}")
            return None
        
        storage_key = f"{report_id}/{filename}"
        
        try:
            with open(local_path, 'rb') as f:
                file_data = f.read()
            
            # Upload to Supabase Storage
            result = self.client.storage.from_(self.images_bucket).upload(
                path=storage_key,
                file=file_data,
                file_options={"content-type": "image/jpeg", "upsert": str(upsert).lower()}
            )
            
            full_key = f"{self.images_bucket}/{storage_key}"
            logger.info(f"Uploaded image: {full_key}")
            return full_key
            
        except Exception as e:
            logger.error(f"Failed to upload image {storage_key}: {e}")
            return None
    
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
        if not local_path.exists():
            logger.error(f"Local file not found: {local_path}")
            return None
        
        storage_key = f"{report_id}/{filename}"
        
        try:
            with open(local_path, 'rb') as f:
                file_data = f.read()
            
            # Upload to Supabase Storage
            result = self.client.storage.from_(self.reports_bucket).upload(
                path=storage_key,
                file=file_data,
                file_options={"content-type": content_type, "upsert": str(upsert).lower()}
            )
            
            full_key = f"{self.reports_bucket}/{storage_key}"
            logger.info(f"Uploaded report: {full_key}")
            return full_key
            
        except Exception as e:
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
        if not storage_key:
            logger.warning("Empty storage key provided")
            return None
        
        # Parse bucket and path from storage key
        parts = storage_key.split('/', 1)
        if len(parts) != 2:
            logger.error(f"Invalid storage key format: {storage_key}")
            return None
        
        bucket_name, path = parts
        expires_in = expires_in or self.signed_url_ttl
        
        try:
            # Generate signed URL
            result = self.client.storage.from_(bucket_name).create_signed_url(
                path=path,
                expires_in=expires_in
            )
            
            if result:
                signed_url = result.get('signedURL')
                logger.debug(f"Generated signed URL for: {storage_key}")
                return signed_url
            else:
                logger.error(f"No signed URL returned for: {storage_key}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to generate signed URL for {storage_key}: {e}")
            return None
    
    def download_file_content(self, storage_key: str) -> Optional[bytes]:
        """
        Download file content from storage.
        
        Args:
            storage_key: Full storage key (e.g., 'reports/20231205_143022/report.html')
        
        Returns:
            File content as bytes or None if download failed
        """
        if not storage_key:
            logger.warning("Empty storage key provided")
            return None
        
        # Parse bucket and path from storage key
        parts = storage_key.split('/', 1)
        if len(parts) != 2:
            logger.error(f"Invalid storage key format: {storage_key}")
            return None
        
        bucket_name, path = parts
        
        try:
            # Download file content
            result = self.client.storage.from_(bucket_name).download(path)
            
            if result:
                logger.debug(f"Downloaded content from: {storage_key}")
                return result
            else:
                logger.error(f"No content returned for: {storage_key}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to download file from {storage_key}: {e}")
            return None
    
    def get_image_signed_url(self, report_id: str, filename: str) -> Optional[str]:
        """
        Generate signed URL for an image.
        
        Args:
            report_id: Report ID
            filename: Image filename ('original.jpg' or 'annotated.jpg')
        
        Returns:
            Signed URL or None if failed
        """
        storage_key = f"{self.images_bucket}/{report_id}/{filename}"
        return self.get_signed_url(storage_key)
    
    def get_report_signed_url(self, report_id: str, filename: str) -> Optional[str]:
        """
        Generate signed URL for a report file.
        
        Args:
            report_id: Report ID
            filename: Report filename ('report.html' or 'report.pdf')
        
        Returns:
            Signed URL or None if failed
        """
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
        try:
            # Delete images
            self.client.storage.from_(self.images_bucket).remove([
                f"{report_id}/original.jpg",
                f"{report_id}/annotated.jpg"
            ])
            
            # Delete reports
            self.client.storage.from_(self.reports_bucket).remove([
                f"{report_id}/report.html",
                f"{report_id}/report.pdf"
            ])
            
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
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        raise ValueError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment"
        )
    
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
    
    logging.basicConfig(level=logging.INFO)
    
    # Load environment variables
    load_dotenv()
    
    print("=" * 70)
    print("SUPABASE STORAGE MANAGER TEST")
    print("=" * 70)
    
    try:
        manager = create_storage_manager_from_env()
        print(f"\n[OK] Storage manager initialized")
        print(f"Images bucket: {manager.images_bucket}")
        print(f"Reports bucket: {manager.reports_bucket}")
        print(f"Signed URL TTL: {manager.signed_url_ttl}s")
        
        print("\n[OK] All tests passed!")
    except Exception as e:
        print(f"\n[X] Test failed: {e}")
        sys.exit(1)
    
    print("=" * 70)
