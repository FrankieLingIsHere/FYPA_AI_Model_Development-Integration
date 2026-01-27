"""
Violation Queue Manager
========================

Thread-safe queue manager for handling multiple violations from multiple devices.
Provides priority queuing, rate limiting, and batch processing capabilities.

Features:
- Priority-based processing (CRITICAL > HIGH > MEDIUM > LOW)
- Per-device rate limiting
- Batch processing for efficiency
- Thread-safe operations
- Statistics tracking
"""

import logging
import threading
import time
from queue import PriorityQueue, Empty
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime, timedelta
from enum import IntEnum
import hashlib

logger = logging.getLogger(__name__)


class ViolationPriority(IntEnum):
    """Priority levels for violation processing."""
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4


@dataclass(order=True)
class QueuedViolation:
    """
    A queued violation with priority ordering.
    
    Violations are sorted by priority first, then by timestamp.
    """
    priority: int
    timestamp: float = field(compare=True)
    data: Dict[str, Any] = field(compare=False)
    device_id: str = field(compare=False, default='unknown')
    report_id: str = field(compare=False, default='')
    retry_count: int = field(compare=False, default=0)


class ViolationQueueManager:
    """
    Thread-safe queue manager for violations from multiple devices.
    
    Features:
    - Priority-based processing
    - Per-device rate limiting
    - Batch operations
    - Statistics tracking
    """
    
    def __init__(
        self,
        max_size: int = 100,
        rate_limit_per_device: int = 10,
        rate_limit_window: int = 60,
        max_retries: int = 3
    ):
        """
        Initialize the queue manager.
        
        Args:
            max_size: Maximum queue size
            rate_limit_per_device: Max violations per device per window
            rate_limit_window: Rate limit window in seconds
            max_retries: Maximum retry attempts for failed processing
        """
        self.queue = PriorityQueue(maxsize=max_size)
        self.max_size = max_size
        self.rate_limit = rate_limit_per_device
        self.rate_window = rate_limit_window
        self.max_retries = max_retries
        
        # Thread safety
        self._lock = threading.Lock()
        
        # Device rate tracking: {device_id: [timestamps]}
        self._device_timestamps: Dict[str, List[float]] = {}
        
        # Statistics
        self._stats = {
            'total_enqueued': 0,
            'total_processed': 0,
            'total_failed': 0,
            'total_rate_limited': 0,
            'by_device': {},
            'by_priority': {p.name: 0 for p in ViolationPriority}
        }
        
        logger.info(f"ViolationQueueManager initialized (max_size={max_size}, rate_limit={rate_limit_per_device}/{rate_limit_window}s)")
    
    def _get_priority(self, severity: str) -> int:
        """Convert severity string to priority value."""
        mapping = {
            'CRITICAL': ViolationPriority.CRITICAL,
            'HIGH': ViolationPriority.HIGH,
            'MEDIUM': ViolationPriority.MEDIUM,
            'LOW': ViolationPriority.LOW
        }
        return mapping.get(severity.upper(), ViolationPriority.MEDIUM)
    
    def _check_rate_limit(self, device_id: str) -> bool:
        """
        Check if device is within rate limit.
        
        Args:
            device_id: Device identifier
        
        Returns:
            True if within limit, False if rate limited
        """
        with self._lock:
            now = time.time()
            window_start = now - self.rate_window
            
            if device_id not in self._device_timestamps:
                self._device_timestamps[device_id] = []
            
            # Clean old timestamps
            self._device_timestamps[device_id] = [
                ts for ts in self._device_timestamps[device_id]
                if ts > window_start
            ]
            
            # Check limit
            if len(self._device_timestamps[device_id]) >= self.rate_limit:
                logger.warning(f"Rate limit exceeded for device: {device_id}")
                self._stats['total_rate_limited'] += 1
                return False
            
            # Add timestamp
            self._device_timestamps[device_id].append(now)
            return True
    
    def enqueue(
        self,
        violation_data: Dict[str, Any],
        device_id: str = 'unknown',
        report_id: str = None,
        severity: str = 'HIGH'
    ) -> bool:
        """
        Add a violation to the queue.
        
        Args:
            violation_data: Violation data dictionary
            device_id: Source device identifier
            report_id: Unique report ID
            severity: Severity level
        
        Returns:
            True if enqueued, False if rejected
        """
        # Check rate limit
        if not self._check_rate_limit(device_id):
            return False
        
        # Check queue capacity
        if self.queue.full():
            logger.warning("Queue is full, rejecting violation")
            return False
        
        # Generate report_id if not provided
        if not report_id:
            from zoneinfo import ZoneInfo
            myt = ZoneInfo('Asia/Kuala_Lumpur')
            now_myt = datetime.now(myt)
            timestamp = now_myt.strftime('%Y%m%d_%H%M%S')
            device_hash = hashlib.md5(device_id.encode()).hexdigest()[:6]
            micro = now_myt.strftime('%f')[:4]
            report_id = f"{timestamp}_{device_hash}_{micro}"
        
        priority = self._get_priority(severity)
        
        queued = QueuedViolation(
            priority=priority,
            timestamp=time.time(),
            data=violation_data,
            device_id=device_id,
            report_id=report_id
        )
        
        try:
            self.queue.put_nowait(queued)
            
            # Update stats
            with self._lock:
                self._stats['total_enqueued'] += 1
                self._stats['by_priority'][ViolationPriority(priority).name] += 1
                
                if device_id not in self._stats['by_device']:
                    self._stats['by_device'][device_id] = {'enqueued': 0, 'processed': 0, 'failed': 0}
                self._stats['by_device'][device_id]['enqueued'] += 1
            
            logger.info(f"Enqueued violation {report_id} from {device_id} (priority={ViolationPriority(priority).name})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to enqueue violation: {e}")
            return False
    
    def dequeue(self, timeout: float = None) -> Optional[QueuedViolation]:
        """
        Get next violation from queue.
        
        Args:
            timeout: Seconds to wait (None for non-blocking)
        
        Returns:
            QueuedViolation or None if empty
        """
        try:
            return self.queue.get(timeout=timeout)
        except Empty:
            return None
    
    def dequeue_batch(self, batch_size: int = 5) -> List[QueuedViolation]:
        """
        Get a batch of violations from queue.
        
        Args:
            batch_size: Maximum number of violations to retrieve
        
        Returns:
            List of QueuedViolation objects
        """
        batch = []
        for _ in range(batch_size):
            violation = self.dequeue()
            if violation is None:
                break
            batch.append(violation)
        return batch
    
    def requeue(self, violation: QueuedViolation) -> bool:
        """
        Re-add a failed violation to the queue for retry.
        
        Args:
            violation: The failed violation
        
        Returns:
            True if requeued, False if max retries exceeded
        """
        if violation.retry_count >= self.max_retries:
            logger.warning(f"Max retries exceeded for {violation.report_id}")
            with self._lock:
                self._stats['total_failed'] += 1
                if violation.device_id in self._stats['by_device']:
                    self._stats['by_device'][violation.device_id]['failed'] += 1
            return False
        
        violation.retry_count += 1
        # Lower priority for retries
        violation.priority = min(violation.priority + 1, ViolationPriority.LOW)
        
        try:
            self.queue.put_nowait(violation)
            logger.info(f"Requeued violation {violation.report_id} (retry {violation.retry_count})")
            return True
        except Exception as e:
            logger.error(f"Failed to requeue: {e}")
            return False
    
    def mark_processed(self, violation: QueuedViolation):
        """Mark a violation as successfully processed."""
        with self._lock:
            self._stats['total_processed'] += 1
            if violation.device_id in self._stats['by_device']:
                self._stats['by_device'][violation.device_id]['processed'] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        with self._lock:
            return {
                **self._stats,
                'current_size': self.queue.qsize(),
                'capacity': self.max_size
            }
    
    def clear(self):
        """Clear the queue."""
        with self._lock:
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                except Empty:
                    break
        logger.info("Queue cleared")


class MultiDeviceViolationHandler:
    """
    High-level handler for processing violations from multiple devices.
    
    Manages worker threads, batch processing, and callbacks.
    """
    
    def __init__(
        self,
        queue_manager: ViolationQueueManager,
        db_manager: Any,
        num_workers: int = 2,
        batch_size: int = 5,
        process_callback: Callable = None
    ):
        """
        Initialize the handler.
        
        Args:
            queue_manager: ViolationQueueManager instance
            db_manager: Database manager for persistence
            num_workers: Number of worker threads
            batch_size: Violations to process per batch
            process_callback: Optional callback for processing each violation
        """
        self.queue = queue_manager
        self.db = db_manager
        self.num_workers = num_workers
        self.batch_size = batch_size
        self.process_callback = process_callback
        
        self._workers: List[threading.Thread] = []
        self._running = False
        self._lock = threading.Lock()
        
        logger.info(f"MultiDeviceViolationHandler initialized ({num_workers} workers)")
    
    def start(self):
        """Start worker threads."""
        if self._running:
            logger.warning("Handler already running")
            return
        
        self._running = True
        
        for i in range(self.num_workers):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"ViolationWorker-{i}",
                daemon=True
            )
            worker.start()
            self._workers.append(worker)
        
        logger.info(f"Started {self.num_workers} violation workers")
    
    def stop(self, timeout: float = 5.0):
        """Stop worker threads."""
        self._running = False
        
        for worker in self._workers:
            worker.join(timeout=timeout)
        
        self._workers.clear()
        logger.info("Stopped violation workers")
    
    def _worker_loop(self):
        """Main worker loop."""
        while self._running:
            try:
                # Get batch of violations
                batch = self.queue.dequeue_batch(self.batch_size)
                
                if not batch:
                    time.sleep(0.5)  # Wait before checking again
                    continue
                
                # Process batch
                for violation in batch:
                    try:
                        self._process_violation(violation)
                        self.queue.mark_processed(violation)
                    except Exception as e:
                        logger.error(f"Error processing {violation.report_id}: {e}")
                        self.queue.requeue(violation)
                        
            except Exception as e:
                logger.error(f"Worker error: {e}")
                time.sleep(1)
    
    def _process_violation(self, violation: QueuedViolation):
        """
        Process a single violation.
        
        Args:
            violation: The violation to process
        """
        report_id = violation.report_id
        device_id = violation.device_id
        data = violation.data
        
        logger.info(f"Processing violation {report_id} from {device_id}")
        
        # Update status to generating
        if hasattr(self.db, 'update_status'):
            self.db.update_status(report_id, 'generating')
        
        try:
            # Call custom processor if provided
            if self.process_callback:
                result = self.process_callback(violation)
                if not result:
                    raise Exception("Process callback returned failure")
            
            # Update status to completed
            if hasattr(self.db, 'update_status'):
                self.db.update_status(report_id, 'completed')
            
            # Log success
            if hasattr(self.db, 'log_event'):
                self.db.log_event(
                    'violation_processed',
                    f"Successfully processed violation {report_id}",
                    report_id=report_id,
                    metadata={'device_id': device_id}
                )
                
        except Exception as e:
            logger.error(f"Failed to process violation {report_id}: {e}")
            
            # Update status to failed
            if hasattr(self.db, 'update_status'):
                self.db.update_status(report_id, 'failed', str(e))
            
            raise
    
    def submit_violation(
        self,
        violation_data: Dict[str, Any],
        device_id: str = 'unknown',
        report_id: str = None,
        severity: str = 'HIGH'
    ) -> Optional[str]:
        """
        Submit a violation for processing.
        
        Args:
            violation_data: Violation data
            device_id: Source device
            report_id: Optional report ID
            severity: Severity level
        
        Returns:
            Report ID if submitted, None if rejected
        """
        # Generate report_id if not provided
        if not report_id:
            from zoneinfo import ZoneInfo
            myt = ZoneInfo('Asia/Kuala_Lumpur')
            now_myt = datetime.now(myt)
            timestamp = now_myt.strftime('%Y%m%d_%H%M%S')
            device_hash = hashlib.md5(device_id.encode()).hexdigest()[:6]
            micro = now_myt.strftime('%f')[:4]
            report_id = f"{timestamp}_{device_hash}_{micro}"
        
        # Add to database with pending status
        if hasattr(self.db, 'insert_detection_event'):
            self.db.insert_detection_event(
                report_id=report_id,
                timestamp=datetime.now(),
                person_count=violation_data.get('person_count', 0),
                violation_count=violation_data.get('violation_count', 0),
                severity=severity,
                device_id=device_id,
                status='pending'
            )
        
        # Enqueue for processing
        success = self.queue.enqueue(
            violation_data=violation_data,
            device_id=device_id,
            report_id=report_id,
            severity=severity
        )
        
        if success:
            logger.info(f"Submitted violation {report_id} from {device_id}")
            return report_id
        else:
            logger.warning(f"Failed to submit violation from {device_id}")
            return None
    
    def get_handler_stats(self) -> Dict[str, Any]:
        """Get handler statistics."""
        return {
            'queue_stats': self.queue.get_stats(),
            'workers': len(self._workers),
            'running': self._running
        }


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_queue_manager_from_config(config: Dict[str, Any] = None) -> ViolationQueueManager:
    """
    Create a ViolationQueueManager from configuration.
    
    Args:
        config: Optional configuration dict (uses QUEUE_CONFIG if not provided)
    
    Returns:
        ViolationQueueManager instance
    """
    if config is None:
        try:
            from ..config import QUEUE_CONFIG
            config = QUEUE_CONFIG
        except ImportError:
            config = {}
    
    return ViolationQueueManager(
        max_size=config.get('max_queue_size', 100),
        rate_limit_per_device=config.get('rate_limit_per_device', 10),
        rate_limit_window=60,
        max_retries=config.get('max_retries', 3)
    )


def create_violation_handler(
    db_manager: Any,
    config: Dict[str, Any] = None,
    process_callback: Callable = None
) -> MultiDeviceViolationHandler:
    """
    Create a MultiDeviceViolationHandler from configuration.
    
    Args:
        db_manager: Database manager instance
        config: Optional configuration dict
        process_callback: Optional processing callback
    
    Returns:
        MultiDeviceViolationHandler instance
    """
    if config is None:
        try:
            from ..config import QUEUE_CONFIG
            config = QUEUE_CONFIG
        except ImportError:
            config = {}
    
    queue_manager = create_queue_manager_from_config(config)
    
    return MultiDeviceViolationHandler(
        queue_manager=queue_manager,
        db_manager=db_manager,
        num_workers=config.get('num_workers', 2),
        batch_size=config.get('batch_size', 5),
        process_callback=process_callback
    )


# =============================================================================
# TESTING
# =============================================================================

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 70)
    print("VIOLATION QUEUE MANAGER TEST")
    print("=" * 70)
    
    # Create queue manager
    queue = ViolationQueueManager(max_size=10, rate_limit_per_device=5)
    
    # Test enqueueing
    print("\n--- Testing Enqueue ---")
    for i in range(8):
        device = f"CAM_0{i % 3}"
        severity = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'][i % 4]
        success = queue.enqueue(
            violation_data={'test': f'data_{i}'},
            device_id=device,
            severity=severity
        )
        print(f"Enqueued {i}: {success} (device={device}, severity={severity})")
    
    # Test dequeue
    print("\n--- Testing Dequeue (Priority Order) ---")
    while True:
        v = queue.dequeue()
        if v is None:
            break
        print(f"Dequeued: {v.report_id} priority={ViolationPriority(v.priority).name} device={v.device_id}")
    
    # Test rate limiting
    print("\n--- Testing Rate Limiting ---")
    for i in range(7):
        success = queue.enqueue(
            violation_data={'test': f'rate_{i}'},
            device_id='CAM_RATE_TEST',
            severity='HIGH'
        )
        print(f"Enqueue {i}: {success}")
    
    # Show stats
    print("\n--- Statistics ---")
    stats = queue.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    print("\n[OK] All tests passed!")
    print("=" * 70)
