"""
Global State Store for Project Vantage
Implements centralized state management with observers and persistence
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional, Callable, Set
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
import json
import threading
from collections import defaultdict
import copy
import sqlite3
import os
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class StateScope(Enum):
    """Scopes for state data"""
    GLOBAL = "global"          # System-wide state
    USER = "user"             # User-specific state
    DEVICE = "device"         # Device-specific state
    SESSION = "session"       # Session-specific state
    TEMPORARY = "temporary"   # Temporary/transient state


class StateChangeEvent:
    """Represents a state change event"""
    
    def __init__(self, key: str, old_value: Any, new_value: Any, 
                 scope: StateScope, source: str = "system"):
        self.key = key
        self.old_value = old_value
        self.new_value = new_value
        self.scope = scope
        self.source = source
        self.timestamp = datetime.now()
        self.event_id = f"{key}_{self.timestamp.timestamp()}"


@dataclass
class StateObserver:
    """Observer for state changes"""
    observer_id: str
    callback: Callable[[StateChangeEvent], None]
    interested_keys: Set[str] = None  # None means all keys
    scope_filter: StateScope = None    # None means all scopes
    is_async: bool = True


class StatePersistence:
    """Handles state persistence to SQLite database"""
    
    def __init__(self, db_path: str = "./state_store.db"):
        self.db_path = db_path
        self.persist_interval = 30.0  # seconds
        self.is_persisting = False
        self.persistence_task = None
        self._ensure_db_exists()
    
    def _ensure_db_exists(self):
        """Ensure the SQLite database and table exist"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS state_store (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        scope TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                conn.commit()
                logger.info(f"SQLite database initialized at {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize SQLite database: {e}")
    
    async def save_state(self, state_data: Dict[str, Any]) -> bool:
        """Save state to SQLite database"""
        try:
            # Prepare data for storage - flatten the nested dict structure
            flattened_data = self._flatten_dict(state_data)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Clear existing state data
                cursor.execute("DELETE FROM state_store")
                
                # Insert new state data
                for key, value in flattened_data.items():
                    cursor.execute(
                        "INSERT OR REPLACE INTO state_store (key, value, scope) VALUES (?, ?, ?)",
                        (key, json.dumps(value, default=str), "global")
                    )
                
                conn.commit()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to save state to SQLite: {e}")
            return False
    
    def _flatten_dict(self, d: Dict[str, Any], parent_key: str = '', sep: str = '.') -> Dict[str, Any]:
        """Flatten a nested dictionary"""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)
    
    def _unflatten_dict(self, items: List[tuple]) -> Dict[str, Any]:
        """Unflatten a list of (key, value) pairs into a nested dictionary"""
        result = {}
        for key, value in items:
            keys = key.split('.')
            d = result
            for k in keys[:-1]:
                if k not in d:
                    d[k] = {}
                d = d[k]
            d[keys[-1]] = value
        return result

    async def load_state(self) -> Dict[str, Any]:
        """Load state from SQLite database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT key, value FROM state_store")
                rows = cursor.fetchall()
                
                # Reconstruct the state dictionary
                state_items = []
                for key, value in rows:
                    try:
                        parsed_value = json.loads(value)
                        state_items.append((key, parsed_value))
                    except json.JSONDecodeError:
                        # If JSON parsing fails, store as-is
                        state_items.append((key, value))
                
                # Unflatten the data back to nested structure
                return self._unflatten_dict(state_items)
                
        except Exception as e:
            logger.error(f"Failed to load state from SQLite: {e}")
            return {}

    async def start_auto_persistence(self, get_state_func: Callable):
        """Start automatic periodic state persistence"""
        if self.is_persisting:
            return
        
        self.is_persisting = True
        self.persistence_task = asyncio.create_task(self._persistence_loop(get_state_func))
        logger.info("Auto-persistence started")
    
    async def stop_auto_persistence(self):
        """Stop automatic state persistence"""
        self.is_persisting = False
        if self.persistence_task:
            self.persistence_task.cancel()
            try:
                await self.persistence_task
            except asyncio.CancelledError:
                pass
        logger.info("Auto-persistence stopped")
    
    async def _persistence_loop(self, get_state_func: Callable):
        """Periodic persistence loop"""
        while self.is_persisting:
            try:
                current_state = get_state_func()
                await self.save_state(current_state)
                await asyncio.sleep(self.persist_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in persistence loop: {e}")
                await asyncio.sleep(5)


class GlobalStateStore:
    """
    Centralized global state management with observers and persistence
    """
    
    def __init__(self, db_path: str = "./state_store.db"):
        # Thread-safe state storage
        self._state_lock = threading.RLock()
        self._state_data: Dict[str, Any] = {}
        
        # Observers
        self._observers: Dict[str, StateObserver] = {}
        self._observer_lock = threading.RLock()
        
        # State history for rollback/undo
        self._state_history: List[StateChangeEvent] = []
        self._max_history_size = 1000
        
        # Persistence
        self._persistence = StatePersistence(db_path)
        self._auto_persistence_enabled = False
        
        # Performance metrics
        self._metrics = {
            'total_changes': 0,
            'total_reads': 0,
            'observer_notifications': 0,
            'failed_notifications': 0
        }
        
        # Initialize with default global state
        self._initialize_default_state()
        
        # Load any existing state from database
        asyncio.create_task(self._load_persistent_state())
    
    async def _load_persistent_state(self):
        """Load state from persistent storage during initialization"""
        try:
            saved_state = await self._persistence.load_state()
            if saved_state:
                with self._state_lock:
                    self._state_data.update(saved_state)
                logger.info("Loaded state from persistent storage")
        except Exception as e:
            logger.error(f"Error loading persistent state: {e}")

    def _initialize_default_state(self):
        """Initialize default global state structure"""
        with self._state_lock:
            self._state_data = {
                'system': {
                    'status': 'initializing',
                    'startup_time': datetime.now().isoformat(),
                    'version': '1.0.0',
                    'components': {}
                },
                'environmental': {
                    'temperature': {'average': 22.0, 'unit': 'celsius'},
                    'humidity': {'average': 45.0, 'unit': 'percent'},
                    'light': {'average': 300.0, 'unit': 'lux'},
                    'air_quality': {'index': 50, 'status': 'good'}
                },
                'social': {
                    'estimated_presence': 'unknown',
                    'occupancy_count': 0,
                    'activity_level': 'unknown'
                },
                'temporal': {
                    'current_time': datetime.now().isoformat(),
                    'day_of_week': datetime.now().weekday(),
                    'hour': datetime.now().hour,
                    'season': self._get_current_season()
                },
                'security': {
                    'current_level': 'normal',
                    'last_incident': None,
                    'cameras_active': True
                },
                'user_preferences': {
                    'theme': 'dark',
                    'notifications': 'enabled',
                    'privacy_level': 'balanced'
                },
                'network': {
                    'connected_devices': [],
                    'mesh_status': 'forming',
                    'bandwidth_usage': 0.0
                }
            }
    
    def _get_current_season(self) -> str:
        """Get current season based on month"""
        month = datetime.now().month
        if month in [12, 1, 2]:
            return 'winter'
        elif month in [3, 4, 5]:
            return 'spring'
        elif month in [6, 7, 8]:
            return 'summer'
        else:
            return 'autumn'
    
    async def set(self, key: str, value: Any, scope: StateScope = StateScope.GLOBAL, 
                  source: str = "system") -> bool:
        """Set a state value"""
        try:
            with self._state_lock:
                # Get old value for change event
                old_value = self._get_nested_value(key)
                
                # Set new value
                self._set_nested_value(key, value)
                
                # Record change in history
                change_event = StateChangeEvent(key, old_value, value, scope, source)
                self._state_history.append(change_event)
                
                # Keep history size manageable
                if len(self._state_history) > self._max_history_size:
                    self._state_history = self._state_history[-500:]
                
                # Update metrics
                self._metrics['total_changes'] += 1
            
            # Notify observers asynchronously
            asyncio.create_task(self._notify_observers(change_event))
            
            logger.debug(f"State updated: {key} = {value} (scope: {scope.value})")
            return True
            
        except Exception as e:
            logger.error(f"Error setting state {key}: {e}")
            return False
    
    async def get(self, key: str, default: Any = None) -> Any:
        """Get a state value"""
        try:
            with self._state_lock:
                value = self._get_nested_value(key)
                self._metrics['total_reads'] += 1
                return value if value is not None else default
                
        except Exception as e:
            logger.error(f"Error getting state {key}: {e}")
            return default
    
    def _get_nested_value(self, key: str) -> Any:
        """Get nested value using dot notation (e.g., 'environmental.temperature.average')"""
        keys = key.split('.')
        current = self._state_data
        
        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return None
        
        return copy.deepcopy(current)  # Return copy to prevent external modification
    
    def _set_nested_value(self, key: str, value: Any):
        """Set nested value using dot notation"""
        keys = key.split('.')
        current = self._state_data
        
        # Navigate to parent of target
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]
        
        # Set the value
        current[keys[-1]] = copy.deepcopy(value)  # Store copy to prevent external modification
    
    async def delete(self, key: str, scope: StateScope = StateScope.GLOBAL) -> bool:
        """Delete a state key"""
        try:
            old_value = await self.get(key)
            success = await self.set(key, None, scope)
            if success and old_value is not None:
                logger.debug(f"State deleted: {key}")
            return success
            
        except Exception as e:
            logger.error(f"Error deleting state {key}: {e}")
            return False
    
    async def register_observer(self, observer_id: str, callback: Callable,
                              interested_keys: List[str] = None,
                              scope_filter: StateScope = None) -> bool:
        """Register an observer for state changes"""
        try:
            with self._observer_lock:
                observer = StateObserver(
                    observer_id=observer_id,
                    callback=callback,
                    interested_keys=set(interested_keys) if interested_keys else None,
                    scope_filter=scope_filter,
                    is_async=asyncio.iscoroutinefunction(callback)
                )
                
                self._observers[observer_id] = observer
                logger.debug(f"Observer registered: {observer_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error registering observer {observer_id}: {e}")
            return False
    
    async def unregister_observer(self, observer_id: str) -> bool:
        """Unregister an observer"""
        try:
            with self._observer_lock:
                if observer_id in self._observers:
                    del self._observers[observer_id]
                    logger.debug(f"Observer unregistered: {observer_id}")
                    return True
                return False
                
        except Exception as e:
            logger.error(f"Error unregistering observer {observer_id}: {e}")
            return False
    
    async def _notify_observers(self, change_event: StateChangeEvent):
        """Notify all interested observers of a state change"""
        try:
            with self._observer_lock:
                observers_to_notify = []
                
                for observer in self._observers.values():
                    # Check if observer is interested in this change
                    if self._should_notify_observer(observer, change_event):
                        observers_to_notify.append(observer)
                
                # Notify observers concurrently
                if observers_to_notify:
                    tasks = []
                    for observer in observers_to_notify:
                        try:
                            if observer.is_async:
                                task = asyncio.create_task(observer.callback(change_event))
                                tasks.append(task)
                            else:
                                # Run sync callback in thread pool
                                task = asyncio.create_task(
                                    asyncio.get_event_loop().run_in_executor(
                                        None, observer.callback, change_event
                                    )
                                )
                                tasks.append(task)
                                
                        except Exception as e:
                            logger.error(f"Error notifying observer {observer.observer_id}: {e}")
                            self._metrics['failed_notifications'] += 1
                    
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
                        self._metrics['observer_notifications'] += len(tasks)
                        
        except Exception as e:
            logger.error(f"Error in observer notification: {e}")
    
    def _should_notify_observer(self, observer: StateObserver, 
                               change_event: StateChangeEvent) -> bool:
        """Determine if observer should be notified of change"""
        # Check scope filter
        if observer.scope_filter and observer.scope_filter != change_event.scope:
            return False
        
        # Check key interest
        if observer.interested_keys:
            return change_event.key in observer.interested_keys
        
        # Observer wants all changes
        return True
    
    async def get_state_snapshot(self, scope: StateScope = None) -> Dict[str, Any]:
        """Get snapshot of current state"""
        try:
            with self._state_lock:
                if scope:
                    # Return only data for specific scope
                    scope_data = {}
                    for key, value in self._state_data.items():
                        # This is a simplification - real implementation would need
                        # to track scope information for each piece of state
                        scope_data[key] = copy.deepcopy(value)
                    return scope_data
                else:
                    # Return complete state
                    return copy.deepcopy(self._state_data)
                    
        except Exception as e:
            logger.error(f"Error getting state snapshot: {e}")
            return {}
    
    async def restore_state(self, state_snapshot: Dict[str, Any]) -> bool:
        """Restore state from snapshot"""
        try:
            with self._state_lock:
                # Create backup of current state
                backup = copy.deepcopy(self._state_data)
                
                try:
                    # Restore new state
                    self._state_data = copy.deepcopy(state_snapshot)
                    
                    # Notify observers of major state change
                    change_event = StateChangeEvent(
                        key="full_state_restore",
                        old_value=backup,
                        new_value=state_snapshot,
                        scope=StateScope.GLOBAL,
                        source="restore_operation"
                    )
                    asyncio.create_task(self._notify_observers(change_event))
                    
                    logger.info("State restored from snapshot")
                    return True
                    
                except Exception as restore_error:
                    # Rollback to backup on error
                    self._state_data = backup
                    logger.error(f"State restore failed, rolled back: {restore_error}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error restoring state: {e}")
            return False
    
    async def get_change_history(self, limit: int = 50) -> List[StateChangeEvent]:
        """Get recent state change history"""
        try:
            # Return most recent changes
            start_idx = max(0, len(self._state_history) - limit)
            return self._state_history[start_idx:]
            
        except Exception as e:
            logger.error(f"Error getting change history: {e}")
            return []
    
    async def enable_auto_persistence(self):
        """Enable automatic state persistence"""
        if not self._auto_persistence_enabled:
            await self._persistence.start_auto_persistence(self.get_state_snapshot)
            self._auto_persistence_enabled = True
            logger.info("Auto-persistence enabled")
    
    async def disable_auto_persistence(self):
        """Disable automatic state persistence"""
        if self._auto_persistence_enabled:
            await self._persistence.stop_auto_persistence()
            self._auto_persistence_enabled = False
            logger.info("Auto-persistence disabled")
    
    async def manual_persist(self) -> bool:
        """Manually persist current state"""
        try:
            current_state = await self.get_state_snapshot()
            return await self._persistence.save_state(current_state)
        except Exception as e:
            logger.error(f"Manual persistence failed: {e}")
            return False
    
    async def load_persistent_state(self) -> bool:
        """Load state from persistent storage"""
        try:
            persisted_state = await self._persistence.load_state()
            if persisted_state:
                return await self.restore_state(persisted_state)
            return True  # No persisted state is not an error
        except Exception as e:
            logger.error(f"Failed to load persistent state: {e}")
            return False
    
    async def get_store_stats(self) -> Dict[str, Any]:
        """Get state store statistics"""
        return {
            'metrics': self._metrics,
            'observer_count': len(self._observers),
            'history_size': len(self._state_history),
            'state_size_estimate': len(json.dumps(self._state_data, default=str)),
            'auto_persistence_enabled': self._auto_persistence_enabled,
            'timestamp': datetime.now().isoformat()
        }
    
    async def cleanup(self):
        """Cleanup resources"""
        await self.disable_auto_persistence()
        # Clear observers
        with self._observer_lock:
            self._observers.clear()
        logger.info("GlobalStateStore cleaned up")


# Global instance
global_state_store = GlobalStateStore()