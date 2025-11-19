"""
Write-Ahead Logging (WAL) module for MachineA Battery Cart.

This module provides a LocalQueue that persists pending Firebase updates to disk
before attempting to upload them. If the Pi loses internet connection, the queue
is preserved and will retry on reconnection.
"""

import json
import os
import time
import logging
from typing import Any, Callable, Optional
from threading import Lock

class LocalQueue:
    """Thread-safe local queue for pending Firebase updates.
    
    All updates are written to disk before processing. If a write to Firebase
    fails, the item remains in the queue for retry on next process() call.
    """

    def __init__(self, queue_file: str = "firebase_queue.json", logger: Optional[logging.Logger] = None):
        """Initialize the LocalQueue.
        
        Args:
            queue_file: Path to the persistent queue file (JSON).
            logger: Optional logger for debug/info messages.
        """
        self.queue_file = queue_file
        self.logger = logger or logging.getLogger("WAL")
        self.lock = Lock()
        self.queue = []
        self._load_queue()

    def _load_queue(self):
        """Load queue from disk if it exists."""
        if os.path.exists(self.queue_file):
            try:
                with open(self.queue_file, "r") as f:
                    self.queue = json.load(f)
                self.logger.info(f"Loaded {len(self.queue)} queued items from {self.queue_file}")
            except Exception as e:
                self.logger.error(f"Failed to load queue from {self.queue_file}: {e}")
                self.queue = []
        else:
            self.queue = []

    def _save_queue(self):
        """Persist queue to disk."""
        try:
            with open(self.queue_file, "w") as f:
                json.dump(self.queue, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save queue to {self.queue_file}: {e}")

    def enqueue(self, path: str, data: Any, operation: str = "update"):
        """Add an item to the queue and persist to disk.
        
        Args:
            path: Firebase path (e.g., "BatteryList/BAT123").
            data: Data to write (dict or other JSON-serializable).
            operation: "update", "set", or "delete".
        """
        with self.lock:
            item = {
                "path": path,
                "data": data,
                "operation": operation,
                "enqueued_at": time.time(),
            }
            self.queue.append(item)
            self._save_queue()
            self.logger.debug(f"[WAL] Enqueued {operation} to {path}")

    def process(self, firebase_ref: Any, logger: Optional[logging.Logger] = None) -> int:
        """Attempt to process all queued items.
        
        For each queued item, try to write it to Firebase. If successful,
        remove it from the queue. If it fails, leave it in the queue for retry.
        
        Args:
            firebase_ref: Firebase reference object (from firebase_admin.db.reference()).
            logger: Optional logger for operation output.
        
        Returns:
            Number of items successfully processed.
        """
        if logger is None:
            logger = self.logger
        
        processed = 0
        failed = 0
        
        with self.lock:
            items_to_process = list(self.queue)
        
        if not items_to_process:
            logger.debug("[WAL] Queue is empty; nothing to process.")
            return 0
        
        logger.info(f"[WAL] Processing {len(items_to_process)} queued item(s)...")
        
        remaining = []
        for item in items_to_process:
            path = item.get("path")
            data = item.get("data")
            operation = item.get("operation", "update")
            enqueued_at = item.get("enqueued_at")
            
            try:
                if operation == "update":
                    firebase_ref.child(path).update(data)
                elif operation == "set":
                    firebase_ref.child(path).set(data)
                elif operation == "delete":
                    firebase_ref.child(path).delete()
                else:
                    logger.warning(f"[WAL] Unknown operation '{operation}' for {path}; skipping.")
                    continue
                
                age = time.time() - enqueued_at
                logger.info(f"[WAL] ✓ {operation} to {path} (queued for {age:.1f}s)")
                processed += 1
            except Exception as e:
                logger.warning(f"[WAL] ✗ {operation} to {path} failed: {e} (will retry)")
                failed += 1
                remaining.append(item)
        
        # Update queue with items that failed
        with self.lock:
            self.queue = remaining
            self._save_queue()
        
        if processed > 0:
            logger.info(f"[WAL] Successfully processed {processed} item(s); {len(remaining)} still queued.")
        if remaining:
            logger.warning(f"[WAL] {len(remaining)} item(s) remain in queue and will be retried.")
        
        return processed

    def size(self) -> int:
        """Return the current queue size."""
        with self.lock:
            return len(self.queue)

    def clear(self):
        """Clear the queue and remove the queue file."""
        with self.lock:
            self.queue = []
            self._save_queue()
        if os.path.exists(self.queue_file):
            try:
                os.remove(self.queue_file)
                self.logger.info(f"Cleared queue file: {self.queue_file}")
            except Exception as e:
                self.logger.error(f"Failed to delete queue file: {e}")

    def get_queue_contents(self) -> list:
        """Return a copy of the current queue contents (for debugging)."""
        with self.lock:
            return [dict(item) for item in self.queue]
