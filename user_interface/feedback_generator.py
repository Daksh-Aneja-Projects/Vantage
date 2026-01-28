"""
Feedback Generator for Project Vantage
Generates structured feedback for the Server-Driven UI system
"""
import asyncio
import logging
from typing import Dict, Any, Optional
from user_interface.websocket_ui_emitter import UIComponent, UIComponentType, UIActionType, StructuredUIBuilder
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum

logger = logging.getLogger(__name__)


class FeedbackType(Enum):
    """Types of feedback"""
    NOTIFICATION = "notification"
    STATUS_UPDATE = "status_update"
    USER_PROMPT = "user_prompt"
    SYSTEM_ALERT = "system_alert"
    CONTEXT_FEEDBACK = "context_feedback"


class FeedbackPriority(Enum):
    """Priority levels for feedback"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ServerDrivenUISchema(BaseModel):
    """
    Server-Driven UI Schema for generative interfaces
    """
    component_id: str = Field(..., description="Unique identifier for the UI component")
    component_type: str = Field(..., description="Type of UI component")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Component properties")
    state: Dict[str, Any] = Field(default_factory=dict, description="Component state")
    actions: Optional[List[Dict[str, Any]]] = Field(default=None, description="Available actions")
    priority: str = Field(default="medium", description="Priority level")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class FeedbackGenerator:
    """
    Generates structured feedback for Server-Driven UI
    """
    
    def __init__(self):
        self.ui_builder = StructuredUIBuilder()
        self.feedback_queue = asyncio.Queue()
        self.is_running = False
        
    async def initialize(self):
        """Initialize the feedback generator"""
        self.is_running = True
        logger.info("FeedbackGenerator initialized")
    
    async def generate(self, text: str, feedback_type: str, **kwargs) -> Dict[str, Any]:
        """
        Generate structured feedback for Server-Driven UI
        """
        try:
            # Determine feedback type and create appropriate schema
            if feedback_type == "notification":
                return await self._generate_notification(text, **kwargs)
            elif feedback_type == "status_update":
                return await self._generate_status_update(text, **kwargs)
            elif feedback_type == "user_prompt":
                return await self._generate_user_prompt(text, **kwargs)
            elif feedback_type == "system_alert":
                return await self._generate_system_alert(text, **kwargs)
            elif feedback_type == "context_feedback":
                return await self._generate_context_feedback(text, **kwargs)
            else:
                # Default to notification
                return await self._generate_notification(text, **kwargs)
                
        except Exception as e:
            logger.error(f"Failed to generate feedback: {e}")
            return self._create_error_feedback(str(e))
    
    async def _generate_notification(self, text: str, **kwargs) -> Dict[str, Any]:
        """Generate notification feedback"""
        priority = kwargs.get('priority', 'medium')
        duration = kwargs.get('duration', 5000)  # 5 seconds default
        
        # Create Server-Driven UI schema
        schema = ServerDrivenUISchema(
            component_id=f"notification_{datetime.now().timestamp()}",
            component_type="notification",
            properties={
                "message": text,
                "severity": kwargs.get('severity', 'info'),
                "duration": duration,
                "position": kwargs.get('position', 'top-right')
            },
            state={
                "visible": True,
                "dismissed": False
            },
            priority=priority,
            timestamp=datetime.now().isoformat()
        )
        
        return schema.model_dump()
    
    async def _generate_status_update(self, text: str, **kwargs) -> Dict[str, Any]:
        """Generate status update feedback"""
        status_value = kwargs.get('status', 'active')
        component_id = kwargs.get('component_id', f"status_indicator_{datetime.now().timestamp()}")
        
        # Create Server-Driven UI schema
        schema = ServerDrivenUISchema(
            component_id=component_id,
            component_type="status-indicator",
            properties={
                "label": text,
                "status_colors": {
                    "online": "#4CAF50",
                    "offline": "#F44336",
                    "warning": "#FF9800",
                    "unknown": "#9E9E9E"
                }
            },
            state={
                "status": status_value,
                "last_update": datetime.now().isoformat()
            },
            priority=kwargs.get('priority', 'medium'),
            timestamp=datetime.now().isoformat()
        )
        
        return schema.model_dump()
    
    async def _generate_user_prompt(self, text: str, **kwargs) -> Dict[str, Any]:
        """Generate user prompt feedback"""
        options = kwargs.get('options', [])
        timeout = kwargs.get('timeout', 30000)  # 30 seconds default
        
        # Create Server-Driven UI schema
        schema = ServerDrivenUISchema(
            component_id=f"prompt_{datetime.now().timestamp()}",
            component_type="prompt-dialog",
            properties={
                "message": text,
                "input_type": kwargs.get('input_type', 'text'),
                "options": options,
                "timeout": timeout
            },
            state={
                "visible": True,
                "response_pending": True
            },
            actions=[
                {
                    "type": "button_click",
                    "targets": [opt['id'] for opt in options] if options else ['confirm', 'cancel']
                }
            ],
            priority=kwargs.get('priority', 'high'),
            timestamp=datetime.now().isoformat()
        )
        
        return schema.model_dump()
    
    async def _generate_system_alert(self, text: str, **kwargs) -> Dict[str, Any]:
        """Generate system alert feedback"""
        severity = kwargs.get('severity', 'warning')
        urgent = kwargs.get('urgent', False)
        
        # Create Server-Driven UI schema
        schema = ServerDrivenUISchema(
            component_id=f"alert_{datetime.now().timestamp()}",
            component_type="alert-banner",
            properties={
                "message": text,
                "severity": severity,
                "sticky": urgent,
                "auto_dismiss": not urgent
            },
            state={
                "visible": True,
                "acknowledged": False
            },
            actions=[
                {
                    "type": "acknowledge",
                    "target": "alert_dismiss"
                }
            ],
            priority=kwargs.get('priority', 'high'),
            timestamp=datetime.now().isoformat()
        )
        
        return schema.model_dump()
    
    async def _generate_context_feedback(self, text: str, **kwargs) -> Dict[str, Any]:
        """Generate context-aware feedback"""
        context_data = kwargs.get('context_data', {})
        fade_after = kwargs.get('fade_after', 10000)  # 10 seconds default
        
        # Create Server-Driven UI schema
        schema = ServerDrivenUISchema(
            component_id=f"context_{datetime.now().timestamp()}",
            component_type="context-panel",
            properties={
                "title": "Context Awareness",
                "content": text,
                "context_data": context_data,
                "fade_after": fade_after
            },
            state={
                "visible": True,
                "opacity": 0.9
            },
            priority=kwargs.get('priority', 'medium'),
            timestamp=datetime.now().isoformat()
        )
        
        return schema.model_dump()
    
    def _create_error_feedback(self, error_message: str) -> Dict[str, Any]:
        """Create error feedback in case of generation failure"""
        schema = ServerDrivenUISchema(
            component_id=f"error_{datetime.now().timestamp()}",
            component_type="error-message",
            properties={
                "message": f"Error: {error_message}",
                "severity": "error"
            },
            state={
                "visible": True
            },
            priority="high",
            timestamp=datetime.now().isoformat()
        )
        
        return schema.model_dump()
    
    async def generate_structured_feedback(self, feedback_request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate feedback based on structured request
        """
        feedback_type = feedback_request.get('type', 'notification')
        content = feedback_request.get('content', 'No content provided')
        priority = feedback_request.get('priority', 'medium')
        properties = feedback_request.get('properties', {})
        
        # Merge additional properties
        properties.update({
            'priority': priority,
            **properties
        })
        
        return await self.generate(content, feedback_type, **properties)
    
    async def get_feedback_schema_example(self) -> Dict[str, Any]:
        """
        Get an example of the Server-Driven UI schema
        """
        return {
            "component_id": "example_notification_12345",
            "component_type": "notification",
            "properties": {
                "message": "System status: All systems operational",
                "severity": "info",
                "duration": 5000,
                "position": "top-right"
            },
            "state": {
                "visible": True,
                "dismissed": False
            },
            "actions": [
                {
                    "type": "dismiss",
                    "target": "notification_close"
                }
            ],
            "priority": "medium",
            "timestamp": datetime.now().isoformat()
        }


# Backward compatibility
StructuredFeedbackGenerator = FeedbackGenerator
ServerDrivenFeedbackGenerator = FeedbackGenerator