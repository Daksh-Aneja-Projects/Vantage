"""
State Emitter for Project Vantage
Real-time UI state streaming with WebSocket server for generative interfaces
"""
import asyncio
import logging
import json
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

from user_interface.websocket_ui_emitter import WebSocketUIEmitter, UIComponent, UIComponentType, StructuredUIBuilder

logger = logging.getLogger(__name__)


class StateType(Enum):
    """Types of state updates"""
    SENSOR_DATA = "sensor_data"
    CONTEXT_UPDATE = "context_update"
    DECISION_MADE = "decision_made"
    SYSTEM_STATUS = "system_status"
    FEEDBACK_REQUEST = "feedback_request"


@dataclass
class StateUpdate:
    """Structured state update"""
    state_type: StateType
    data: Dict[str, Any]
    timestamp: str
    priority: int = 1


class StateEmitter:
    """
    Emits state updates to connected UI clients via WebSocket
    """
    
    def __init__(self):
        self.websocket_emitter = WebSocketUIEmitter(host="0.0.0.0", port=8080)
        self.is_initialized = False
        self.ui_builder = StructuredUIBuilder()
        self.state_handlers: Dict[StateType, List[Callable]] = {}
        self.active_subscribers: List[str] = []
        
    async def initialize(self):
        """Initialize the state emitter"""
        try:
            # Initialize WebSocket emitter
            await self.websocket_emitter.initialize()
            
            # Register default UI components
            await self._register_default_components()
            
            self.is_initialized = True
            logger.info("StateEmitter initialized successfully")
            
            # Start background server
            asyncio.create_task(self._start_server())
            
        except Exception as e:
            logger.error(f"Failed to initialize StateEmitter: {e}")
            raise
    
    async def _start_server(self):
        """Start the WebSocket server in background"""
        await self.websocket_emitter.start_server()
    
    async def _register_default_components(self):
        """Register default UI components"""
        try:
            # Create dashboard component
            dashboard = self.ui_builder.create_dashboard_component(
                "main_dashboard",
                "Vantage Dashboard",
                [
                    {"id": "sensor_panel", "type": "panel", "title": "Sensor Status"},
                    {"id": "context_panel", "type": "panel", "title": "Context Analysis"},
                    {"id": "decision_panel", "type": "panel", "title": "System Decisions"}
                ]
            )
            await self.websocket_emitter.register_component(dashboard)
            
            # Create status indicators
            status_indicators = [
                self.ui_builder.create_status_indicator(
                    f"status_{sensor_type.value}",
                    "online",
                    f"{sensor_type.value.title()} Status"
                )
                for sensor_type in [StateType.SENSOR_DATA, StateType.CONTEXT_UPDATE, StateType.DECISION_MADE]
            ]
            
            for indicator in status_indicators:
                await self.websocket_emitter.register_component(indicator)
                
        except Exception as e:
            logger.error(f"Failed to register default components: {e}")
    
    async def emit_sensor_data(self, sensor_data: Dict[str, Any]) -> bool:
        """Emit sensor data update"""
        try:
            state_update = StateUpdate(
                state_type=StateType.SENSOR_DATA,
                data=sensor_data,
                timestamp=datetime.now().isoformat(),
                priority=2
            )
            
            # Transform sensor data into UI-friendly format
            ui_data = self._transform_sensor_data_for_ui(sensor_data)
            
            # Update UI components
            success = await self.websocket_emitter.emit_sensor_state(ui_data)
            
            if success:
                # Update status indicator
                await self.websocket_emitter.update_component(
                    "status_sensor_data",
                    {"state": {"status": "online", "last_update": datetime.now().isoformat()}}
                )
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to emit sensor data: {e}")
            return False
    
    async def emit_context_update(self, context_data: Dict[str, Any]) -> bool:
        """Emit context analysis update"""
        try:
            state_update = StateUpdate(
                state_type=StateType.CONTEXT_UPDATE,
                data=context_data,
                timestamp=datetime.now().isoformat(),
                priority=1
            )
            
            # Transform context data for UI
            ui_data = self._transform_context_data_for_ui(context_data)
            
            # Update UI
            success = await self.websocket_emitter.emit_context_state(ui_data)
            
            if success:
                # Update status indicator
                await self.websocket_emitter.update_component(
                    "status_context_update",
                    {"state": {"status": "online", "last_update": datetime.now().isoformat()}}
                )
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to emit context update: {e}")
            return False
    
    async def emit_decision_made(self, decision_data: Dict[str, Any]) -> bool:
        """Emit decision made update"""
        try:
            state_update = StateUpdate(
                state_type=StateType.DECISION_MADE,
                data=decision_data,
                timestamp=datetime.now().isoformat(),
                priority=3
            )
            
            # Transform decision data for UI
            ui_data = self._transform_decision_data_for_ui(decision_data)
            
            # Create notification if needed
            if decision_data.get('type') == 'adjust_environment':
                notification = self.ui_builder.create_notification_component(
                    f"decision_notification_{datetime.now().timestamp()}",
                    f"Environment adjusted: {decision_data.get('params', {}).get('setting', 'unknown')}",
                    "info"
                )
                await self.websocket_emitter.register_component(notification)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to emit decision: {e}")
            return False
    
    async def emit_system_status(self, status_data: Dict[str, Any]) -> bool:
        """Emit system status update"""
        try:
            # Update global state
            success = await self.websocket_emitter.update_global_state(status_data)
            
            if success:
                # Update status indicator
                await self.websocket_emitter.update_component(
                    "status_system_status",
                    {"state": {"status": "online", "last_update": datetime.now().isoformat()}}
                )
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to emit system status: {e}")
            return False
    
    def _transform_sensor_data_for_ui(self, sensor_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform raw sensor data for UI presentation"""
        transformed = {}
        
        for sensor_id, data in sensor_data.items():
            if isinstance(data, dict) and 'data' in data:
                # Extract relevant values
                sensor_values = data['data']
                if isinstance(sensor_values, dict):
                    # Extract value and confidence
                    value = sensor_values.get('value', sensor_values.get('temperature', sensor_values.get('lux', 'N/A')))
                    confidence = sensor_values.get('confidence', 1.0)
                    
                    transformed[f"sensor_{sensor_id}"] = {
                        "value": value,
                        "confidence": confidence,
                        "timestamp": data.get('timestamp', datetime.now().isoformat()),
                        "type": data.get('sensor_type', 'unknown')
                    }
        
        return transformed
    
    def _transform_context_data_for_ui(self, context_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform context analysis for UI presentation"""
        return {
            "analysis": context_data,
            "summary": self._generate_context_summary(context_data),
            "timestamp": datetime.now().isoformat()
        }
    
    def _transform_decision_data_for_ui(self, decision_data: Dict[str, Any]) -> Dict[str, Any]:
        """Transform decision data for UI presentation"""
        return {
            "decision": decision_data,
            "execution_status": "pending",
            "timestamp": datetime.now().isoformat()
        }
    
    def _generate_context_summary(self, context_data: Dict[str, Any]) -> str:
        """Generate human-readable context summary"""
        if not context_data:
            return "No context available"
        
        # Simple summary generation based on common context keys
        summary_parts = []
        
        if 'user_presence' in context_data:
            summary_parts.append(f"User presence: {context_data['user_presence']}")
        
        if 'environmental_conditions' in context_data:
            conditions = context_data['environmental_conditions']
            if 'temperature' in conditions:
                summary_parts.append(f"Temperature: {conditions['temperature']}°C")
            if 'light_level' in conditions:
                summary_parts.append(f"Light: {conditions['light_level']}")
        
        if 'time_of_day' in context_data:
            summary_parts.append(f"Time: {context_data['time_of_day']}")
        
        return "; ".join(summary_parts) if summary_parts else "Context analyzed"
    
    async def get_emitter_status(self) -> Dict[str, Any]:
        """Get current emitter status"""
        ui_stats = await self.websocket_emitter.get_server_stats()
        
        return {
            "is_initialized": self.is_initialized,
            "active_subscribers": len(self.active_subscribers),
            "ui_components_count": len(await self.websocket_emitter.get_all_components()),
            "websocket_stats": ui_stats,
            "timestamp": datetime.now().isoformat()
        }
    
    async def shutdown(self):
        """Shutdown the state emitter"""
        await self.websocket_emitter.stop_server()
        self.is_initialized = False
        logger.info("StateEmitter shutdown complete")


# Backward compatibility
UIStateEmitter = StateEmitter
RealTimeStateEmitter = StateEmitter