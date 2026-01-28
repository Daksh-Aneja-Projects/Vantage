"""
Project Vantage: Ambient Intelligence Platform
Main entry point for the ambient intelligence system
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List, Callable, Awaitable
from datetime import datetime
import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv
from config import get_settings

# Load environment variables
load_dotenv()

# Get application settings
app_settings = get_settings()

# Configure logging
logging.basicConfig(
    level=get_settings().log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EventBus:
    """Event bus for handling asynchronous communication between components"""
    
    def __init__(self):
        self.subscribers: Dict[str, List[Callable]] = {}
        
    def subscribe(self, event_type: str, handler: Callable):
        """Subscribe to an event type"""
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(handler)
        logger.debug(f"Subscribed handler to event type: {event_type}")
        
    def unsubscribe(self, event_type: str, handler: Callable):
        """Unsubscribe from an event type"""
        if event_type in self.subscribers:
            if handler in self.subscribers[event_type]:
                self.subscribers[event_type].remove(handler)
                logger.debug(f"Unsubscribed handler from event type: {event_type}")
        
    async def publish(self, event_type: str, data: Any):
        """Publish an event to all subscribers"""
        if event_type in self.subscribers:
            tasks = []
            for handler in self.subscribers[event_type]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        task = asyncio.create_task(handler(data))
                        tasks.append(task)
                    else:
                        # Run sync functions in thread pool
                        task = asyncio.create_task(
                            asyncio.get_event_loop().run_in_executor(None, handler, data)
                        )
                        tasks.append(task)
                except Exception as e:
                    logger.error(f"Error in event handler for {event_type}: {e}")
            
            # Wait for all handlers to complete
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        else:
            logger.debug(f"No subscribers for event type: {event_type}")


class SensorDataEvent:
    """Event representing new sensor data"""
    def __init__(self, sensor_id: str, data: Dict[str, Any], timestamp: str = None):
        self.sensor_id = sensor_id
        self.data = data
        self.timestamp = timestamp or datetime.now().isoformat()


class UserVoiceEvent:
    """Event representing user voice input"""
    def __init__(self, transcript: str, confidence: float, intent: str, timestamp: str = None):
        self.transcript = transcript
        self.confidence = confidence
        self.intent = intent
        self.timestamp = timestamp or datetime.now().isoformat()


class AmbientIntelligenceSystem:
    """
    Main class for the Ambient Intelligence System
    Coordinates all components of Project Vantage
    """
    
    def __init__(self):
        self.is_running = False
        self.components = {}
        self.context_data = {}
        self.user_preferences = {}
        self.websocket_connections: List[WebSocket] = []
        self.system_state = "idle"  # Track system state
        self.last_sensor_update = datetime.now()
        self.watchdog_timeout = get_settings().sensor_watchdog_timeout
        
        # Initialize event bus
        self.event_bus = EventBus()
        
        # Initialize DePIN integration
        self.depin_enabled = get_settings().depin_enabled
        self.wallet_address = get_settings().wallet_address
        
        # Initialize telemetry
        self.telemetry_enabled = get_settings().enable_telemetry
        self.telemetry_buffer = []
        self.max_telemetry_buffer_size = 1000
        
    def register_websocket(self, websocket: WebSocket):
        """Register a WebSocket connection"""
        if websocket not in self.websocket_connections:
            self.websocket_connections.append(websocket)
            logger.info(f"WebSocket registered. Total connections: {len(self.websocket_connections)}")
        
    def unregister_websocket(self, websocket: WebSocket):
        """Unregister a WebSocket connection"""
        if websocket in self.websocket_connections:
            self.websocket_connections.remove(websocket)
            logger.info(f"WebSocket unregistered. Total connections: {len(self.websocket_connections)}")
            
    async def broadcast_to_clients(self, message: Dict[str, Any]):
        """Broadcast a message to all connected WebSocket clients"""
        disconnected = []
        for websocket in self.websocket_connections:
            try:
                await websocket.send_json(message)
            except WebSocketDisconnect:
                disconnected.append(websocket)
            except Exception as e:
                logger.error(f"Error broadcasting to WebSocket: {e}")
                disconnected.append(websocket)
        
        # Clean up disconnected websockets
        for websocket in disconnected:
            self.unregister_websocket(websocket)
    
    async def log_telemetry(self, event_type: str, data: Dict[str, Any]):
        """Log telemetry data if enabled"""
        if not self.telemetry_enabled:
            return
            
        telemetry_entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "data": data,
            "system_state": self.system_state
        }
        
        self.telemetry_buffer.append(telemetry_entry)
        
        # Keep buffer size manageable
        if len(self.telemetry_buffer) > self.max_telemetry_buffer_size:
            self.telemetry_buffer.pop(0)
        
        # Log for debugging
        logger.debug(f"Telemetry event: {event_type} - {data}")
    
    async def get_telemetry_report(self) -> Dict[str, Any]:
        """Get a report of recent telemetry data"""
        return {
            "telemetry_enabled": self.telemetry_enabled,
            "buffer_size": len(self.telemetry_buffer),
            "recent_events": self.telemetry_buffer[-10:],  # Last 10 events
            "timestamp": datetime.now().isoformat()
        }
    
    async def initialize(self):
        """Initialize all system components"""
        logger.info("Initializing Ambient Intelligence System...")
        
        # Initialize core components based on configuration
        await self._initialize_sensor_layer()
        await self._initialize_processing_layer()
        await self._initialize_decision_layer()
        await self._initialize_interaction_layer()
        
        # Subscribe to events
        await self._setup_event_subscriptions()
        
        logger.info("All components initialized successfully")
        
    async def _setup_event_subscriptions(self):
        """Setup event subscriptions for the event bus"""
        # Subscribe to sensor data events
        self.event_bus.subscribe('sensor_data', self._handle_sensor_data_event)
        
        # Subscribe to voice events
        self.event_bus.subscribe('voice_input', self._handle_voice_event)
        
        # Subscribe to context update events
        self.event_bus.subscribe('context_update', self._handle_context_update)
        
        # Subscribe to decision events
        self.event_bus.subscribe('decision_made', self._handle_decision_event)
        
        logger.info("Event subscriptions set up")
    
    async def _handle_sensor_data_event(self, event: SensorDataEvent):
        """Handle sensor data events"""
        logger.debug(f"Handling sensor data event from {event.sensor_id}")
        
        # Process the sensor data
        processed_data = await self.components['data_ingestor'].process({
            event.sensor_id: {
                'sensor_type': 'unknown',  # Would be determined from sensor config
                'timestamp': event.timestamp,
                'data': event.data,
                'confidence': 1.0
            }
        })
        
        # Update context data
        self.context_data.update(processed_data)
        
        # Publish context update event
        await self.event_bus.publish('context_update', processed_data)
    
    async def _handle_voice_event(self, event: UserVoiceEvent):
        """Handle voice input events"""
        logger.debug(f"Handling voice event: {event.transcript}")
        
        # Process voice command based on intent
        if event.intent == 'temperature_control':
            await self._execute_action({
                'type': 'adjust_environment',
                'params': {'setting': 'temperature', 'value': event.transcript}
            })
        elif event.intent == 'lighting_control':
            await self._execute_action({
                'type': 'adjust_environment',
                'params': {'setting': 'lighting', 'value': event.transcript}
            })
        elif event.intent in ['greeting', 'help_request']:
            await self._execute_action({
                'type': 'provide_feedback',
                'params': {'text': f"I heard: {event.transcript}", 'type': 'acknowledgment'}
            })
    
    async def _handle_context_update(self, context_data: Dict[str, Any]):
        """Handle context update events"""
        logger.debug(f"Handling context update with {len(context_data)} items")
        
        # Run ML predictions
        if 'ml_pipeline' in self.components:
            predictions = await self.components['ml_pipeline'].predict(context_data)
            
            # Store predictions
            self.context_data['predictions'] = predictions
            
            # Publish prediction event
            await self.event_bus.publish('predictions_made', predictions)
    
    async def _handle_decision_event(self, decision: Dict[str, Any]):
        """Handle decision events"""
        logger.debug(f"Handling decision: {decision.get('type')}")
        
        # Execute the decision
        await self._execute_action(decision)
    
    async def _initialize_sensor_layer(self):
        """Initialize the sensory layer components"""
        from sensor_fusion.sensor_manager import SensorManager
        from sensor_fusion.data_ingestor import DataIngestor
        
        # Use configuration to determine which data ingestor to use
        app_env = get_settings().app_env
        if app_env == "production":
            logger.info("Initializing DataIngestor in production mode")
            self.components['data_ingestor'] = DataIngestor(mode="production")
        else:
            logger.info("Initializing DataIngestor in development mode")
            self.components['data_ingestor'] = DataIngestor(mode="development")
        
        self.components['sensor_manager'] = SensorManager()
        
        logger.info("Sensor layer initialized")
        
    async def _initialize_processing_layer(self):
        """Initialize the processing layer components"""
        from context_engine.context_interpreter import ContextInterpreter
        from context_engine.ml_pipeline import MLPipeline
        
        # Use configuration to determine which ML pipeline to use
        app_env = get_settings().app_env
        if app_env == "production":
            logger.info("Initializing MLPipeline in production mode with hardware acceleration")
            self.components['ml_pipeline'] = MLPipeline(mode="production")
        else:
            logger.info("Initializing MLPipeline in development mode")
            self.components['ml_pipeline'] = MLPipeline(mode="development")
        
        self.components['context_interpreter'] = ContextInterpreter()
        
        logger.info("Processing layer initialized")
        
    async def _initialize_decision_layer(self):
        """Initialize the decision layer components"""
        from ai_reasoning.reasoning_engine import ReasoningEngine
        from ai_reasoning.policy_manager import PolicyManager
        
        self.components['reasoning_engine'] = ReasoningEngine()
        self.components['policy_manager'] = PolicyManager()
        
        logger.info("Decision layer initialized")
        
    async def _initialize_interaction_layer(self):
        """Initialize the interaction layer components"""
        from user_interface.voice_processor import VoiceProcessor
        from user_interface.feedback_generator import FeedbackGenerator
        
        self.components['voice_processor'] = VoiceProcessor()
        self.components['feedback_generator'] = FeedbackGenerator()
        
        logger.info("Interaction layer initialized")
        
    async def start(self):
        """Start the ambient intelligence system"""
        if self.is_running:
            logger.warning("System is already running")
            return
            
        await self.initialize()
        
        logger.info("Starting Ambient Intelligence System...")
        self.is_running = True
        
        # Start all component loops
        await self._start_component_loops()
        
        # Start watchdog timer
        asyncio.create_task(self._watchdog_timer())
        
        # Initialize DePIN integration
        await self.initialize_depin_integration()
        
        logger.info("Ambient Intelligence System started successfully")
        
    async def _start_component_loops(self):
        """Start the main processing loops for each component"""
        # Start sensor data collection loop
        asyncio.create_task(self._sensor_loop())
        
        # Start context processing loop
        asyncio.create_task(self._context_processing_loop())
        
        # Start decision making loop
        asyncio.create_task(self._decision_making_loop())
        
        logger.info("Component loops started")
        
    async def _sensor_loop(self):
        """Main loop for collecting and processing sensor data"""
        while self.is_running:
            try:
                # Collect data from all sensors
                sensor_data = await self.components['sensor_manager'].collect_data()
                
                # Publish sensor data events
                for sensor_id, data in sensor_data.items():
                    event = SensorDataEvent(
                        sensor_id=sensor_id,
                        data=data,
                        timestamp=data.get('timestamp')
                    )
                    await self.event_bus.publish('sensor_data', event)
                
                # Update last sensor update time for watchdog
                self.last_sensor_update = datetime.now()
                
                # Small delay to prevent overwhelming but responsive
                await asyncio.sleep(0.05)
                
            except Exception as e:
                logger.error(f"Error in sensor loop: {e}")
                await asyncio.sleep(0.1)  # Brief pause before continuing
                
    async def _context_processing_loop(self):
        """Main loop for context interpretation and understanding"""
        while self.is_running:
            try:
                if self.context_data:
                    # Interpret the current context
                    context_analysis = await self.components['context_interpreter'].analyze(
                        self.context_data
                    )
                    
                    # Update context with analysis
                    self.context_data.update(context_analysis)
                    
                    # Publish context update event
                    await self.event_bus.publish('context_update', context_analysis)
                    
                await asyncio.sleep(0.2)  # Reduced delay for more responsive context processing
                
            except Exception as e:
                logger.error(f"Error in context processing loop: {e}")
                await asyncio.sleep(0.5)  # Reduced pause
                
    async def _decision_making_loop(self):
        """Main loop for decision making and action planning"""
        while self.is_running:
            try:
                if self.context_data and 'predictions' in self.context_data:
                    # Make decisions based on context and predictions
                    decisions = await self.components['reasoning_engine'].make_decisions(
                        self.context_data
                    )
                    
                    # Apply policies to decisions
                    filtered_decisions = await self.components['policy_manager'].apply_policies(
                        decisions, self.user_preferences
                    )
                    
                    # Publish decision events
                    for decision in filtered_decisions:
                        await self.event_bus.publish('decision_made', decision)
                        
                await asyncio.sleep(0.5)  # More responsive decision loop
                
            except Exception as e:
                logger.error(f"Error in decision making loop: {e}")
                await asyncio.sleep(0.5)  # Reduced pause
                
    async def _execute_action(self, decision: Dict[str, Any]):
        """Execute a specific action decided by the system"""
        try:
            action_type = decision.get('type')
            action_params = decision.get('params', {})
            
            if action_type == 'adjust_environment':
                await self._adjust_environment(action_params)
            elif action_type == 'provide_feedback':
                await self._provide_feedback(action_params)
            elif action_type == 'request_input':
                await self._request_input(action_params)
            else:
                logger.warning(f"Unknown action type: {action_type}")
                
        except Exception as e:
            logger.error(f"Error executing action: {e}")
            
    async def _adjust_environment(self, params: Dict[str, Any]):
        """Adjust environmental settings based on decisions"""
        logger.info(f"Adjusting environment: {params}")
        # This would interface with IoT devices to adjust lighting, temperature, etc.
        
    async def _provide_feedback(self, params: Dict[str, Any]):
        """Provide feedback to the user"""
        feedback_text = params.get('text', '')
        feedback_type = params.get('type', 'notification')
        
        # Generate and present feedback
        feedback = await self.components['feedback_generator'].generate(
            feedback_text, feedback_type
        )
        
        logger.info(f"Providing feedback: {feedback}")
        
    async def _request_input(self, params: Dict[str, Any]):
        """Request input from the user when needed"""
        request_text = params.get('prompt', 'How can I help you?')
        
        # This would typically involve voice or other interaction channels
        logger.info(f"Requesting input: {request_text}")
        
    async def _watchdog_timer(self):
        """Monitor system health and restart components if needed"""
        while self.is_running:
            try:
                current_time = datetime.now()
                time_since_sensor_update = (current_time - self.last_sensor_update).seconds
                
                if time_since_sensor_update > self.watchdog_timeout:
                    logger.warning(f"Sensor manager timeout detected ({time_since_sensor_update}s). Restarting...")
                    # Attempt to restart sensor manager
                    await self._restart_sensor_manager()
                    
                await asyncio.sleep(0.5)  # Check more frequently
                
            except Exception as e:
                logger.error(f"Error in watchdog timer: {e}")
                await asyncio.sleep(0.5)
                
    async def _restart_sensor_manager(self):
        """Restart the sensor manager component"""
        try:
            logger.info("Restarting sensor manager...")
            if 'sensor_manager' in self.components:
                # Reinitialize sensor manager
                from sensor_fusion.sensor_manager import SensorManager
                self.components['sensor_manager'] = SensorManager()
                logger.info("Sensor manager restarted")
        except Exception as e:
            logger.error(f"Failed to restart sensor manager: {e}")
    
    async def initialize_depin_integration(self):
        """Initialize DePIN integration for compute-for-content economy"""
        if not self.depin_enabled:
            logger.info("DePIN integration disabled")
            return
        
        try:
            # Initialize DePIN components
            logger.info(f"Initializing DePIN integration with wallet: {self.wallet_address}")
            
            # Here we would initialize actual DePIN integration
            # For now, we'll just set up the structure
            self.depin_jobs_queue = []
            self.depin_completed_jobs = []
            self.depin_rewards_balance = 0.0
            self.depin_active = True
            
            logger.info("DePIN integration initialized successfully")
            
            # Start DePIN job processor if enabled
            if self.depin_enabled:
                asyncio.create_task(self._process_depin_jobs())
                
        except Exception as e:
            logger.error(f"Failed to initialize DePIN integration: {e}")
            self.depin_active = False
    
    async def _process_depin_jobs(self):
        """Process DePIN jobs in the background"""
        while self.is_running and self.depin_enabled:
            try:
                if self.depin_jobs_queue:
                    # Process next job in queue
                    job = self.depin_jobs_queue.pop(0)
                    
                    # Simulate job processing
                    await self._execute_depin_job(job)
                    
                    # Add reward for completed job
                    await self._add_depin_reward(job.get('reward', 0.01))
                
                await asyncio.sleep(2)  # Check for new jobs more frequently
                
            except Exception as e:
                logger.error(f"Error processing DePIN jobs: {e}")
                await asyncio.sleep(5)  # Wait longer on error
    
    async def _execute_depin_job(self, job: Dict[str, Any]):
        """Execute a specific DePIN job"""
        job_id = job.get('id', 'unknown')
        job_type = job.get('type', 'unknown')
        
        logger.info(f"Executing DePIN job {job_id} of type {job_type}")
        
        # Process the job based on type
        if job_type == 'ml_inference':
            # Execute ML inference job using our models
            result = await self._execute_ml_inference_job(job)
        elif job_type == 'data_processing':
            # Process data using our pipeline
            result = await self._process_data_job(job)
        elif job_type == 'context_analysis':
            # Analyze context data
            result = await self._analyze_context_job(job)
        else:
            # Unknown job type, return generic result
            result = {'status': 'completed', 'result': 'unknown_job_type'}
        
        # Record job completion
        job['result'] = result
        job['completed_at'] = datetime.now().isoformat()
        self.depin_completed_jobs.append(job)
        
        logger.info(f"Completed DePIN job {job_id}")
    
    async def _execute_ml_inference_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """Execute ML inference job"""
        try:
            # Get input data from job
            input_data = job.get('input_data', {})
            
            # Use our ML pipeline for inference
            if 'ml_pipeline' in self.components:
                result = await self.components['ml_pipeline'].predict(input_data)
                return {'status': 'success', 'result': result}
            else:
                return {'status': 'error', 'message': 'ML pipeline not available'}
        except Exception as e:
            logger.error(f"Error executing ML inference job: {e}")
            return {'status': 'error', 'message': str(e)}
    
    async def _process_data_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """Process data job"""
        try:
            # Get input data from job
            input_data = job.get('input_data', {})
            
            # Use our data ingestor for processing
            if 'data_ingestor' in self.components:
                result = await self.components['data_ingestor'].process(input_data)
                return {'status': 'success', 'result': result}
            else:
                return {'status': 'error', 'message': 'Data ingestor not available'}
        except Exception as e:
            logger.error(f"Error processing data job: {e}")
            return {'status': 'error', 'message': str(e)}
    
    async def _analyze_context_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze context job"""
        try:
            # Get context data from job
            context_data = job.get('context_data', {})
            
            # Use our context interpreter for analysis
            if 'context_interpreter' in self.components:
                result = await self.components['context_interpreter'].analyze(context_data)
                return {'status': 'success', 'result': result}
            else:
                return {'status': 'error', 'message': 'Context interpreter not available'}
        except Exception as e:
            logger.error(f"Error analyzing context job: {e}")
            return {'status': 'error', 'message': str(e)}
    
    async def _add_depin_reward(self, amount: float):
        """Add rewards to DePIN balance"""
        self.depin_rewards_balance += amount
        logger.info(f"Added {amount} to DePIN rewards balance. New balance: {self.depin_rewards_balance}")
    
    async def submit_depin_job(self, job: Dict[str, Any]) -> str:
        """Submit a job to the DePIN network"""
        if not self.depin_enabled:
            logger.warning("DePIN not enabled, cannot submit job")
            return "depin_not_enabled"
        
        job_id = job.get('id', f"job_{datetime.now().timestamp()}")
        job['id'] = job_id
        job['submitted_at'] = datetime.now().isoformat()
        
        self.depin_jobs_queue.append(job)
        logger.info(f"Submitted DePIN job {job_id}")
        
        return job_id
    
    async def get_depin_status(self) -> Dict[str, Any]:
        """Get current DePIN status and statistics"""
        return {
            'enabled': self.depin_enabled,
            'active': getattr(self, 'depin_active', False),
            'wallet_address': self.wallet_address,
            'jobs_queued': len(self.depin_jobs_queue),
            'jobs_completed': len(self.depin_completed_jobs),
            'rewards_balance': self.depin_rewards_balance,
            'timestamp': datetime.now().isoformat()
        }
    
    async def stop(self):
        """Stop the ambient intelligence system"""
        logger.info("Stopping Ambient Intelligence System...")
        self.is_running = False
        
        # Stop all component loops gracefully
        # Cleanup resources
        
        logger.info("Ambient Intelligence System stopped")


async def main():
    """Main entry point with improved error handling and monitoring"""
    system = AmbientIntelligenceSystem()
    
    try:
        # Set up signal handlers for graceful shutdown
        import signal
        
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown...")
            system.is_running = False
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        await system.start()
        
        # Event-driven service - no blocking loop needed
        # The system runs on event callbacks and async tasks
            
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}")
        logger.exception("Full traceback:")
    finally:
        await system.stop()
        logger.info("System shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())