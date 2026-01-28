"""
Performance Optimizations for Project Vantage
Implements pre-allocated buffers, garbage collection management, and performance monitoring
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import gc
import psutil
import threading
import time
from collections import deque
from dataclasses import dataclass
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """Performance metrics collection"""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_rss: int = 0  # Resident Set Size in bytes
    memory_vms: int = 0  # Virtual Memory Size in bytes
    gc_collections: int = 0
    gc_collected: int = 0
    gc_uncollectable: int = 0
    event_loop_lag: float = 0.0
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class BufferPool:
    """Pre-allocated buffer pool for reducing GC pressure"""
    
    def __init__(self, buffer_size: int = 1024, pool_size: int = 100):
        self.buffer_size = buffer_size
        self.pool_size = pool_size
        self._pool = deque()
        self._lock = threading.Lock()
        self._allocated_count = 0
        self._reuse_count = 0
        
        # Pre-allocate initial buffers
        self._preallocate_buffers()
    
    def _preallocate_buffers(self):
        """Pre-allocate buffers"""
        with self._lock:
            for _ in range(self.pool_size):
                buffer = bytearray(self.buffer_size)
                self._pool.append(buffer)
            self._allocated_count = self.pool_size
    
    def get_buffer(self) -> bytearray:
        """Get a buffer from the pool"""
        with self._lock:
            if self._pool:
                buffer = self._pool.popleft()
                self._reuse_count += 1
                return buffer
            else:
                # Pool exhausted, create new buffer
                self._allocated_count += 1
                return bytearray(self.buffer_size)
    
    def return_buffer(self, buffer: bytearray):
        """Return buffer to the pool"""
        with self._lock:
            if len(self._pool) < self.pool_size and len(buffer) == self.buffer_size:
                # Reset buffer content
                buffer[:] = b'\x00' * len(buffer)
                self._pool.append(buffer)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get buffer pool statistics"""
        with self._lock:
            return {
                'pool_size': self.pool_size,
                'available_buffers': len(self._pool),
                'allocated_count': self._allocated_count,
                'reuse_count': self._reuse_count,
                'hit_rate': self._reuse_count / max(1, self._allocated_count),
                'buffer_size': self.buffer_size
            }


class MemoryManager:
    """Memory management and garbage collection optimization"""
    
    def __init__(self):
        self.gc_thresholds = gc.get_threshold()
        self.gc_stats = {
            'collections': [0, 0, 0],
            'collected': 0,
            'uncollectable': 0,
            'last_gc_time': None
        }
        self.memory_monitoring_enabled = False
        self.memory_monitor_task = None
        self.memory_alert_threshold = 85.0  # Percent
        self.gc_interval = 30.0  # seconds
        
        # Performance tracking
        self._gc_start_time = None
        self._gc_durations = deque(maxlen=100)
    
    async def start_memory_monitoring(self):
        """Start memory monitoring"""
        if self.memory_monitoring_enabled:
            return
        
        self.memory_monitoring_enabled = True
        self.memory_monitor_task = asyncio.create_task(self._memory_monitor_loop())
        logger.info("Memory monitoring started")
    
    async def stop_memory_monitoring(self):
        """Stop memory monitoring"""
        self.memory_monitoring_enabled = False
        if self.memory_monitor_task:
            self.memory_monitor_task.cancel()
            try:
                await self.memory_monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Memory monitoring stopped")
    
    async def _memory_monitor_loop(self):
        """Memory monitoring loop"""
        while self.memory_monitoring_enabled:
            try:
                await self._check_memory_usage()
                await asyncio.sleep(5.0)  # Check every 5 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in memory monitor: {e}")
                await asyncio.sleep(10)
    
    async def _check_memory_usage(self):
        """Check current memory usage"""
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_percent = process.memory_percent()
            
            # Check if memory usage is above threshold
            if memory_percent > self.memory_alert_threshold:
                logger.warning(f"High memory usage detected: {memory_percent:.1f}%")
                await self._handle_high_memory(memory_percent, memory_info)
                
        except Exception as e:
            logger.error(f"Error checking memory usage: {e}")
    
    async def _handle_high_memory(self, memory_percent: float, memory_info):
        """Handle high memory usage situation"""
        try:
            # Force garbage collection
            await self.force_gc()
            
            # Log detailed memory information
            logger.info(f"Memory info after GC: RSS={memory_info.rss / 1024 / 1024:.1f}MB, "
                       f"VMS={memory_info.vms / 1024 / 1024:.1f}MB")
            
            # Check if we're still above threshold
            process = psutil.Process()
            if process.memory_percent() > self.memory_alert_threshold:
                logger.error("Memory usage still high after GC - potential memory leak")
                
        except Exception as e:
            logger.error(f"Error handling high memory: {e}")
    
    async def force_gc(self):
        """Force garbage collection"""
        try:
            # Record start time
            self._gc_start_time = time.time()
            
            # Perform full garbage collection
            collected = gc.collect()
            
            # Get GC stats
            stats = gc.get_stats()
            self.gc_stats['collections'] = [s['collections'] for s in stats]
            self.gc_stats['collected'] = collected
            self.gc_stats['uncollectable'] = sum(s['uncollectable'] for s in stats)
            self.gc_stats['last_gc_time'] = datetime.now()
            
            # Record duration
            if self._gc_start_time:
                duration = time.time() - self._gc_start_time
                self._gc_durations.append(duration)
                self._gc_start_time = None
            
            logger.debug(f"GC completed: collected {collected} objects")
            
        except Exception as e:
            logger.error(f"Error during forced GC: {e}")
    
    async def optimize_gc_thresholds(self, gen0: int = 700, gen1: int = 10, gen2: int = 10):
        """Optimize garbage collection thresholds"""
        try:
            gc.set_threshold(gen0, gen1, gen2)
            self.gc_thresholds = gc.get_threshold()
            logger.info(f"GC thresholds set to: {self.gc_thresholds}")
        except Exception as e:
            logger.error(f"Error setting GC thresholds: {e}")
    
    async def disable_gc(self):
        """Temporarily disable garbage collection"""
        gc.disable()
        logger.info("Garbage collection disabled")
    
    async def enable_gc(self):
        """Re-enable garbage collection"""
        gc.enable()
        logger.info("Garbage collection enabled")
    
    def get_gc_stats(self) -> Dict[str, Any]:
        """Get garbage collection statistics"""
        return {
            **self.gc_stats,
            'thresholds': self.gc_thresholds,
            'average_gc_duration': sum(self._gc_durations) / len(self._gc_durations) if self._gc_durations else 0,
            'gc_durations_count': len(self._gc_durations)
        }


class EventLoopMonitor:
    """Monitors event loop performance and detects blocking operations"""
    
    def __init__(self, lag_threshold: float = 0.1):  # 100ms threshold
        self.lag_threshold = lag_threshold
        self.monitoring_enabled = False
        self.monitor_task = None
        self.lag_history = deque(maxlen=1000)
        self.blocking_operations = []
        
    async def start_monitoring(self):
        """Start event loop monitoring"""
        if self.monitoring_enabled:
            return
            
        self.monitoring_enabled = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("Event loop monitoring started")
    
    async def stop_monitoring(self):
        """Stop event loop monitoring"""
        self.monitoring_enabled = False
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Event loop monitoring stopped")
    
    async def _monitor_loop(self):
        """Event loop monitoring loop"""
        while self.monitoring_enabled:
            try:
                start_time = time.perf_counter()
                await asyncio.sleep(0.1)  # Sample interval
                end_time = time.perf_counter()
                
                # Calculate actual vs expected sleep time
                actual_sleep = end_time - start_time
                expected_sleep = 0.1
                lag = actual_sleep - expected_sleep
                
                self.lag_history.append(lag)
                
                # Check for excessive lag
                if lag > self.lag_threshold:
                    logger.warning(f"Event loop lag detected: {lag:.3f}s")
                    self._record_blocking_operation(lag, start_time)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in event loop monitor: {e}")
    
    def _record_blocking_operation(self, lag: float, timestamp: float):
        """Record blocking operation details"""
        self.blocking_operations.append({
            'timestamp': datetime.fromtimestamp(timestamp).isoformat(),
            'lag_duration': lag,
            'stack_trace': self._get_current_stack()
        })
        
        # Keep only recent blocking operations
        if len(self.blocking_operations) > 50:
            self.blocking_operations = self.blocking_operations[-25:]
    
    def _get_current_stack(self) -> str:
        """Get current stack trace"""
        import traceback
        return ''.join(traceback.format_stack()[:-2])  # Exclude monitor frames
    
    def get_lag_stats(self) -> Dict[str, Any]:
        """Get event loop lag statistics"""
        if not self.lag_history:
            return {'samples': 0}
        
        lags = list(self.lag_history)
        return {
            'samples': len(lags),
            'average_lag': sum(lags) / len(lags),
            'max_lag': max(lags),
            'min_lag': min(lags),
            'lag_threshold_exceeded': len([l for l in lags if l > self.lag_threshold]),
            'blocking_operations_count': len(self.blocking_operations),
            'recent_lags': lags[-10:] if len(lags) > 10 else lags
        }


class PerformanceOptimizer:
    """
    Main performance optimization coordinator
    """
    
    def __init__(self):
        self.buffer_pools = {}
        self.memory_manager = MemoryManager()
        self.event_loop_monitor = EventLoopMonitor()
        self.metrics_history = deque(maxlen=1000)
        self.optimization_enabled = False
        
        # Initialize default buffer pools
        self._setup_default_buffer_pools()
    
    def _setup_default_buffer_pools(self):
        """Setup default buffer pools for common use cases"""
        # Small buffers for sensor data
        self.buffer_pools['sensor_small'] = BufferPool(buffer_size=256, pool_size=200)
        
        # Medium buffers for JSON messages
        self.buffer_pools['json_medium'] = BufferPool(buffer_size=1024, pool_size=100)
        
        # Large buffers for bulk data
        self.buffer_pools['bulk_large'] = BufferPool(buffer_size=8192, pool_size=20)
    
    async def start_optimization(self):
        """Start all performance optimizations"""
        if self.optimization_enabled:
            logger.warning("Performance optimization already enabled")
            return
        
        try:
            # Start monitoring services
            await self.memory_manager.start_memory_monitoring()
            await self.event_loop_monitor.start_monitoring()
            
            # Optimize GC settings
            await self.memory_manager.optimize_gc_thresholds(gen0=500, gen1=5, gen2=5)
            
            self.optimization_enabled = True
            logger.info("Performance optimization started")
            
        except Exception as e:
            logger.error(f"Failed to start performance optimization: {e}")
    
    async def stop_optimization(self):
        """Stop all performance optimizations"""
        try:
            await self.memory_manager.stop_memory_monitoring()
            await self.event_loop_monitor.stop_monitoring()
            self.optimization_enabled = False
            logger.info("Performance optimization stopped")
            
        except Exception as e:
            logger.error(f"Error stopping performance optimization: {e}")
    
    def get_buffer_pool(self, pool_name: str = 'sensor_small') -> BufferPool:
        """Get a buffer pool by name"""
        return self.buffer_pools.get(pool_name, self.buffer_pools['sensor_small'])
    
    @contextmanager
    def pooled_buffer(self, pool_name: str = 'sensor_small'):
        """Context manager for using pooled buffers"""
        pool = self.get_buffer_pool(pool_name)
        buffer = pool.get_buffer()
        try:
            yield buffer
        finally:
            pool.return_buffer(buffer)
    
    async def collect_performance_metrics(self) -> PerformanceMetrics:
        """Collect comprehensive performance metrics"""
        try:
            # Get system metrics
            process = psutil.Process()
            cpu_percent = process.cpu_percent()
            memory_info = process.memory_info()
            memory_percent = process.memory_percent()
            
            # Get GC stats
            gc_stats = self.memory_manager.get_gc_stats()
            
            # Get event loop stats
            loop_stats = self.event_loop_monitor.get_lag_stats()
            
            metrics = PerformanceMetrics(
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                memory_rss=memory_info.rss,
                memory_vms=memory_info.vms,
                gc_collections=sum(gc_stats.get('collections', [0, 0, 0])),
                gc_collected=gc_stats.get('collected', 0),
                gc_uncollectable=gc_stats.get('uncollectable', 0),
                event_loop_lag=loop_stats.get('average_lag', 0.0)
            )
            
            # Store in history
            self.metrics_history.append(metrics)
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error collecting performance metrics: {e}")
            return PerformanceMetrics()
    
    async def get_optimization_report(self) -> Dict[str, Any]:
        """Get comprehensive performance optimization report"""
        try:
            # Collect current metrics
            current_metrics = await self.collect_performance_metrics()
            
            # Get component stats
            buffer_stats = {
                name: pool.get_stats() 
                for name, pool in self.buffer_pools.items()
            }
            
            gc_stats = self.memory_manager.get_gc_stats()
            loop_stats = self.event_loop_monitor.get_lag_stats()
            
            return {
                'current_metrics': {
                    'cpu_percent': current_metrics.cpu_percent,
                    'memory_percent': current_metrics.memory_percent,
                    'memory_rss_mb': current_metrics.memory_rss / 1024 / 1024,
                    'event_loop_lag': current_metrics.event_loop_lag
                },
                'buffer_pools': buffer_stats,
                'garbage_collection': gc_stats,
                'event_loop': loop_stats,
                'optimization_enabled': self.optimization_enabled,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error generating optimization report: {e}")
            return {}
    
    async def force_cleanup(self):
        """Force cleanup of resources"""
        try:
            # Force garbage collection
            await self.memory_manager.force_gc()
            
            # Clear buffer pools (they'll re-preallocate as needed)
            for pool in self.buffer_pools.values():
                with pool._lock:
                    pool._pool.clear()
            
            logger.info("Performance cleanup completed")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")


# Global performance optimizer instance
global_optimizer = PerformanceOptimizer()