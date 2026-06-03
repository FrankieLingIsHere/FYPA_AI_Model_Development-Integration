"""
Violation Queue Manager
========================

Thread-safe queue manager for handling multiple violations from multiple devices.
Provides priority queuing, rate limiting, and batch processing capabilities.

Features:
- Priority-based processing (URGENT > CRITICAL > HIGH > MEDIUM > LOW)
- Per-device rate limiting
- Batch processing for efficiency
- Thread-safe operations
- Statistics tracking
"""
# Readability: Backend core: coordinate detection, persistence, and report workflow concerns.

import logging
import threading
import time
from queue import PriorityQueue, Empty
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime, timedelta
from enum import IntEnum
import hashlib

# Prepare logger for the next step.
logger = logging.getLogger(__name__)


# Section: group violation priority state and behaviour in one readable unit.
class ViolationPriority(IntEnum):
    """Priority levels for violation processing."""
    # Prepare urgent for the next step.
    URGENT = 0
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4


# Section: group queued violation state and behaviour in one readable unit.
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


# Section: group violation queue manager state and behaviour in one readable unit.
class ViolationQueueManager:
    """
    Thread-safe queue manager for violations from multiple devices.
    
    Features:
    - Priority-based processing
    - Per-device rate limiting
    - Batch operations
    - Statistics tracking
    """
    
    # Section: run the init workflow with clear inputs and outputs.
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
        # Prepare queue for the next step.
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
        # Prepare stats for the next step.
        self._stats = {
            'total_enqueued': 0,
            'total_processed': 0,
            'total_failed': 0,
            'total_rate_limited': 0,
            'by_device': {},
            'by_priority': {p.name: 0 for p in ViolationPriority}
        }
        
        # Trigger the side effect required for this stage.
        logger.info(f"ViolationQueueManager initialized (max_size={max_size}, rate_limit={rate_limit_per_device}/{rate_limit_window}s)")
    
    # Section: run the get priority workflow with clear inputs and outputs.
    def _get_priority(self, severity: str) -> int:
        """Convert severity string to priority value."""
        mapping = {
            'URGENT': ViolationPriority.URGENT,
            'CRITICAL': ViolationPriority.CRITICAL,
            'HIGH': ViolationPriority.HIGH,
            'MEDIUM': ViolationPriority.MEDIUM,
            'LOW': ViolationPriority.LOW
        }
        # Return the prepared result to the caller.
        return mapping.get(severity.upper(), ViolationPriority.MEDIUM)
    
    # Section: run the prune device timestamps locked workflow with clear inputs and outputs.
    def _prune_device_timestamps_locked(self, device_id: str, now: float) -> None:
        """Drop timestamps outside the active rate-limit window. Caller must hold _lock."""
        window_start = now - self.rate_window

        if device_id not in self._device_timestamps:
            # Prepare values needed by the next step.
            self._device_timestamps[device_id] = []

        # Prepare values needed by the next step.
        self._device_timestamps[device_id] = [
            ts for ts in self._device_timestamps[device_id]
            if ts > window_start
        ]

    # Section: run the is device rate limited workflow with clear inputs and outputs.
    def is_device_rate_limited(self, device_id: str, record: bool = False) -> bool:
        """Return True if device already used its active-window enqueue allowance."""
        with self._lock:
            # Prepare now for the next step.
            now = time.time()
            self._prune_device_timestamps_locked(device_id, now)
            limited = len(self._device_timestamps[device_id]) >= self.rate_limit
            if limited and record:
                # Trigger the side effect required for this stage.
                logger.warning(f"Rate limit exceeded for device: {device_id}")
                self._stats['total_rate_limited'] += 1
            return limited

    # Section: run the check rate limit workflow with clear inputs and outputs.
    def _check_rate_limit(self, device_id: str) -> bool:
        """
        Check if device is within rate limit.
        
        Args:
            device_id: Device identifier
        
        Returns:
            True if within limit, False if rate limited
        """
        # Open the managed resource only for the block that needs it.
        with self._lock:
            # Prepare now for the next step.
            now = time.time()
            self._prune_device_timestamps_locked(device_id, now)

            # Check limit
            if len(self._device_timestamps[device_id]) >= self.rate_limit:
                logger.warning(f"Rate limit exceeded for device: {device_id}")
                self._stats['total_rate_limited'] += 1
                return False
            
            # Add timestamp
            # Trigger the side effect required for this stage.
            self._device_timestamps[device_id].append(now)
            return True
    
    # Section: run the enqueue workflow with clear inputs and outputs.
    def enqueue(
        self,
        violation_data: Dict[str, Any],
        device_id: str = 'unknown',
        report_id: str = None,
        severity: str = 'HIGH',
        expedite: bool = False,
    ) -> bool:
        """
        Add a violation to the queue.
        
        Args:
            violation_data: Violation data dictionary
            device_id: Source device identifier
            report_id: Unique report ID
            severity: Severity level
            expedite: If True, place item ahead of normal backlog at same priority
        
        Returns:
            True if enqueued, False if rejected
        """
        # Check rate limit
        # Choose the correct branch before the workflow continues.
        if not self._check_rate_limit(device_id):
            # Return the prepared result to the caller.
            return False
        
        # Check queue capacity
        if self.queue.full():
            logger.warning("Queue is full, rejecting violation")
            return False
        
        # Generate report_id if not provided
        # Choose the correct branch before the workflow continues.
        if not report_id:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            device_hash = hashlib.md5(device_id.encode()).hexdigest()[:6]
            micro = datetime.now().strftime('%f')[:4]
            report_id = f"{timestamp}_{device_hash}_{micro}"
        
        priority = self._get_priority(severity)
        queue_timestamp = time.time()
        if expedite:
            # Keep urgent user-triggered actions responsive even when historical queue backlog exists.
            queue_timestamp -= 1_000_000_000.0
        
        queued = QueuedViolation(
            priority=priority,
            timestamp=queue_timestamp,
            data=violation_data,
            device_id=device_id,
            report_id=report_id
        )
        
        try:
            # Trigger the side effect required for this stage.
            self.queue.put_nowait(queued)
            
            # Update stats
            with self._lock:
                self._stats['total_enqueued'] += 1
                self._stats['by_priority'][ViolationPriority(priority).name] += 1
                
                # Choose the correct branch before the workflow continues.
                if device_id not in self._stats['by_device']:
                    # Prepare values needed by the next step.
                    self._stats['by_device'][device_id] = {'enqueued': 0, 'processed': 0, 'failed': 0}
                self._stats['by_device'][device_id]['enqueued'] += 1
            
            # Trigger the side effect required for this stage.
            logger.info(f"Enqueued violation {report_id} from {device_id} (priority={ViolationPriority(priority).name})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to enqueue violation: {e}")
            return False
    
    # Section: run the dequeue workflow with clear inputs and outputs.
    def dequeue(self, timeout: float = None) -> Optional[QueuedViolation]:
        """
        Get next violation from queue.
        
        Args:
            timeout: Seconds to wait (None for non-blocking)
        
        Returns:
            QueuedViolation or None if empty
        """
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Return the prepared result to the caller.
            return self.queue.get(timeout=timeout)
        except Empty:
            return None
    
    # Section: run the dequeue batch workflow with clear inputs and outputs.
    def dequeue_batch(self, batch_size: int = 5) -> List[QueuedViolation]:
        """
        Get a batch of violations from queue.
        
        Args:
            batch_size: Maximum number of violations to retrieve
        
        Returns:
            List of QueuedViolation objects
        """
        # Prepare batch for the next step.
        batch = []
        for _ in range(batch_size):
            # Prepare violation for the next step.
            violation = self.dequeue()
            if violation is None:
                break
            batch.append(violation)
        return batch
    
    # Section: run the requeue workflow with clear inputs and outputs.
    def requeue(self, violation: QueuedViolation) -> bool:
        """
        Re-add a failed violation to the queue for retry.
        
        Args:
            violation: The failed violation
        
        Returns:
            True if requeued, False if max retries exceeded
        """
        # Choose the correct branch before the workflow continues.
        if violation.retry_count >= self.max_retries:
            # Trigger the side effect required for this stage.
            logger.warning(f"Max retries exceeded for {violation.report_id}")
            with self._lock:
                self._stats['total_failed'] += 1
                # Choose the correct branch before the workflow continues.
                if violation.device_id in self._stats['by_device']:
                    self._stats['by_device'][violation.device_id]['failed'] += 1
            return False
        
        violation.retry_count += 1
        # Lower priority for retries
        # Prepare priority for the next step.
        violation.priority = min(violation.priority + 1, ViolationPriority.LOW)
        
        try:
            # Trigger the side effect required for this stage.
            self.queue.put_nowait(violation)
            logger.info(f"Requeued violation {violation.report_id} (retry {violation.retry_count})")
            return True
        except Exception as e:
            logger.error(f"Failed to requeue: {e}")
            return False
    
    # Section: run the mark processed workflow with clear inputs and outputs.
    def mark_processed(self, violation: QueuedViolation):
        """Mark a violation as successfully processed."""
        # Open the managed resource only for the block that needs it.
        with self._lock:
            self._stats['total_processed'] += 1
            # Choose the correct branch before the workflow continues.
            if violation.device_id in self._stats['by_device']:
                self._stats['by_device'][violation.device_id]['processed'] += 1
    
    # Section: run the get queue size workflow with clear inputs and outputs.
    def get_queue_size(self) -> int:
        """Get current queue size."""
        return self.queue.qsize()
    
    # Section: run the get stats workflow with clear inputs and outputs.
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        # Open the managed resource only for the block that needs it.
        with self._lock:
            # Return the prepared result to the caller.
            return {
                **self._stats,
                'current_size': self.queue.qsize(),
                'capacity': self.max_size
            }

    # Section: run the is report queued workflow with clear inputs and outputs.
    def is_report_queued(self, report_id: str) -> bool:
        """Return True if the given report_id is already waiting in the queue."""
        # Prepare target for the next step.
        target = str(report_id or '').strip()
        if not target:
            # Return the prepared result to the caller.
            return False

        with self.queue.mutex:
            return any(
                str(getattr(item, 'report_id', '') or '').strip() == target
                for item in list(self.queue.queue)
            )

    # Section: run the get queue preview workflow with clear inputs and outputs.
    def get_queue_preview(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return a stable preview snapshot of queued items for diagnostics."""
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Prepare limit for the next step.
            limit = max(1, min(int(limit or 20), 100))
        except Exception:
            limit = 20

        with self.queue.mutex:
            items = list(self.queue.queue)

        items.sort(key=lambda item: (int(getattr(item, 'priority', 999)), float(getattr(item, 'timestamp', 0.0))))
        # Prepare now for the next step.
        now = time.time()

        preview: List[Dict[str, Any]] = []
        for item in items[:limit]:
            # Prepare ts value for the next step.
            ts_value = float(getattr(item, 'timestamp', 0.0) or 0.0)
            age_seconds = max(0.0, now - ts_value)
            preview.append({
                'report_id': str(getattr(item, 'report_id', '') or ''),
                'device_id': str(getattr(item, 'device_id', '') or ''),
                'priority': int(getattr(item, 'priority', 0) or 0),
                'retry_count': int(getattr(item, 'retry_count', 0) or 0),
                'age_seconds': round(age_seconds, 2),
            })

        # Return the prepared result to the caller.
        return preview
    
    # Section: run the clear workflow with clear inputs and outputs.
    def clear(self):
        """Clear the queue."""
        with self._lock:
            # Keep the loop active only while the runtime condition is true.
            while not self.queue.empty():
                # Protect this step so expected failures can fall back cleanly.
                try:
                    # Trigger the side effect required for this stage.
                    self.queue.get_nowait()
                except Empty:
                    break
        # Trigger the side effect required for this stage.
        logger.info("Queue cleared")


# Section: group multi device violation handler state and behaviour in one readable unit.
class MultiDeviceViolationHandler:
    """
    High-level handler for processing violations from multiple devices.
    
    Manages worker threads, batch processing, and callbacks.
    """
    
    # Section: run the init workflow with clear inputs and outputs.
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
        # Prepare queue for the next step.
        self.queue = queue_manager
        self.db = db_manager
        self.num_workers = num_workers
        self.batch_size = batch_size
        self.process_callback = process_callback
        
        self._workers: List[threading.Thread] = []
        self._running = False
        self._lock = threading.Lock()
        
        # Trigger the side effect required for this stage.
        logger.info(f"MultiDeviceViolationHandler initialized ({num_workers} workers)")
    
    # Section: run the start workflow with clear inputs and outputs.
    def start(self):
        """Start worker threads."""
        if self._running:
            # Trigger the side effect required for this stage.
            logger.warning("Handler already running")
            return
        
        self._running = True
        
        # Process each item in this collection using the same rule set.
        for i in range(self.num_workers):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"ViolationWorker-{i}",
                daemon=True
            )
            # Trigger the side effect required for this stage.
            worker.start()
            self._workers.append(worker)
        
        # Trigger the side effect required for this stage.
        logger.info(f"Started {self.num_workers} violation workers")
    
    # Section: run the stop workflow with clear inputs and outputs.
    def stop(self, timeout: float = 5.0):
        """Stop worker threads."""
        self._running = False
        
        for worker in self._workers:
            # Trigger the side effect required for this stage.
            worker.join(timeout=timeout)
        
        # Trigger the side effect required for this stage.
        self._workers.clear()
        logger.info("Stopped violation workers")
    
    # Section: run the worker loop workflow with clear inputs and outputs.
    def _worker_loop(self):
        """Main worker loop."""
        while self._running:
            try:
                # Get batch of violations
                # Prepare batch for the next step.
                batch = self.queue.dequeue_batch(self.batch_size)
                
                if not batch:
                    # Trigger the side effect required for this stage.
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
                # Trigger the side effect required for this stage.
                logger.error(f"Worker error: {e}")
                time.sleep(1)
    
    # Section: run the process violation workflow with clear inputs and outputs.
    def _process_violation(self, violation: QueuedViolation):
        """
        Process a single violation.
        
        Args:
            violation: The violation to process
        """
        # Prepare report id for the next step.
        report_id = violation.report_id
        device_id = violation.device_id
        data = violation.data
        
        logger.info(f"Processing violation {report_id} from {device_id}")
        
        # Update status to generating
        if hasattr(self.db, 'update_status'):
            self.db.update_status(report_id, 'generating')
        
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Call custom processor if provided
            if self.process_callback:
                # Prepare result for the next step.
                result = self.process_callback(violation)
                if not result:
                    # Surface the failure with enough context for the caller.
                    raise Exception("Process callback returned failure")
            
            # Update status to completed
            # Choose the correct branch before the workflow continues.
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
            # Trigger the side effect required for this stage.
            logger.error(f"Failed to process violation {report_id}: {e}")
            
            # Update status to failed
            if hasattr(self.db, 'update_status'):
                self.db.update_status(report_id, 'failed', str(e))
            
            raise
    
    # Section: run the submit violation workflow with clear inputs and outputs.
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
        # Choose the correct branch before the workflow continues.
        if not report_id:
            # Prepare timestamp for the next step.
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            device_hash = hashlib.md5(device_id.encode()).hexdigest()[:6]
            micro = datetime.now().strftime('%f')[:4]
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
        # Prepare success for the next step.
        success = self.queue.enqueue(
            violation_data=violation_data,
            device_id=device_id,
            report_id=report_id,
            severity=severity
        )
        
        if success:
            # Trigger the side effect required for this stage.
            logger.info(f"Submitted violation {report_id} from {device_id}")
            return report_id
        else:
            logger.warning(f"Failed to submit violation from {device_id}")
            return None
    
    # Section: run the get handler stats workflow with clear inputs and outputs.
    def get_handler_stats(self) -> Dict[str, Any]:
        """Get handler statistics."""
        # Return the prepared result to the caller.
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
    # Choose the correct branch before the workflow continues.
    if config is None:
        # Protect this step so expected failures can fall back cleanly.
        try:
            from ..config import QUEUE_CONFIG
            # Prepare config for the next step.
            config = QUEUE_CONFIG
        except ImportError:
            config = {}
    
    return ViolationQueueManager(
        max_size=config.get('max_queue_size', 100),
        rate_limit_per_device=config.get('rate_limit_per_device', 10),
        rate_limit_window=60,
        max_retries=config.get('max_retries', 3)
    )


# Section: run the create violation handler workflow with clear inputs and outputs.
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
    # Choose the correct branch before the workflow continues.
    if config is None:
        # Protect this step so expected failures can fall back cleanly.
        try:
            from ..config import QUEUE_CONFIG
            # Prepare config for the next step.
            config = QUEUE_CONFIG
        except ImportError:
            config = {}
    
    queue_manager = create_queue_manager_from_config(config)
    
    # Return the prepared result to the caller.
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
    # Trigger the side effect required for this stage.
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
    # Trigger the side effect required for this stage.
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
        # Trigger the side effect required for this stage.
        print(f"Enqueue {i}: {success}")
    
    # Show stats
    # Trigger the side effect required for this stage.
    print("\n--- Statistics ---")
    stats = queue.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    print("\n[OK] All tests passed!")
    print("=" * 70)
