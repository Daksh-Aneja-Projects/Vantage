"""
WebSocket UI Emitter for Project Vantage
Real-time UI state streaming with structured data for generative interfaces
"""
import asyncio
import logging
import json
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

logger = logging.getLogger(__name__)


class UIComponentType(Enum):
    """Supported UI component types"""
    DASHBOARD = "dashboard"
    SIDEBAR = "sidebar"
    NOTIFICATION = "notification"
    OVERLAY = "overlay"
    WIDGET = "widget"
    CHART = "chart"
    STATUS_INDICATOR = "status_indicator"


class UIActionType(Enum):
    """UI action types for interactive components"""
    UPDATE_STATE = "update_state"
    SHOW_NOTIFICATION = "show_notification"
    HIDE_COMPONENT = "hide_component"
    ANIMATE_TRANSITION = "animate_transition"
    TRIGGER_EFFECT = "trigger_effect"


@dataclass
class UIComponent:
    """Structured UI component definition"""
    component_id: str
    component_type: UIComponentType
    properties: Dict[str, Any]
    state: Dict[str, Any]
    visible: bool = True
    interactive: bool = False
    animations: Optional[List[Dict[str, Any]]] = None


@dataclass
class UIStateUpdate:
    """Structured UI state update"""
    timestamp: str
    component_updates: List[Dict[str, Any]]
    global_properties: Optional[Dict[str, Any]] = None
    actions: Optional[List[Dict[str, Any]]] = None


class WebSocketUIEmitter:
    """WebSocket-based UI state emitter for real-time updates"""
    
    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self.host = host
        self.port = port
        self.app = FastAPI(title="Vantage UI Emitter")
        self.active_connections: List[WebSocket] = []
        self.ui_components: Dict[str, UIComponent] = {}
        self.global_state: Dict[str, Any] = {}
        self.is_running = False
        self.stats = {
            'connections': 0,
            'updates_sent': 0,
            'errors': 0
        }
        # Message queue for buffering messages when clients disconnect
        self.message_buffer: Dict[str, List[Dict[str, Any]]] = {}
        self.max_buffer_size = 50  # Maximum messages to buffer per client
        self.critical_message_types = {"alert", "error", "critical_state"}  # Messages that should always be delivered
        
        # Setup CORS for web clients
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # In production, specify actual origins
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup WebSocket and HTTP routes"""
        
        @self.app.websocket("/ws/ui-state")
        async def ui_state_websocket(websocket: WebSocket):
            await self._handle_ui_connection(websocket)
        
        @self.app.get("/api/ui/components")
        async def get_ui_components():
            return {
                "components": [
                    {
                        "id": comp.component_id,
                        "type": comp.component_type.value,
                        "visible": comp.visible,
                        "properties": comp.properties
                    }
                    for comp in self.ui_components.values()
                ],
                "global_state": self.global_state,
                "timestamp": datetime.now().isoformat()
            }
        
        @self.app.get("/api/ui/stats")
        async def get_ui_stats():
            return {
                "stats": self.stats,
                "active_connections": len(self.active_connections),
                "timestamp": datetime.now().isoformat()
            }
    
    async def _handle_ui_connection(self, websocket: WebSocket):
        """Handle incoming UI client connections"""
        await websocket.accept()
        
        try:
            # Add to active connections
            self.active_connections.append(websocket)
            self.stats['connections'] += 1
            logger.info(f"UI client connected. Total connections: {len(self.active_connections)}")
            
            # Send current UI state to new client
            await self._send_full_state(websocket)
            
            # Send any buffered messages for this client
            await self._send_buffered_messages(websocket)
            
            # Listen for client messages (optional)
            while True:
                try:
                    data = await websocket.receive_text()
                    await self._handle_client_message(websocket, data)
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"Error receiving from UI client: {e}")
                    break
                    
        finally:
            # Remove from active connections
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
                    
            # Buffer critical messages for when client reconnects
            client_id = f"{websocket.client.host}:{websocket.client.port}"
            logger.info(f"UI client disconnected: {client_id}. Remaining connections: {len(self.active_connections)}")
    
    async def _send_full_state(self, websocket: WebSocket):
        """Send complete current UI state to client"""
        try:
            full_state = {
                "type": "full_state",
                "timestamp": datetime.now().isoformat(),
                "components": [
                    {
                        "id": comp.component_id,
                        "type": comp.component_type.value,
                        "properties": comp.properties,
                        "state": comp.state,
                        "visible": comp.visible
                    }
                    for comp in self.ui_components.values()
                ],
                "global_state": self.global_state
            }
            
            await websocket.send_text(json.dumps(full_state))
            
        except Exception as e:
            logger.error(f"Error sending full state: {e}")
    
    async def _handle_client_message(self, websocket: WebSocket, message: str):
        """Handle messages from UI clients"""
        try:
            data = json.loads(message)
            message_type = data.get('type')
            
            if message_type == 'ui_action':
                # Handle UI action from client
                action = data.get('action')
                component_id = data.get('component_id')
                logger.info(f"Received UI action: {action} for component {component_id}")
                # Forward to application logic as needed
                
            elif message_type == 'component_interaction':
                # Handle component interaction
                component_id = data.get('component_id')
                interaction_type = data.get('interaction')
                logger.info(f"Component {component_id} interaction: {interaction_type}")
                
        except json.JSONDecodeError:
            logger.error("Invalid JSON received from UI client")
        except Exception as e:
            logger.error(f"Error handling client message: {e}")
    
    async def register_component(self, component: UIComponent) -> bool:
        """Register a UI component"""
        try:
            self.ui_components[component.component_id] = component
            logger.info(f"Registered UI component: {component.component_id}")
            
            # Broadcast component registration to all clients
            await self._broadcast_update({
                "type": "component_registered",
                "component": {
                    "id": component.component_id,
                    "type": component.component_type.value,
                    "properties": component.properties,
                    "visible": component.visible
                },
                "timestamp": datetime.now().isoformat()
            })
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to register component {component.component_id}: {e}")
            return False
    
    async def update_component(self, component_id: str, updates: Dict[str, Any]) -> bool:
        """Update a registered UI component"""
        try:
            if component_id not in self.ui_components:
                logger.warning(f"Component {component_id} not found")
                return False
            
            component = self.ui_components[component_id]
            
            # Apply updates
            if 'properties' in updates:
                component.properties.update(updates['properties'])
            if 'state' in updates:
                component.state.update(updates['state'])
            if 'visible' in updates:
                component.visible = updates['visible']
            
            # Create update message
            update_message = {
                "type": "component_update",
                "component_id": component_id,
                "updates": updates,
                "timestamp": datetime.now().isoformat()
            }
            
            # Broadcast to all clients
            await self._broadcast_update(update_message)
            self.stats['updates_sent'] += 1
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to update component {component_id}: {e}")
            self.stats['errors'] += 1
            return False
    
    async def trigger_action(self, action_type: UIActionType, 
                           component_id: Optional[str] = None,
                           parameters: Optional[Dict[str, Any]] = None) -> bool:
        """Trigger UI action across all clients"""
        try:
            action_message = {
                "type": "ui_action",
                "action_type": action_type.value,
                "component_id": component_id,
                "parameters": parameters or {},
                "timestamp": datetime.now().isoformat()
            }
            
            await self._broadcast_update(action_message)
            self.stats['updates_sent'] += 1
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to trigger action {action_type}: {e}")
            self.stats['errors'] += 1
            return False
    
    async def update_global_state(self, updates: Dict[str, Any]) -> bool:
        """Update global UI state"""
        try:
            self.global_state.update(updates)
            
            update_message = {
                "type": "global_state_update",
                "updates": updates,
                "timestamp": datetime.now().isoformat()
            }
            
            await self._broadcast_update(update_message)
            self.stats['updates_sent'] += 1
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to update global state: {e}")
            self.stats['errors'] += 1
            return False
    
    async def emit_sensor_state(self, sensor_data: Dict[str, Any]) -> bool:
        """Emit sensor data as UI state updates"""
        try:
            # Transform sensor data into UI-friendly format
            ui_updates = []
            
            for sensor_id, data in sensor_data.items():
                if isinstance(data, dict) and 'value' in data:
                    # Create component update for sensor
                    ui_updates.append({
                        "component_id": f"sensor_{sensor_id}",
                        "updates": {
                            "state": {
                                "value": data['value'],
                                "confidence": data.get('confidence', 1.0),
                                "timestamp": data.get('timestamp', datetime.now().isoformat())
                            }
                        }
                    })
            
            if ui_updates:
                state_update = {
                    "type": "sensor_state_update",
                    "updates": ui_updates,
                    "timestamp": datetime.now().isoformat()
                }
                
                await self._broadcast_update(state_update)
                self.stats['updates_sent'] += 1
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to emit sensor state: {e}")
            self.stats['errors'] += 1
            return False
    
    async def emit_context_state(self, context_data: Dict[str, Any]) -> bool:
        """Emit context analysis as UI state"""
        try:
            context_update = {
                "type": "context_state_update",
                "context": context_data,
                "timestamp": datetime.now().isoformat()
            }
            
            await self._broadcast_update(context_update)
            self.stats['updates_sent'] += 1
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to emit context state: {e}")
            self.stats['errors'] += 1
            return False
    
    async def _broadcast_update(self, message: Dict[str, Any]):
        """Broadcast message to all connected clients"""
        if not self.active_connections:
            return
            
        disconnected = []
        message_str = json.dumps(message)
            
        for websocket in self.active_connections:
            try:
                await websocket.send_text(message_str)
            except WebSocketDisconnect:
                disconnected.append(websocket)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                disconnected.append(websocket)
            
        # Remove disconnected clients
        for websocket in disconnected:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
                # Buffer critical messages for when client reconnects
                client_id = f"{websocket.client.host}:{websocket.client.port}"
                message_type = message.get('type', '')
                if message_type in self.critical_message_types:
                    if client_id not in self.message_buffer:
                        self.message_buffer[client_id] = []
                    # Add to buffer but respect max size
                    if len(self.message_buffer[client_id]) < self.max_buffer_size:
                        self.message_buffer[client_id].append(message)
                    else:
                        # Remove oldest message if buffer is full
                        self.message_buffer[client_id].pop(0)
                        self.message_buffer[client_id].append(message)
        
    async def _send_buffered_messages(self, websocket: WebSocket):
        """Send buffered messages to a reconnected client"""
        client_id = f"{websocket.client.host}:{websocket.client.port}"
        if client_id in self.message_buffer:
            buffered_messages = self.message_buffer[client_id]
            for message in buffered_messages:
                try:
                    await websocket.send_text(json.dumps(message))
                    logger.info(f"Sent buffered message to {client_id}: {message.get('type', 'unknown')}")
                except Exception as e:
                    logger.error(f"Error sending buffered message to {client_id}: {e}")
            # Clear the buffer after sending
            del self.message_buffer[client_id]
        
    async def _buffer_message_for_client(self, client_id: str, message: Dict[str, Any]):
        """Buffer a message for a specific client"""
        if client_id not in self.message_buffer:
            self.message_buffer[client_id] = []
        # Add to buffer but respect max size
        if len(self.message_buffer[client_id]) < self.max_buffer_size:
            self.message_buffer[client_id].append(message)
        else:
            # Remove oldest message if buffer is full
            self.message_buffer[client_id].pop(0)
            self.message_buffer[client_id].append(message)
    
    async def get_component(self, component_id: str) -> Optional[UIComponent]:
        """Get registered component by ID"""
        return self.ui_components.get(component_id)
    
    async def get_all_components(self) -> List[UIComponent]:
        """Get all registered components"""
        return list(self.ui_components.values())
    
    async def remove_component(self, component_id: str) -> bool:
        """Remove component from registry"""
        try:
            if component_id in self.ui_components:
                del self.ui_components[component_id]
                
                # Notify clients of removal
                await self._broadcast_update({
                    "type": "component_removed",
                    "component_id": component_id,
                    "timestamp": datetime.now().isoformat()
                })
                
                logger.info(f"Removed component: {component_id}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Failed to remove component {component_id}: {e}")
            return False
    
    async def start_server(self):
        """Start the WebSocket server"""
        try:
            self.is_running = True
            config = uvicorn.Config(
                self.app,
                host=self.host,
                port=self.port,
                log_level="info"
            )
            server = uvicorn.Server(config)
            
            logger.info(f"WebSocket UI Emitter started on ws://{self.host}:{self.port}/ws/ui-state")
            await server.serve()
            
        except Exception as e:
            logger.error(f"Failed to start UI emitter server: {e}")
            self.is_running = False
    
    async def stop_server(self):
        """Stop the WebSocket server"""
        self.is_running = False
        logger.info("WebSocket UI Emitter stopped")
    
    async def get_server_stats(self) -> Dict[str, Any]:
        """Get server statistics"""
        return {
            "is_running": self.is_running,
            "host": self.host,
            "port": self.port,
            "active_connections": len(self.active_connections),
            "registered_components": len(self.ui_components),
            "stats": self.stats,
            "timestamp": datetime.now().isoformat()
        }


class StructuredUIBuilder:
    """Helper class for building structured UI components"""
    
    @staticmethod
    def create_dashboard_component(component_id: str, 
                                 title: str,
                                 widgets: List[Dict[str, Any]],
                                 layout: str = "grid") -> UIComponent:
        """Create dashboard component"""
        return UIComponent(
            component_id=component_id,
            component_type=UIComponentType.DASHBOARD,
            properties={
                "title": title,
                "widgets": widgets,
                "layout": layout,
                "theme": "dark"
            },
            state={
                "active_tab": 0,
                "refresh_rate": 1000
            },
            interactive=True
        )
    
    @staticmethod
    def create_sidebar_component(component_id: str,
                               menu_items: List[Dict[str, Any]],
                               position: str = "left") -> UIComponent:
        """Create sidebar component"""
        return UIComponent(
            component_id=component_id,
            component_type=UIComponentType.SIDEBAR,
            properties={
                "menu_items": menu_items,
                "position": position,
                "width": "250px"
            },
            state={
                "expanded": True,
                "selected_item": None
            },
            interactive=True
        )
    
    @staticmethod
    def create_notification_component(component_id: str,
                                    message: str,
                                    severity: str = "info",
                                    duration: int = 5000) -> UIComponent:
        """Create notification component"""
        return UIComponent(
            component_id=component_id,
            component_type=UIComponentType.NOTIFICATION,
            properties={
                "message": message,
                "severity": severity,
                "duration": duration
            },
            state={
                "visible": True,
                "timestamp": datetime.now().isoformat()
            }
        )
    
    @staticmethod
    def create_status_indicator(component_id: str,
                              status: str,
                              label: str,
                              color_map: Optional[Dict[str, str]] = None) -> UIComponent:
        """Create status indicator component"""
        return UIComponent(
            component_id=component_id,
            component_type=UIComponentType.STATUS_INDICATOR,
            properties={
                "label": label,
                "color_map": color_map or {
                    "online": "#4CAF50",
                    "offline": "#F44336",
                    "warning": "#FF9800",
                    "unknown": "#9E9E9E"
                }
            },
            state={
                "status": status,
                "last_update": datetime.now().isoformat()
            }
        )


# Backward compatibility
WebSocketUIStreamer = WebSocketUIEmitter
RealTimeUIEmitter = WebSocketUIEmitter