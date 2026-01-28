"""
Supervisor Pattern for Project Vantage
Implements fault tolerance, error handling, and automatic component restart
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional, Callable, Coroutine
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
import traceback
import time
from collections import defaultdict

logger = logging.getLogger(__name__)


class ComponentHealth(Enum):
    """Component health states"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    RESTARTING = "restarting"
    STOPPED = "stopped"


class RestartPolicy(Enum):
    """Component restart policies"""
    NEVER = "never"
    ON_FAILURE = "on_failure"
    ALWAYS = "always"
    EXPONENTIAL_BACKOFF = "exponential_backoff"


@dataclass
class ComponentStatus:
    """Status information for a supervised component"""
    component_id: str
    health: ComponentHealth
    last_heartbeat: datetime
    failure_count: int
    restart_count: int
    error_messages: List[str]
    startup_time: datetime
    last_restart: Optional[datetime] = None


@dataclass
class RestartStrategy:
    """Restart strategy configuration"""
    policy: RestartPolicy
    max_restarts: int = 5
    base_delay: float = 1.0  # seconds
    max_delay: float = 60.0  # seconds
    reset_window: float = 300.0  # seconds


class ComponentSupervisor:
    """
    Supervises components and manages their lifecycle, restarts, and health monitoring
    """
    
    def __init__(self):
        self.components: Dict[str, Any] = {}
        self.statuses: Dict[str, ComponentStatus] = {}
        self.restart_strategies: Dict[str, RestartStrategy] = {}
        self.health_checkers: Dict[str, Callable] = {}
        self.failure_callbacks: Dict[str, List[Callable]] = defaultdict(list)
        self.recovery_callbacks: Dict[str, List[Callable]] = defaultdict(list)
        
        # Supervisor configuration
        self.health_check_interval = 5.0  # seconds
        self.is_monitoring = False
        self.monitoring_task = None
        
        # Statistics
        self.supervisor_stats = {
            'total_components': 0,
            'healthy_components': 0,
            'failed_components': 0,
            'total_restarts': 0,
            'uptime_seconds': 0,
            'start_time': datetime.now()
        }
    
    async def register_component(self, component_id: str, component: Any,
                               restart_strategy: RestartStrategy = None,
                               health_checker: Callable = None) -> bool:
        """Register a component for supervision"""
        try:
            self.components[component_id] = component
            self.restart_strategies[component_id] = restart_strategy or RestartStrategy(
                policy=RestartPolicy.EXPONENTIAL_BACKOFF
            )
            
            if health_checker:
                self.health_checkers[component_id] = health_checker
            
            # Initialize status
            self.statuses[component_id] = ComponentStatus(
                component_id=component_id,
                health=ComponentHealth.HEALTHY,
                last_heartbeat=datetime.now(),
                failure_count=0,
                restart_count=0,
                error_messages=[],
                startup_time=datetime.now()
            )
            
            self.supervisor_stats['total_components'] += 1
            logger.info(f"Component registered for supervision: {component_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register component {component_id}: {e}")
            return False
    
    async def start_supervision(self):
        """Start the supervision monitoring"""
        if self.is_monitoring:
            logger.warning("Supervisor already running")
            return
        
        self.is_monitoring = True
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        logger.info("Component supervision started")
    
    async def stop_supervision(self):
        """Stop the supervision monitoring"""
        self.is_monitoring = False
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        logger.info("Component supervision stopped")
    
    async def _monitoring_loop(self):
        """Main monitoring loop"""
        while self.is_monitoring:
            try:
                await self._perform_health_checks()
                await self._check_component_heartbeats()
                await self._update_statistics()
                await asyncio.sleep(self.health_check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in supervision loop: {e}")
                await asyncio.sleep(1)
    
    async def _perform_health_checks(self):
        """Perform health checks on all components"""
        for component_id, health_checker in self.health_checkers.items():
            try:
                is_healthy = await health_checker()
                await self._update_component_health(component_id, is_healthy)
                
            except Exception as e:
                logger.error(f"Health check failed for {component_id}: {e}")
                await self._update_component_health(component_id, False, str(e))
    
    async def _check_component_heartbeats(self):
        """Check component heartbeats and detect stale components"""
        current_time = datetime.now()
        stale_threshold = 30.0  # seconds
        
        for component_id, status in self.statuses.items():
            time_since_heartbeat = (current_time - status.last_heartbeat).total_seconds()
            
            if time_since_heartbeat > stale_threshold:
                logger.warning(f"Component {component_id} heartbeat stale ({time_since_heartbeat:.1f}s)")
                await self._handle_stale_component(component_id)
    
    async def _update_component_health(self, component_id: str, is_healthy: bool, 
                                     error_message: str = None):
        """Update component health status"""
        if component_id not in self.statuses:
            return
        
        status = self.statuses[component_id]
        old_health = status.health
        
        if is_healthy:
            status.health = ComponentHealth.HEALTHY
            status.last_heartbeat = datetime.now()
            status.error_messages.clear()
            if old_health != ComponentHealth.HEALTHY:
                await self._trigger_recovery_callbacks(component_id)
        else:
            status.health = ComponentHealth.FAILED
            status.failure_count += 1
            if error_message:
                status.error_messages.append(f"[{datetime.now().isoformat()}] {error_message}")
                # Keep only last 10 error messages
                if len(status.error_messages) > 10:
                    status.error_messages = status.error_messages[-10:]
            
            await self._trigger_failure_callbacks(component_id)
            await self._handle_component_failure(component_id)
    
    async def _handle_stale_component(self, component_id: str):
        """Handle component that hasn't sent heartbeat"""
        await self._update_component_health(component_id, False, "Heartbeat timeout")
    
    async def _handle_component_failure(self, component_id: str):
        """Handle component failure according to restart strategy"""
        if component_id not in self.restart_strategies:
            return
        
        strategy = self.restart_strategies[component_id]
        status = self.statuses[component_id]
        
        # Check if we should restart based on policy
        should_restart = False
        restart_delay = 0.0
        
        if strategy.policy == RestartPolicy.ALWAYS:
            should_restart = True
        elif strategy.policy == RestartPolicy.ON_FAILURE:
            should_restart = True
        elif strategy.policy == RestartPolicy.EXPONENTIAL_BACKOFF:
            # Check if we're within restart limits
            if status.restart_count < strategy.max_restarts:
                should_restart = True
                # Calculate exponential backoff delay
                restart_delay = min(
                    strategy.base_delay * (2 ** status.restart_count),
                    strategy.max_delay
                )
        
        if should_restart:
            logger.info(f"Restarting component {component_id} in {restart_delay:.1f}s "
                       f"(attempt {status.restart_count + 1}/{strategy.max_restarts})")
            
            # Schedule restart after delay
            asyncio.create_task(self._delayed_restart(component_id, restart_delay))
        else:
            logger.error(f"Component {component_id} failed permanently - restart limit exceeded")
            status.health = ComponentHealth.STOPPED
    
    async def _delayed_restart(self, component_id: str, delay: float):
        """Restart component after specified delay"""
        try:
            status = self.statuses[component_id]
            status.health = ComponentHealth.RESTARTING
            status.last_restart = datetime.now()
            
            await asyncio.sleep(delay)
            
            success = await self._restart_component(component_id)
            if success:
                status.restart_count += 1
                self.supervisor_stats['total_restarts'] += 1
                logger.info(f"Component {component_id} restarted successfully")
            else:
                status.health = ComponentHealth.FAILED
                logger.error(f"Failed to restart component {component_id}")
                
        except Exception as e:
            logger.error(f"Error during delayed restart of {component_id}: {e}")
            if component_id in self.statuses:
                self.statuses[component_id].health = ComponentHealth.FAILED
    
    async def _restart_component(self, component_id: str) -> bool:
        """Attempt to restart a component"""
        try:
            if component_id not in self.components:
                return False
            
            component = self.components[component_id]
            
            # Try to stop component gracefully
            if hasattr(component, 'stop'):
                try:
                    await component.stop()
                except Exception as e:
                    logger.warning(f"Error stopping component {component_id}: {e}")
            
            # Try to start component
            if hasattr(component, 'start'):
                await component.start()
            elif hasattr(component, 'initialize'):
                await component.initialize()
            else:
                # For simple components, just recreate them
                logger.warning(f"No restart method found for component {component_id}")
                return False
            
            # Update status
            if component_id in self.statuses:
                self.statuses[component_id].health = ComponentHealth.HEALTHY
                self.statuses[component_id].last_heartbeat = datetime.now()
            
            return True
            
        except Exception as e:
            logger.error(f"Error restarting component {component_id}: {e}")
            logger.error(traceback.format_exc())
            return False
    
    async def _trigger_failure_callbacks(self, component_id: str):
        """Trigger registered failure callbacks"""
        for callback in self.failure_callbacks[component_id]:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(component_id)
                else:
                    callback(component_id)
            except Exception as e:
                logger.error(f"Error in failure callback for {component_id}: {e}")
    
    async def _trigger_recovery_callbacks(self, component_id: str):
        """Trigger registered recovery callbacks"""
        for callback in self.recovery_callbacks[component_id]:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(component_id)
                else:
                    callback(component_id)
            except Exception as e:
                logger.error(f"Error in recovery callback for {component_id}: {e}")
    
    def register_failure_callback(self, component_id: str, callback: Callable):
        """Register callback to be called when component fails"""
        self.failure_callbacks[component_id].append(callback)
        logger.debug(f"Failure callback registered for {component_id}")
    
    def register_recovery_callback(self, component_id: str, callback: Callable):
        """Register callback to be called when component recovers"""
        self.recovery_callbacks[component_id].append(callback)
        logger.debug(f"Recovery callback registered for {component_id}")
    
    async def update_heartbeat(self, component_id: str):
        """Update heartbeat for a component"""
        if component_id in self.statuses:
            self.statuses[component_id].last_heartbeat = datetime.now()
    
    async def get_component_status(self, component_id: str) -> Optional[ComponentStatus]:
        """Get status for a specific component"""
        return self.statuses.get(component_id)
    
    async def get_all_statuses(self) -> Dict[str, ComponentStatus]:
        """Get statuses for all components"""
        return self.statuses.copy()
    
    async def get_supervisor_stats(self) -> Dict[str, Any]:
        """Get supervisor statistics"""
        current_time = datetime.now()
        uptime = (current_time - self.supervisor_stats['start_time']).total_seconds()
        
        healthy_count = sum(1 for status in self.statuses.values() 
                          if status.health == ComponentHealth.HEALTHY)
        failed_count = sum(1 for status in self.statuses.values() 
                         if status.health in [ComponentHealth.FAILED, ComponentHealth.STOPPED])
        
        return {
            'supervisor_stats': {
                **self.supervisor_stats,
                'uptime_seconds': uptime,
                'healthy_components': healthy_count,
                'failed_components': failed_count
            },
            'component_statuses': {
                cid: {
                    'health': status.health.value,
                    'failure_count': status.failure_count,
                    'restart_count': status.restart_count,
                    'last_heartbeat': status.last_heartbeat.isoformat(),
                    'uptime': (current_time - status.startup_time).total_seconds()
                }
                for cid, status in self.statuses.items()
            },
            'timestamp': current_time.isoformat()
        }
    
    async def force_restart_component(self, component_id: str) -> bool:
        """Force restart a component regardless of strategy"""
        logger.info(f"Forcing restart of component {component_id}")
        return await self._restart_component(component_id)
    
    async def set_component_health(self, component_id: str, health: ComponentHealth):
        """Manually set component health (for testing/admin purposes)"""
        if component_id in self.statuses:
            self.statuses[component_id].health = health
            logger.info(f"Manually set {component_id} health to {health.value}")
    
    async def _update_statistics(self):
        """Update supervisor statistics"""
        healthy_count = sum(1 for status in self.statuses.values() 
                          if status.health == ComponentHealth.HEALTHY)
        failed_count = sum(1 for status in self.statuses.values() 
                         if status.health in [ComponentHealth.FAILED, ComponentHealth.STOPPED])
        
        self.supervisor_stats['healthy_components'] = healthy_count
        self.supervisor_stats['failed_components'] = failed_count


class CircuitBreaker:
    """Circuit breaker pattern for preventing cascading failures"""
    
    def __init__(self, failure_threshold: int = 5, timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    async def call(self, func: Callable, *args, **kwargs):
        """Call function through circuit breaker"""
        if self.state == "OPEN":
            if self.last_failure_time and (time.time() - self.last_failure_time) > self.timeout:
                self.state = "HALF_OPEN"
                logger.info("Circuit breaker half-open - testing service")
            else:
                raise Exception("Circuit breaker is OPEN - service unavailable")
        
        try:
            result = await func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.failure_count = 0
                logger.info("Circuit breaker closed - service restored")
            return result
            
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
                logger.error(f"Circuit breaker opened after {self.failure_count} failures")
            
            raise e


# Global supervisor instance
global_supervisor = ComponentSupervisor()