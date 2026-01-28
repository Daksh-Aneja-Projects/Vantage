"""
Error handling utilities for Project Vantage
Provides centralized error handling, retry logic, circuit breaker patterns, and crash reporting
"""

# Import the crash handler
try:
    from .crash_handler import handle_exception as handle_crash, install_global_handler
except ImportError:
    # Define fallback functions if crash handler is not available
    def handle_crash(exc_type, exc_value, exc_traceback, context=None):
        print(f"Crash reported: {exc_type.__name__}: {exc_value}")
    
    def install_global_handler():
        pass

import asyncio
import logging
import time
from typing import Callable, Any, Optional, Dict, Type
from datetime import datetime, timedelta
from functools import wraps
import random
from enum import Enum


logger = logging.getLogger(__name__)


class NetworkError(Exception):
    """Custom exception for network-related errors"""
    def __init__(self, message: str, endpoint: str = None, status_code: int = None):
        super().__init__(message)
        self.endpoint = endpoint
        self.status_code = status_code
        self.timestamp = datetime.now().isoformat()


class SensorError(Exception):
    """Custom exception for sensor-related errors"""
    def __init__(self, message: str, sensor_id: str = None, sensor_type: str = None):
        super().__init__(message)
        self.sensor_id = sensor_id
        self.sensor_type = sensor_type
        self.timestamp = datetime.now().isoformat()


class InferenceError(Exception):
    """Custom exception for ML inference-related errors"""
    def __init__(self, message: str, model_name: str = None, input_shape: tuple = None):
        super().__init__(message)
        self.model_name = model_name
        self.input_shape = input_shape
        self.timestamp = datetime.now().isoformat()


class SecurityError(Exception):
    """Custom exception for security-related errors"""
    def __init__(self, message: str, security_context: str = None):
        super().__init__(message)
        self.security_context = security_context
        self.timestamp = datetime.now().isoformat()


class ValidationError(Exception):
    """Custom exception for validation errors"""
    def __init__(self, message: str, field_name: str = None, value: Any = None):
        super().__init__(message)
        self.field_name = field_name
        self.value = value
        self.timestamp = datetime.now().isoformat()


class ErrorCategory(Enum):
    """Categories of errors for better classification"""
    NETWORK_ERROR = "network_error"
    TIMEOUT_ERROR = "timeout_error"
    VALIDATION_ERROR = "validation_error"
    RESOURCE_ERROR = "resource_error"
    SECURITY_ERROR = "security_error"
    BUSINESS_LOGIC_ERROR = "business_logic_error"
    UNKNOWN_ERROR = "unknown_error"


class CircuitBreakerState(Enum):
    """States of the circuit breaker"""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Circuit breaker implementation for fault tolerance"""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60, 
                 expected_exception_types: tuple = (Exception,)):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception_types = expected_exception_types
        
        self.failure_count = 0
        self.last_failure_time = None
        self.state = CircuitBreakerState.CLOSED
        self.next_attempt_time = None
        self.success_count = 0
        self.half_open_success_threshold = 1  # Number of successes to close the circuit
        
        self.lock = asyncio.Lock()
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute a function with circuit breaker protection"""
        async with self.lock:
            if self.state == CircuitBreakerState.OPEN:
                if self._should_attempt_reset():
                    self.state = CircuitBreakerState.HALF_OPEN
                    logger.info(f"Circuit breaker transitioning to HALF_OPEN for {func.__name__}")
                else:
                    raise Exception(f"Circuit breaker is OPEN for {func.__name__}")
            
            try:
                result = await func(*args, **kwargs)
                
                # Success path
                if self.state == CircuitBreakerState.HALF_OPEN:
                    self.success_count += 1
                    if self.success_count >= self.half_open_success_threshold:
                        await self._close_circuit()
                else:
                    # Reset counters on success when circuit is closed
                    await self._on_success()
                
                return result
                
            except self.expected_exception_types as e:
                await self._on_failure(type(e).__name__)
                raise e
            except Exception as e:
                # Unexpected exceptions also count as failures
                await self._on_failure(f"unexpected_{type(e).__name__}")
                raise e
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt a reset"""
        if self.next_attempt_time is None:
            return True
        return datetime.now() >= self.next_attempt_time
    
    async def _on_success(self):
        """Called when a call succeeds"""
        self.failure_count = 0
        self.last_failure_time = None
        self.success_count = 0
        self.state = CircuitBreakerState.CLOSED
    
    async def _on_failure(self, error_type: str):
        """Called when a call fails"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN
            self.next_attempt_time = datetime.now() + timedelta(seconds=self.recovery_timeout)
            logger.warning(f"Circuit breaker OPENED for {error_type} after {self.failure_count} failures")
    
    async def _close_circuit(self):
        """Close the circuit after successful half-open attempts"""
        self.failure_count = 0
        self.last_failure_time = None
        self.success_count = 0
        self.state = CircuitBreakerState.CLOSED
        logger.info("Circuit breaker CLOSED after successful half-open attempts")
    
    def get_status(self) -> Dict[str, Any]:
        """Get the current status of the circuit breaker"""
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "next_attempt_time": self.next_attempt_time.isoformat() if self.next_attempt_time else None,
            "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None
        }


class ExponentialBackoff:
    """Exponential backoff implementation with jitter"""
    
    def __init__(self, initial_delay: float = 1.0, max_delay: float = 60.0, 
                 multiplier: float = 2.0, jitter_factor: float = 0.1):
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.jitter_factor = jitter_factor
        self.current_delay = initial_delay
    
    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay with exponential backoff and jitter"""
        exp_delay = min(self.initial_delay * (self.multiplier ** attempt), self.max_delay)
        # Add jitter to prevent thundering herd
        jitter = random.uniform(-self.jitter_factor * exp_delay, self.jitter_factor * exp_delay)
        return max(0.0, exp_delay + jitter)
    
    def reset(self):
        """Reset the backoff to initial delay"""
        self.current_delay = self.initial_delay
    
    def next_delay(self) -> float:
        """Get the next delay and increment for next attempt"""
        delay = self.calculate_delay(0)  # We'll recalculate based on attempt count
        self.current_delay = min(self.current_delay * self.multiplier, self.max_delay)
        return delay


def retry_with_backoff(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    multiplier: float = 2.0,
    exceptions: tuple = (Exception,),
    circuit_breaker: Optional[CircuitBreaker] = None
):
    """
    Decorator for retrying functions with exponential backoff
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            backoff = ExponentialBackoff(
                initial_delay=initial_delay,
                max_delay=max_delay,
                multiplier=multiplier
            )
            
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    if circuit_breaker:
                        # Use circuit breaker if provided
                        return await circuit_breaker.call(func, *args, **kwargs)
                    else:
                        # Direct call with retry
                        return await func(*args, **kwargs)
                        
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:  # Not the last attempt
                        delay = backoff.calculate_delay(attempt)
                        logger.warning(
                            f"Attempt {attempt + 1} failed for {func.__name__}: {str(e)}. "
                            f"Retrying in {delay:.2f}s..."
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"All {max_attempts} attempts failed for {func.__name__}. "
                            f"Last error: {str(e)}"
                        )
            
            # If we get here, all attempts failed
            raise last_exception
        
        return wrapper
    return decorator


def categorize_error(exception: Exception) -> ErrorCategory:
    """Categorize an exception into a specific category"""
    exc_type = type(exception)
    
    if exc_type.__name__ in ['ConnectionError', 'TimeoutError', 'ConnectionRefusedError', 'ConnectTimeout']:
        return ErrorCategory.NETWORK_ERROR
    elif exc_type.__name__ in ['TimeoutError', 'asyncio.TimeoutError']:
        return ErrorCategory.TIMEOUT_ERROR
    elif exc_type.__name__ in ['ValidationError', 'ValueError', 'TypeError']:
        return ErrorCategory.VALIDATION_ERROR
    elif exc_type.__name__ in ['MemoryError', 'OSError']:
        return ErrorCategory.RESOURCE_ERROR
    elif exc_type.__name__ in ['PermissionError', 'SecurityError']:
        return ErrorCategory.SECURITY_ERROR
    elif 'Business' in exc_type.__name__ or 'Logic' in exc_type.__name__:
        return ErrorCategory.BUSINESS_LOGIC_ERROR
    else:
        return ErrorCategory.UNKNOWN_ERROR


def log_error(
    exception: Exception, 
    context: Optional[Dict[str, Any]] = None,
    level: int = logging.ERROR,
    is_critical: bool = False
) -> Dict[str, Any]:
    """
    Log an error with structured information
    """
    error_category = categorize_error(exception)
    
    # Create structured error info with additional fields based on exception type
    error_info = {
        'timestamp': datetime.now().isoformat(),
        'error_type': type(exception).__name__,
        'error_message': str(exception),
        'error_category': error_category.value,
        'context': context or {},
        'traceback': None  # In a real implementation, you'd add traceback info
    }
    
    # Add specific attributes from custom exceptions
    if hasattr(exception, 'timestamp'):
        error_info['exception_timestamp'] = exception.timestamp
    if hasattr(exception, 'endpoint'):
        error_info['endpoint'] = exception.endpoint
    if hasattr(exception, 'status_code'):
        error_info['status_code'] = exception.status_code
    if hasattr(exception, 'sensor_id'):
        error_info['sensor_id'] = exception.sensor_id
    if hasattr(exception, 'sensor_type'):
        error_info['sensor_type'] = exception.sensor_type
    if hasattr(exception, 'model_name'):
        error_info['model_name'] = exception.model_name
    if hasattr(exception, 'field_name'):
        error_info['field_name'] = exception.field_name
    if hasattr(exception, 'value'):
        error_info['value'] = exception.value
    
    # Log with structured format for better observability
    logger.log(level, f"{error_info['error_type']} occurred: {error_info['error_message']}", extra=error_info)
    
    # For critical errors, also log to crash handler
    if is_critical:
        import sys
        handle_crash(type(exception), exception, exception.__traceback__, context)
    
    return error_info


class GlobalErrorHandler:
    """Global error handler for the application"""
    
    def __init__(self):
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.error_stats = {
            'total_errors': 0,
            'errors_by_category': {category.value: 0 for category in ErrorCategory},
            'last_error_time': None
        }
        self.logger = logging.getLogger(__name__)
    
    def get_or_create_circuit_breaker(
        self, 
        operation_name: str, 
        failure_threshold: int = 5, 
        recovery_timeout: int = 60
    ) -> CircuitBreaker:
        """Get or create a circuit breaker for an operation"""
        if operation_name not in self.circuit_breakers:
            self.circuit_breakers[operation_name] = CircuitBreaker(
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout
            )
        return self.circuit_breakers[operation_name]
    
    def handle_error(
        self, 
        exception: Exception, 
        context: Optional[Dict[str, Any]] = None,
        operation_name: Optional[str] = None,
        is_critical: bool = False
    ) -> Dict[str, Any]:
        """Handle an error globally"""
        # Determine if this is a critical error (system-level failures)
        if is_critical:
            error_info = log_error(exception, context, is_critical=True)
        else:
            # Consider certain error types as critical automatically
            exc_type = type(exception).__name__
            is_critical_auto = any(critical in exc_type.lower() for critical in ['memory', 'stackoverflow', 'segmentation', 'fatal', 'system'])
            error_info = log_error(exception, context, is_critical=is_critical_auto)
        
        # Update stats
        self.error_stats['total_errors'] += 1
        category = categorize_error(exception)
        self.error_stats['errors_by_category'][category.value] += 1
        self.error_stats['last_error_time'] = datetime.now().isoformat()
        
        # If operation name provided, update its circuit breaker
        if operation_name:
            cb = self.get_or_create_circuit_breaker(operation_name)
            # The circuit breaker is updated when called via the decorator
        
        return error_info
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """Get error statistics"""
        return {
            'timestamp': datetime.now().isoformat(),
            **self.error_stats
        }


# Global error handler instance
global_error_handler = GlobalErrorHandler()


def handle_and_retry(
    max_attempts: int = 3,
    operation_name: Optional[str] = None,
    **retry_kwargs
):
    """
    Decorator that combines error handling with retry logic
    """
    def decorator(func):
        circuit_breaker = None
        if operation_name:
            circuit_breaker = global_error_handler.get_or_create_circuit_breaker(operation_name)
        
        retry_decorator = retry_with_backoff(
            max_attempts=max_attempts,
            circuit_breaker=circuit_breaker,
            **retry_kwargs
        )(func)
        
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await retry_decorator(*args, **kwargs)
            except Exception as e:
                # Handle the error globally
                context = {
                    'function_name': func.__name__,
                    'args': str(args)[:200],  # Limit length for logging
                    'kwargs_keys': list(kwargs.keys())
                }
                global_error_handler.handle_error(e, context, operation_name)
                raise
        
        return wrapper
    return decorator


# Convenience functions
def safe_execute(
    coro,
    default_return=None,
    log_error: bool = True,
    error_context: Optional[Dict[str, Any]] = None
):
    """
    Safely execute a coroutine, catching exceptions and returning a default value
    """
    async def wrapper():
        try:
            return await coro
        except Exception as e:
            if log_error:
                global_error_handler.handle_error(e, error_context)
            return default_return
    
    return wrapper()