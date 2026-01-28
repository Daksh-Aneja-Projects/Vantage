"""
Global Crash Handler for Project Vantage
Logs stack traces to a local encrypted file with secure storage
"""

import logging
import traceback
import json
import os
from datetime import datetime
from typing import Dict, Any, Optional
import asyncio
from pathlib import Path
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
import secrets
import threading
from queue import Queue, Empty

logger = logging.getLogger(__name__)

class CrashHandler:
    """
    Global crash handler that logs stack traces to encrypted local files
    """
    
    def __init__(self, log_directory: str = "./logs", encryption_password: str = None):
        self.log_directory = Path(log_directory)
        self.encryption_password = encryption_password or os.getenv('CRASH_LOG_PASSWORD', 'vantage_default_key')
        self.encryption_key = self._generate_key_from_password(self.encryption_password)
        self.cipher_suite = Fernet(self.encryption_key)
        
        # Create log directory if it doesn't exist
        self.log_directory.mkdir(parents=True, exist_ok=True)
        
        # Thread-safe queue for crash logs
        self.crash_queue = Queue()
        self.is_running = False
        self.worker_thread = None
        
        # Statistics
        self.stats = {
            'crashes_logged': 0,
            'encryption_failures': 0,
            'write_failures': 0
        }
        
    def _generate_key_from_password(self, password: str) -> bytes:
        """Generate encryption key from password"""
        salt = b'vantage_crash_log_salt'  # Fixed salt for consistency
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key
    
    def start_worker(self):
        """Start the background worker to process crash logs"""
        if not self.is_running:
            self.is_running = True
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()
            logger.info("Crash handler worker started")
    
    def stop_worker(self):
        """Stop the background worker"""
        self.is_running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=2.0)  # Wait up to 2 seconds
            logger.info("Crash handler worker stopped")
    
    def _worker_loop(self):
        """Background worker loop to process crash logs"""
        while self.is_running:
            try:
                # Get crash info from queue with timeout
                try:
                    crash_info = self.crash_queue.get(timeout=1.0)
                    self._write_crash_log(crash_info)
                    self.crash_queue.task_done()
                except Empty:
                    continue  # Timeout, continue loop
                    
            except Exception as e:
                logger.error(f"Error in crash handler worker: {e}")
    
    def handle_exception(self, exc_type, exc_value, exc_traceback, context: Optional[Dict[str, Any]] = None):
        """
        Handle an exception and log it securely
        """
        try:
            # Format the exception information
            crash_info = {
                'timestamp': datetime.now().isoformat(),
                'exception_type': exc_type.__name__ if exc_type else 'Unknown',
                'exception_message': str(exc_value) if exc_value else 'No message',
                'traceback': ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback)),
                'context': context or {},
                'process_id': os.getpid(),
                'thread_id': threading.get_ident()
            }
            
            # Add to queue for background processing
            self.crash_queue.put(crash_info)
            
            # Update stats
            self.stats['crashes_logged'] += 1
            
            # Also log to standard logger for immediate visibility
            logger.error(f"Crash logged: {exc_type.__name__}: {exc_value}", exc_info=(exc_type, exc_value, exc_traceback))
            
        except Exception as e:
            logger.error(f"Failed to handle exception in crash handler: {e}")
            self.stats['write_failures'] += 1
    
    def _write_crash_log(self, crash_info: Dict[str, Any]):
        """Write crash log to encrypted file"""
        try:
            # Prepare crash data
            crash_data = {
                'version': '1.0',
                'crash_info': crash_info
            }
            
            # Serialize to JSON
            json_data = json.dumps(crash_data, indent=2)
            
            # Encrypt the data
            try:
                encrypted_data = self.cipher_suite.encrypt(json_data.encode())
            except Exception as e:
                logger.error(f"Encryption failed: {e}")
                self.stats['encryption_failures'] += 1
                # Fallback: write unencrypted if encryption fails (still better than losing the log)
                encrypted_data = json_data.encode()
                is_encrypted = False
            else:
                is_encrypted = True
            
            # Create filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"crash_{timestamp}.enc" if is_encrypted else f"crash_{timestamp}.log"
            filepath = self.log_directory / filename
            
            # Write encrypted data to file
            with open(filepath, 'wb') as f:
                f.write(encrypted_data)
            
            logger.info(f"Crash log written to: {filepath}")
            
        except Exception as e:
            logger.error(f"Failed to write crash log: {e}")
            self.stats['write_failures'] += 1
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get crash handler statistics"""
        return {
            'stats': self.stats.copy(),
            'queue_size': self.crash_queue.qsize(),
            'is_running': self.is_running,
            'timestamp': datetime.now().isoformat()
        }
    
    def cleanup_old_logs(self, days_to_keep: int = 30):
        """Remove crash logs older than specified days"""
        try:
            cutoff_time = datetime.now().timestamp() - (days_to_keep * 24 * 3600)
            
            files_removed = 0
            for log_file in self.log_directory.glob("crash_*"):
                if log_file.stat().st_mtime < cutoff_time:
                    log_file.unlink()
                    files_removed += 1
            
            logger.info(f"Cleaned up {files_removed} old crash logs")
            return files_removed
            
        except Exception as e:
            logger.error(f"Failed to clean up old crash logs: {e}")
            return 0
    
    def decrypt_crash_log(self, filepath: str) -> Optional[Dict[str, Any]]:
        """Decrypt and return crash log content (for debugging purposes)"""
        try:
            with open(filepath, 'rb') as f:
                encrypted_data = f.read()
            
            # Try to decrypt
            try:
                decrypted_data = self.cipher_suite.decrypt(encrypted_data)
                return json.loads(decrypted_data.decode())
            except Exception:
                # If decryption fails, assume it wasn't encrypted
                return json.loads(encrypted_data.decode())
                
        except Exception as e:
            logger.error(f"Failed to decrypt crash log {filepath}: {e}")
            return None


# Global crash handler instance
_global_crash_handler = None

def get_crash_handler() -> CrashHandler:
    """Get the global crash handler instance"""
    global _global_crash_handler
    if _global_crash_handler is None:
        _global_crash_handler = CrashHandler()
        _global_crash_handler.start_worker()
    return _global_crash_handler

def handle_exception(exc_type, exc_value, exc_traceback, context: Optional[Dict[str, Any]] = None):
    """Convenience function to handle exceptions globally"""
    handler = get_crash_handler()
    handler.handle_exception(exc_type, exc_value, exc_traceback, context)

def install_global_handler():
    """Install the crash handler as the global exception handler"""
    def global_except_hook(exc_type, exc_value, exc_traceback):
        handle_exception(exc_type, exc_value, exc_traceback)
    
    import sys
    sys.excepthook = global_except_hook
    
    # Also handle async exceptions
    def async_exception_handler(loop, context):
        exc = context.get('exception')
        if exc:
            exc_type = type(exc)
            exc_value = exc
            exc_traceback = exc.__traceback__
            handle_exception(exc_type, exc_value, exc_traceback, context=context)
    
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(async_exception_handler)


# Context manager for handling exceptions in specific blocks
class CrashHandlerContext:
    """Context manager for handling exceptions in specific code blocks"""
    
    def __init__(self, context: Optional[Dict[str, Any]] = None, reraise: bool = True):
        self.context = context or {}
        self.reraise = reraise
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_value, exc_traceback):
        if exc_type is not None:
            handle_exception(exc_type, exc_value, exc_traceback, self.context)
            return not self.reraise  # Return True to suppress the exception if reraise is False
        return False  # Don't suppress if no exception occurred