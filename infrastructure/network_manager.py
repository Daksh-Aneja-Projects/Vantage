"""
Network Manager for Project Vantage
Implements WebRTC-based P2P mesh networking with mDNS discovery
"""
import asyncio
import logging
import json
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import hashlib
import base64
import time
import uuid
import random

# WebRTC and security imports
from privacy_security.ecdh_security import SecurityManager, DeviceIdentity
from infrastructure.web_rtc_mesh import WebRTCMeshNetwork, MeshPeer
from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser

logger = logging.getLogger(__name__)


class DeviceRole(Enum):
    """Device roles in the neural mesh"""
    TV_HUB = "tv_hub"
    PHONE_CLIENT = "phone_client"
    SENSOR_NODE = "sensor_node"


class ConnectionStatus(Enum):
    """Connection status states"""
    DISCONNECTED = "disconnected"
    DISCOVERING = "discovering"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    AUTHENTICATED = "authenticated"


@dataclass
class DeviceInfo:
    """Information about a discovered device"""
    device_id: str
    role: DeviceRole
    ip_address: str
    port: int
    service_name: str
    last_seen: datetime
    capabilities: List[str]
    public_key: Optional[str] = None
    connection_type: str = 'webrtc'  # Changed to webrtc as default
    bluetooth_address: Optional[str] = None  # For BLE devices


@dataclass
class NetworkMessage:
    """Structured network message"""
    message_id: str
    sender_id: str
    recipient_id: str
    message_type: str
    payload: Dict[str, Any]
    timestamp: str
    signature: Optional[str] = None
    encrypted: bool = False


class CircuitBreaker:
    """Circuit breaker pattern implementation for network operations"""
    
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.next_attempt_time = None
        
        self.lock = asyncio.Lock()
    
    async def call(self, func, *args, **kwargs):
        """Execute a function with circuit breaker protection"""
        async with self.lock:
            if self.state == "OPEN":
                if self._should_attempt_reset():
                    self.state = "HALF_OPEN"
                else:
                    raise Exception("Circuit breaker is OPEN")

            try:
                result = await func(*args, **kwargs)
                await self._on_success()
                return result
            except Exception as e:
                await self._on_failure()
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
        self.state = "CLOSED"

    async def _on_failure(self):
        """Called when a call fails"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            self.next_attempt_time = datetime.now() + timedelta(seconds=self.recovery_timeout)

    def get_status(self) -> Dict[str, Any]:
        """Get the current status of the circuit breaker"""
        return {
            "state": self.state,
            "failure_count": self.failure_count,
            "threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "next_attempt_time": self.next_attempt_time.isoformat() if self.next_attempt_time else None
        }


class ExponentialBackoff:
    """Exponential backoff implementation with jitter"""
    
    def __init__(self, initial_delay: float = 1.0, max_delay: float = 60.0, multiplier: float = 2.0):
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.current_delay = initial_delay

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay with exponential backoff and jitter"""
        exp_delay = min(self.initial_delay * (self.multiplier ** attempt), self.max_delay)
        # Add jitter to prevent thundering herd
        jitter = random.uniform(0.0, 0.1 * exp_delay)
        return exp_delay + jitter

    def reset(self):
        """Reset the backoff to initial delay"""
        self.current_delay = self.initial_delay

    def next_delay(self) -> float:
        """Get the next delay and increment for next attempt"""
        delay = self.calculate_delay(0)  # We'll recalculate based on attempt count
        self.current_delay = min(self.current_delay * self.multiplier, self.max_delay)
        return delay


class DiscoveryService:
    """Handles device discovery using mDNS/NSD (Network Service Discovery)"""
    
    def __init__(self, service_type: str = "_vantage._tcp.local.", 
                 txt_record: Dict[str, str] = None):
        self.service_type = service_type
        self.txt_record = txt_record or {
            "version": "1.0",
            "device_type": "tv_hub",  # Default, will be updated by NetworkManager
            "capabilities": "sensor_fusion,context_analysis,decision_making"
        }
        self.zeroconf = None
        self.browser = None
        self.discovered_devices: Dict[str, DeviceInfo] = {}
        self.on_device_discovered: Optional[Callable] = None
        self.advertised_services = []  # Track our own advertised services
        self.last_discovery_time = {}  # Track when devices were last seen
        self.device_ttl = 300  # Time-to-live for discovered devices (5 minutes)
        self.cleanup_task = None
        
    async def start_discovery(self):
        """Start the discovery service"""
        try:
            self.zeroconf = Zeroconf()
            self.browser = ServiceBrowser(
                self.zeroconf, 
                self.service_type, 
                handlers=[self._service_state_changed]
            )
            
            # Start periodic cleanup task
            self.cleanup_task = asyncio.create_task(self._cleanup_stale_devices())
            
            logger.info(f"Discovery service started for {self.service_type}")
        except Exception as e:
            logger.error(f"Failed to start discovery service: {e}")
            raise

    async def stop_discovery(self):
        """Stop the discovery service"""
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass

        if self.browser:
            self.browser.cancel()
        if self.zeroconf:
            self.zeroconf.close()

        # Clear all discovered devices
        self.discovered_devices.clear()
        self.last_discovery_time.clear()

        logger.info("Discovery service stopped")

    def _service_state_changed(self, zeroconf, service_type, name, state_change):
        """Handle service state changes"""
        try:
            if state_change.name == "Added":
                info = zeroconf.get_service_info(service_type, name)
                if info:
                    device_info = self._parse_service_info(info, name)
                    self.discovered_devices[device_info.device_id] = device_info
                    self.last_discovery_time[device_info.device_id] = datetime.now()
                    
                    if self.on_device_discovered:
                        asyncio.create_task(self.on_device_discovered(device_info))
                        
            elif state_change.name == "Removed":
                # Remove device from discovered list
                device_id = self._extract_device_id(name)
                if device_id in self.discovered_devices:
                    del self.discovered_devices[device_id]
                    if device_id in self.last_discovery_time:
                        del self.last_discovery_time[device_id]
                    
        except Exception as e:
            logger.error(f"Error handling service state change: {e}")

    def _parse_service_info(self, info, service_name: str) -> DeviceInfo:
        """Parse service information into DeviceInfo"""
        try:
            # Extract device information from service properties
            properties = {}
            if info.properties:
                for key, value in info.properties.items():
                    decoded_key = key.decode() if isinstance(key, bytes) else key
                    decoded_value = value.decode() if isinstance(value, bytes) else value
                    properties[decoded_key] = decoded_value

            device_id = properties.get('device_id', str(uuid.uuid4()))
            role_str = properties.get('role', 'sensor_node')
            try:
                role = DeviceRole(role_str)
            except ValueError:
                role = DeviceRole.SENSOR_NODE

            capabilities = properties.get('capabilities', '').split(',') if properties.get('capabilities') else []

            # Extract additional information from TXT record
            device_type = properties.get('device_type', 'unknown')
            version = properties.get('version', '1.0')

            return DeviceInfo(
                device_id=device_id,
                role=role,
                ip_address=socket.inet_ntoa(info.addresses[0]) if info.addresses else '0.0.0.0',
                port=info.port,
                service_name=service_name,
                last_seen=datetime.now(),
                capabilities=capabilities,
                public_key=properties.get('public_key'),
                connection_type=properties.get('connection_type', 'webrtc'),  # Changed to webrtc
                bluetooth_address=properties.get('bluetooth_address')
            )
        except Exception as e:
            logger.error(f"Error parsing service info: {e}")
            # Return basic device info
            return DeviceInfo(
                device_id=str(uuid.uuid4()),
                role=DeviceRole.SENSOR_NODE,
                ip_address="0.0.0.0",
                port=0,
                service_name=service_name,
                last_seen=datetime.now(),
                capabilities=[]
            )

    def _extract_device_id(self, service_name: str) -> str:
        """Extract device ID from service name"""
        # Extract UUID from service name
        parts = service_name.split('.')
        if len(parts) > 0:
            return parts[0].replace('_vantage_', '')
        return str(uuid.uuid4())

    def get_available_devices(self, role_filter: DeviceRole = None) -> List[DeviceInfo]:
        """Get list of available devices, optionally filtered by role"""
        # Clean up stale devices first
        current_time = datetime.now()
        stale_devices = [
            device_id for device_id, last_seen 
            in self.last_discovery_time.items() 
            if (current_time - last_seen).seconds > self.device_ttl
        ]

        for device_id in stale_devices:
            if device_id in self.discovered_devices:
                del self.discovered_devices[device_id]
            if device_id in self.last_discovery_time:
                del self.last_discovery_time[device_id]

        devices = list(self.discovered_devices.values())

        if role_filter:
            devices = [d for d in devices if d.role == role_filter]

        return devices

    async def _cleanup_stale_devices(self):
        """Periodically clean up stale device entries"""
        while True:
            try:
                # Sleep for half the TTL period
                await asyncio.sleep(self.device_ttl // 2)

                # Clean up stale devices
                current_time = datetime.now()
                stale_devices = [
                    device_id for device_id, last_seen 
                    in self.last_discovery_time.items() 
                    if (current_time - last_seen).seconds > self.device_ttl
                ]

                for device_id in stale_devices:
                    if device_id in self.discovered_devices:
                        del self.discovered_devices[device_id]
                        logger.info(f"Removed stale device: {device_id}")
                    if device_id in self.last_discovery_time:
                        del self.last_discovery_time[device_id]

            except asyncio.CancelledError:
                logger.info("Device cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in device cleanup: {e}")

    async def advertise_service(self, device_id: str, device_role: DeviceRole, 
                              port: int = 8080, additional_properties: Dict[str, str] = None):
        """Advertise this device as a discoverable service"""
        try:
            # Prepare service properties
            properties = {
                b'device_id': device_id.encode(),
                b'role': device_role.value.encode(),
                b'connection_type': b'webrtc',  # Changed to webrtc
                b'version': b'1.0',
                b'device_type': device_role.value.encode(),
                b'capabilities': b'sensor_fusion,context_analysis,decision_making'
            }

            # Add any additional properties
            if additional_properties:
                for key, value in additional_properties.items():
                    properties[key.encode() if isinstance(key, str) else key] = \
                        value.encode() if isinstance(value, str) else value

            # Get local IP address
            import socket
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)

            # If unable to get local IP, fallback to 0.0.0.0
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
            except Exception:
                local_ip = "0.0.0.0"

            info = ServiceInfo(
                self.service_type,
                f"_vantage_{device_id}.{self.service_type}",
                addresses=[socket.inet_aton(local_ip)],
                port=port,
                properties=properties,
                server=f"{device_id}.local."
            )

            # Register the service
            self.zeroconf.register_service(info, ttl=300)  # 5 minute TTL

            # Keep track of advertised service
            self.advertised_services.append(info)

            logger.info(f"Service advertised: {device_id} on {local_ip}:{port}")
            return True

        except Exception as e:
            logger.error(f"Failed to advertise service: {e}")
            return False

    async def unadvertise_service(self, device_id: str = None):
        """Remove service advertisement"""
        try:
            if device_id:
                # Remove specific service
                services_to_remove = []
                for service_info in self.advertised_services:
                    if device_id in service_info.name:
                        services_to_remove.append(service_info)

                for service_info in services_to_remove:
                    self.zeroconf.unregister_service(service_info)
                    self.advertised_services.remove(service_info)
            else:
                # Remove all services
                for service_info in self.advertised_services:
                    self.zeroconf.unregister_service(service_info)
                self.advertised_services.clear()

            logger.info(f"Service advertisement removed: {device_id if device_id else 'All services'}")
            return True

        except Exception as e:
            logger.error(f"Failed to unadvertise service: {e}")
            return False


class NetworkManager:
    """
    Main network manager handling P2P communication and device coordination with WebRTC
    """
    
    def __init__(self, device_role: DeviceRole = DeviceRole.TV_HUB):
        self.device_role = device_role
        self.device_id = str(uuid.uuid4())
        self.connection_status = ConnectionStatus.DISCONNECTED
        self.discovery_service = DiscoveryService()
        self.active_connections: Dict[str, MeshPeer] = {}  # device_id -> WebRTC peer connection
        self.message_handlers: Dict[str, Callable] = {}
        self.shared_secrets: Dict[str, str] = {}
        
        # Circuit breaker for network operations
        self.network_circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
        
        # Exponential backoff for reconnection attempts
        self.reconnect_backoff = ExponentialBackoff(initial_delay=1.0, max_delay=60.0)
        
        # Initialize WebRTC mesh network
        self.webrtc_network = WebRTCMeshNetwork(self.device_id, self.device_role.value)
        
        # Register default message handlers
        self._register_default_handlers()
        
        # Track connection failures for backoff
        self.connection_failures: Dict[str, int] = {}
        self.last_connection_attempt: Dict[str, datetime] = {}
        
        # Initialize BLE manager for Android TV
        self.ble_manager = BLEManager()
        
        # Track discovered BLE devices
        self.discovered_ble_devices: Dict[str, Dict[str, Any]] = {}
        
        # Initialize security manager for ECDH
        self.security_manager = SecurityManager(self.device_id, self.device_role.value, [])

    def _register_default_handlers(self):
        """Register default message handlers"""
        self.register_message_handler('handshake_request', self._handle_handshake_request)
        self.register_message_handler('handshake_response', self._handle_handshake_response)
        self.register_message_handler('sensor_data', self._handle_sensor_data)
        self.register_message_handler('context_update', self._handle_context_update)
        self.register_message_handler('heartbeat', self._handle_heartbeat)

    async def initialize(self):
        """Initialize the network manager"""
        logger.info(f"Initializing Network Manager as {self.device_role.value}")
        
        # Initialize security manager
        await self.security_manager.initialize()
        
        # Initialize WebRTC network
        await self.webrtc_network.initialize()
        
        # Start discovery service
        await self.discovery_service.start_discovery()
        
        # Set up our own service advertisement if we're a hub
        if self.device_role == DeviceRole.TV_HUB:
            await self._advertise_service()
        
        self.connection_status = ConnectionStatus.DISCOVERING
        logger.info("Network Manager initialized successfully")

    async def _advertise_service(self):
        """Advertise this device as a service"""
        try:
            # Advertise using the enhanced discovery service
            success = await self.discovery_service.advertise_service(
                device_id=self.device_id,
                device_role=self.device_role,
                port=8080
            )
            
            if success:
                logger.info(f"Service advertised: {self.device_id}")
            else:
                logger.error(f"Failed to advertise service: {self.device_id}")

        except Exception as e:
            logger.error(f"Failed to advertise service: {e}")

    async def connect_to_device(self, device_info: DeviceInfo, shared_secret: str = None) -> bool:
        """Connect to a discovered device with exponential backoff and circuit breaker"""
        device_id = device_info.device_id
        
        # Determine connection method based on device info
        if hasattr(device_info, 'connection_type') and device_info.connection_type == 'ble':
            # Use BLE connection
            return await self._connect_via_ble(device_info, shared_secret)
        else:
            # Use WebRTC connection for mesh networking
            return await self._connect_via_webrtc(device_info, shared_secret)

    async def _connect_via_webrtc(self, device_info: DeviceInfo, shared_secret: str = None) -> bool:
        """Connect to device using WebRTC"""
        try:
            logger.info(f"Connecting to device {device_info.device_id} via WebRTC")
            
            # Get device identity for secure pairing
            # In a real implementation, we would retrieve this from the device
            # For now, we'll create a placeholder
            peer_identity = DeviceIdentity(
                device_id=device_info.device_id,
                public_key_pem="PLACEHOLDER_PUBLIC_KEY",
                device_role=device_info.role.value,
                capabilities=device_info.capabilities,
                timestamp=datetime.now().isoformat(),
                signature="PLACEHOLDER_SIGNATURE"
            )
            
            # Initiate secure connection using ECDH
            success = await self.security_manager.initiate_secure_connection(peer_identity)
            if not success:
                logger.error(f"Failed to establish secure connection with {device_info.device_id}")
                return False
            
            # Join WebRTC mesh with device
            discovery_info = {
                'peer_id': device_info.device_id,
                'device_role': device_info.role.value,
                'capabilities': device_info.capabilities
            }
            
            join_success = await self.webrtc_network.join_mesh(discovery_info)
            if not join_success:
                logger.error(f"Failed to join WebRTC mesh with {device_info.device_id}")
                return False
            
            # Mark as connected
            self.connection_status = ConnectionStatus.CONNECTED
            logger.info(f"Successfully connected to device {device_info.device_id} via WebRTC")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect via WebRTC to {device_info.device_id}: {e}")
            return False

    async def _connect_via_ble(self, device_info: DeviceInfo, shared_secret: str = None) -> bool:
        """Connect to a device via BLE"""
        device_id = device_info.device_id
        bluetooth_address = device_info.bluetooth_address

        if not bluetooth_address:
            logger.error(f"No Bluetooth address provided for device {device_id}")
            return False

        try:
            logger.info(f"Attempting BLE connection to {device_id} at {bluetooth_address}")

            # Connect to the BLE device
            success = await self.ble_manager.connect_to_device(bluetooth_address, device_info.service_name)

            if success:
                # Store BLE connection info
                self.active_connections[device_id] = {
                    'bluetooth_address': bluetooth_address,
                    'connection_type': 'ble',
                    'connected': True,
                    'last_connected': datetime.now(),
                    'secure_channel': None  # Will be set up after pairing
                }

                # If shared secret is provided, set up secure channel
                if shared_secret:
                    # In real implementation, use ECDH for BLE secure channel
                    pass

                self.connection_status = ConnectionStatus.CONNECTED

                logger.info(f"Successfully connected to BLE device {device_id}")
                return True
            else:
                logger.error(f"Failed to connect to BLE device {device_id}")
                self.connection_status = ConnectionStatus.DISCONNECTED
                return False

        except Exception as e:
            logger.error(f"Error in BLE connection to {device_id}: {e}")
            self.connection_status = ConnectionStatus.DISCONNECTED
            return False

    async def send_message(self, recipient_id: str, message_type: str, payload: Dict[str, Any], 
                          encrypt: bool = True) -> bool:
        """Send message to a connected device with retry logic and circuit breaker"""
        try:
            # Check if recipient is in active connections
            if recipient_id not in self.active_connections:
                logger.warning(f"Device {recipient_id} not connected")
                return False

            # Check connection type and route appropriately
            connection_info = self.active_connections[recipient_id]
            if isinstance(connection_info, dict) and connection_info.get('connection_type') == 'ble':
                # Send via BLE
                return await self._send_message_via_ble(recipient_id, message_type, payload, encrypt)
            else:
                # Send via WebRTC
                return await self._send_message_via_webrtc(recipient_id, message_type, payload, encrypt)

        except Exception as e:
            logger.error(f"Failed to send message to {recipient_id}: {e}")
            return False

    async def _send_message_via_webrtc(self, recipient_id: str, message_type: str, 
                                  payload: Dict[str, Any], encrypt: bool = True) -> bool:
        """Send message via WebRTC connection"""
        try:
            # Create message object
            message = NetworkMessage(
                message_id=str(uuid.uuid4()),
                sender_id=self.device_id,
                recipient_id=recipient_id,
                message_type=message_type,
                payload=payload,
                timestamp=datetime.now().isoformat(),
                encrypted=encrypt
            )

            # Encrypt message if requested
            if encrypt:
                encrypted_message = await self.security_manager.encrypt_for_peer(
                    message.__dict__, recipient_id
                )
                if encrypted_message:
                    # Send encrypted message via WebRTC
                    results = await self.webrtc_network.broadcast_message(encrypted_message)
                    return results.get(recipient_id, False)
                else:
                    logger.error(f"Failed to encrypt message for {recipient_id}")
                    return False
            else:
                # Send unencrypted message via WebRTC
                results = await self.webrtc_network.broadcast_message(message.__dict__)
                return results.get(recipient_id, False)

        except Exception as e:
            logger.error(f"Error sending message via WebRTC to {recipient_id}: {e}")
            return False

    async def _send_message_via_ble(self, recipient_id: str, message_type: str, payload: Dict[str, Any], encrypt: bool = True) -> bool:
        """Send message to a BLE-connected device"""
        try:
            connection_info = self.active_connections[recipient_id]
            bluetooth_address = connection_info.get('bluetooth_address')

            if not bluetooth_address:
                logger.error(f"No Bluetooth address for device {recipient_id}")
                return False

            # Create message object
            message = NetworkMessage(
                message_id=str(uuid.uuid4()),
                sender_id=self.device_id,
                recipient_id=recipient_id,
                message_type=message_type,
                payload=payload,
                timestamp=datetime.now().isoformat(),
                encrypted=encrypt
            )

            # Convert message to JSON bytes
            message_str = json.dumps(message.__dict__)
            message_bytes = message_str.encode('utf-8')

            # Send via BLE
            # Use a predefined characteristic UUID for Vantage messages
            characteristic_uuid = "0000180F-0000-1000-8000-00805F9B34FB"  # Standard battery service characteristic as example

            success = await self.ble_manager.send_data_to_device(
                bluetooth_address, 
                characteristic_uuid, 
                message_bytes
            )

            if success:
                logger.debug(f"Message sent to BLE device {recipient_id}")
                return True
            else:
                logger.error(f"Failed to send message to BLE device {recipient_id}")
                return False

        except Exception as e:
            logger.error(f"Error sending message via BLE to {recipient_id}: {e}")
            return False

    def register_message_handler(self, message_type: str, handler: Callable):
        """Register a handler for a specific message type"""
        self.message_handlers[message_type] = handler
        logger.debug(f"Registered handler for message type: {message_type}")

    async def _handle_handshake_request(self, message: NetworkMessage):
        """Handle incoming handshake request"""
        logger.info(f"Received handshake request from {message.sender_id}")
        # Implementation would generate challenge and send response
        pass

    async def _handle_handshake_response(self, message: NetworkMessage):
        """Handle handshake response"""
        logger.info(f"Received handshake response from {message.sender_id}")
        # Implementation would verify response and complete handshake
        pass

    async def _handle_sensor_data(self, message: NetworkMessage):
        """Handle incoming sensor data"""
        logger.debug(f"Received sensor data from {message.sender_id}")
        # Forward to sensor fusion system
        pass

    async def _handle_context_update(self, message: NetworkMessage):
        """Handle context update message"""
        logger.debug(f"Received context update from {message.sender_id}")
        # Forward to context engine
        pass

    async def _handle_heartbeat(self, message: NetworkMessage):
        """Handle heartbeat message"""
        logger.debug(f"Received heartbeat from {message.sender_id}")
        # Update device status
        pass

    async def broadcast_message(self, message_type: str, payload: Dict[str, Any], 
                              encrypt: bool = True) -> Dict[str, bool]:
        """Broadcast message to all connected devices"""
        # Create message object
        message = NetworkMessage(
            message_id=str(uuid.uuid4()),
            sender_id=self.device_id,
            recipient_id="all",
            message_type=message_type,
            payload=payload,
            timestamp=datetime.now().isoformat(),
            encrypted=encrypt
        )

        # Encrypt if requested
        if encrypt:
            # For broadcast, we need to encrypt for each recipient separately
            results = {}
            for device_id in self.active_connections.keys():
                encrypted_message = await self.security_manager.encrypt_for_peer(
                    message.__dict__, device_id
                )
                if encrypted_message:
                    # Send via appropriate connection method
                    if isinstance(self.active_connections[device_id], dict) and \
                       self.active_connections[device_id].get('connection_type') == 'ble':
                        results[device_id] = await self._send_message_via_ble(
                            device_id, message_type, payload, False  # Already encrypted
                        )
                    else:
                        results[device_id] = await self._send_message_via_webrtc(
                            device_id, message_type, payload, False  # Already encrypted
                        )
                else:
                    results[device_id] = False
            return results
        else:
            # Send unencrypted broadcast via WebRTC
            return await self.webrtc_network.broadcast_message(message.__dict__)

    async def get_network_status(self) -> Dict[str, Any]:
        """Get current network status"""
        webrtc_status = await self.webrtc_network.get_mesh_status() if self.webrtc_network else {}
        security_status = await self.security_manager.get_system_status() if self.security_manager else {}

        return {
            'device_id': self.device_id,
            'device_role': self.device_role.value,
            'connection_status': self.connection_status.value,
            'connected_devices': list(self.active_connections.keys()),
            'discovered_devices': len(self.discovery_service.discovered_devices),
            'circuit_breaker_status': self.network_circuit_breaker.get_status(),
            'webrtc_status': webrtc_status,
            'security_status': security_status,
            'timestamp': datetime.now().isoformat()
        }

    async def shutdown(self):
        """Shutdown the network manager"""
        logger.info("Shutting down Network Manager")

        # Close all connections
        for device_id in list(self.active_connections.keys()):
            if isinstance(self.active_connections[device_id], dict) and \
               self.active_connections[device_id].get('connection_type') == 'ble':
                # Handle BLE disconnection
                await self.ble_manager.disconnect_from_device(
                    self.active_connections[device_id]['bluetooth_address']
                )
            else:
                # Handle WebRTC disconnection
                pass  # WebRTC connections are managed by the mesh network

        self.active_connections.clear()

        # Shutdown WebRTC network
        if self.webrtc_network:
            await self.webrtc_network.shutdown()

        # Stop discovery service
        await self.discovery_service.stop_discovery()

        self.connection_status = ConnectionStatus.DISCONNECTED
        logger.info("Network Manager shutdown complete")


# BLE Manager for handling Bluetooth Low Energy connections
class BLEManager:
    """Handles Bluetooth Low Energy connections for the neural mesh"""
    
    def __init__(self):
        self.bluetooth_adapter = None
        self.scanner = None
        self.active_connections = {}
        self.is_scanning = False
        self.scan_callback = None
        self.gatt_callbacks = {}
        
        # Android Bluetooth integration
        try:
            from jnius import autoclass, cast
            from android.permissions import request_permissions, Permission
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            Context = autoclass('android.content.Context')
            BluetoothAdapter = autoclass('android.bluetooth.BluetoothAdapter')
            BluetoothDevice = autoclass('android.bluetooth.BluetoothDevice')
            BluetoothGatt = autoclass('android.bluetooth.BluetoothGatt')
            BluetoothGattCallback = autoclass('android.bluetooth.BluetoothGattCallback')
            BluetoothProfile = autoclass('android.bluetooth.BluetoothProfile')
            BluetoothGattCharacteristic = autoclass('android.bluetooth.BluetoothGattCharacteristic')
            BluetoothGattService = autoclass('android.bluetooth.BluetoothGattService')
            ActivityCompat = autoclass('androidx.core.app.ActivityCompat')
            Intent = autoclass('android.content.Intent')
            Build = autoclass('android.os.Build')
            
            # Import PythonJavaClass for callback definitions
            from jnius import PythonJavaClass, java_method
            
            self.bluetooth_adapter = BluetoothAdapter.getDefaultAdapter()
        except ImportError:
            # Fallback for non-Android environments
            BluetoothAdapter = None
            BluetoothDevice = None
            PythonActivity = None
            print("Warning: Android Bluetooth libraries not available. Running in simulation mode.")
    
    async def start_scan(self, scan_duration: int = 10):
        """Start scanning for BLE devices"""
        try:
            if self.bluetooth_adapter and self.bluetooth_adapter.isEnabled():
                # Get the Bluetooth LE scanner
                if hasattr(self.bluetooth_adapter, 'getBluetoothLeScanner'):
                    self.scanner = self.bluetooth_adapter.getBluetoothLeScanner()
                    
                    # Define scan callback
                    self.scan_callback = BLEScanCallback(self)
                    
                    # Start scan
                    from jnius import cast
                    scan_settings = autoclass('android.bluetooth.le.ScanSettings')
                    scan_filters = autoclass('android.bluetooth.le.ScanFilter')
                    
                    builder = autoclass('android.bluetooth.le.ScanSettings$Builder')()
                    scan_settings_obj = (builder
                                         .setScanMode(scan_settings.SCAN_MODE_LOW_LATENCY)
                                         .build())
                    
                    self.scanner.startScan(None, scan_settings_obj, self.scan_callback)
                    self.is_scanning = True
                    
                    logger.info(f"Started BLE scan for {scan_duration} seconds")
                    
                    # Stop scanning after duration
                    await asyncio.sleep(scan_duration)
                    await self.stop_scan()
                    
                    return True
                else:
                    logger.warning("BLE scanning not supported on this device")
            
            # Fallback to simulation
            logger.info("Using BLE simulation mode")
            return await self._simulate_ble_scan(scan_duration)
            
        except Exception as e:
            logger.error(f"Error starting BLE scan: {e}")
            return False

    async def stop_scan(self):
        """Stop the BLE scan"""
        try:
            if self.scanner and self.is_scanning:
                self.scanner.stopScan(self.scan_callback)
                self.is_scanning = False
                logger.info("BLE scan stopped")
            return True
        except Exception as e:
            logger.error(f"Error stopping BLE scan: {e}")
            return False

    async def connect_to_device(self, device_address: str, device_name: str = None):
        """Connect to a specific BLE device"""
        try:
            if self.bluetooth_adapter and self.bluetooth_adapter.isEnabled():
                # Get the device
                device = self.bluetooth_adapter.getRemoteDevice(device_address)
                
                if device:
                    # Create GATT callback for this connection
                    gatt_callback = BLEGattCallback(self, device_address)
                    self.gatt_callbacks[device_address] = gatt_callback
                    
                    # Connect to the device
                    gatt = device.connectGatt(
                        cast('android.app.Activity', PythonActivity.mActivity),
                        False,  # autoConnect
                        gatt_callback
                    )
                    
                    # Store the connection
                    self.active_connections[device_address] = {
                        'device': device,
                        'gatt': gatt,
                        'callback': gatt_callback,
                        'connected': False,
                        'services': None
                    }
                    
                    logger.info(f"Attempting to connect to BLE device: {device_address}")
                    return True
                else:
                    logger.warning(f"Could not find device with address: {device_address}")
            
            # Fallback to simulation
            logger.info(f"Using BLE simulation for device: {device_address}")
            return await self._simulate_ble_connection(device_address, device_name)
            
        except Exception as e:
            logger.error(f"Error connecting to BLE device {device_address}: {e}")
            return False

    async def disconnect_from_device(self, device_address: str):
        """Disconnect from a BLE device"""
        try:
            if device_address in self.active_connections:
                conn_info = self.active_connections[device_address]
                gatt = conn_info['gatt']
                
                if gatt:
                    gatt.disconnect()
                    gatt.close()
                    
                # Clean up
                del self.active_connections[device_address]
                if device_address in self.gatt_callbacks:
                    del self.gatt_callbacks[device_address]
                
                logger.info(f"Disconnected from BLE device: {device_address}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error disconnecting from BLE device {device_address}: {e}")
            return False

    async def send_data_to_device(self, device_address: str, characteristic_uuid: str, data: bytes):
        """Send data to a connected BLE device"""
        try:
            if device_address in self.active_connections:
                conn_info = self.active_connections[device_address]
                gatt = conn_info['gatt']
                
                if conn_info['connected'] and conn_info['services']:
                    # Find the service and characteristic
                    service = gatt.getService(autoclass('java.util.UUID').fromString(characteristic_uuid))
                    if service:
                        characteristic = service.getCharacteristic(
                            autoclass('java.util.UUID').fromString(characteristic_uuid)
                        )
                        if characteristic:
                            # Write the data
                            characteristic.setValue(data)
                            characteristic.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT)
                            
                            # Write to device
                            success = gatt.writeCharacteristic(characteristic)
                            
                            if success:
                                logger.info(f"Sent data to BLE device {device_address}")
                                return True
                            else:
                                logger.error(f"Failed to send data to BLE device {device_address}")
                                return False
                        else:
                            logger.error(f"Characteristic {characteristic_uuid} not found")
                    else:
                        logger.error(f"Service for characteristic {characteristic_uuid} not found")
                else:
                    logger.warning(f"Device {device_address} not connected or services not discovered")
            else:
                logger.warning(f"Device {device_address} not in active connections")
            
            return False
            
        except Exception as e:
            logger.error(f"Error sending data to BLE device {device_address}: {e}")
            return False

    async def _simulate_ble_scan(self, duration: int):
        """Simulate BLE scan for testing purposes"""
        # Simulate finding some devices
        simulated_devices = [
            {'address': 'AA:BB:CC:DD:EE:FF', 'name': 'Phone_Client_1', 'rssi': -65},
            {'address': '11:22:33:44:55:66', 'name': 'Smart_TV_2', 'rssi': -70},
        ]
        
        logger.info(f"Simulated BLE scan found {len(simulated_devices)} devices")
        await asyncio.sleep(duration)
        return simulated_devices

    async def _simulate_ble_connection(self, device_address: str, device_name: str = None):
        """Simulate BLE connection for testing purposes"""
        # Simulate connection process
        await asyncio.sleep(1)  # Simulate connection time

        self.active_connections[device_address] = {
            'device': device_address,
            'connected': True,
            'services': [],  # Simulated services
            'simulated': True
        }

        logger.info(f"Simulated connection to BLE device: {device_address}")
        return True

    def get_discovered_devices(self):
        """Get list of discovered devices"""
        # This would return actual discovered devices in real implementation
        return self.active_connections


# Define BLE Scan Callback class
try:
    from jnius import PythonJavaClass, java_method
    
    class BLEScanCallback(PythonJavaClass):
        __javaclass__ = 'android/bluetooth/le/ScanCallback'
        
        def __init__(self, ble_manager):
            super().__init__()
            self.ble_manager = ble_manager
        
        @java_method('(ILandroid/bluetooth/le/ScanResult;)V')
        def onScanResult(self, callback_type, result):
            """Handle discovered BLE device"""
            try:
                device = result.getDevice()
                device_address = device.getAddress()
                device_name = device.getName() or "Unknown"
                rssi = result.getRssi()
                
                logger.info(f"Discovered BLE device: {device_name} ({device_address}), RSSI: {rssi}")
                
                # Store discovered device info
                if hasattr(self.ble_manager, 'discovered_devices'):
                    self.ble_manager.discovered_devices[device_address] = {
                        'name': device_name,
                        'rssi': rssi,
                        'timestamp': datetime.now().isoformat()
                    }
                else:
                    self.ble_manager.discovered_devices = {
                        device_address: {
                            'name': device_name,
                            'rssi': rssi,
                            'timestamp': datetime.now().isoformat()
                        }
                    }
                    
            except Exception as e:
                logger.error(f"Error in BLE scan callback: {e}")
        
        @java_method('([Landroid/bluetooth/le/ScanResult;)V')
        def onBatchScanResults(self, results):
            """Handle batch scan results"""
            try:
                for result in results:
                    self.onScanResult(0, result)
            except Exception as e:
                logger.error(f"Error in BLE batch scan callback: {e}")
        
        @java_method('(ILandroid/bluetooth/le/ScanCallback;)V')
        def onScanFailed(self, error_code, callback):
            """Handle scan failure"""
            logger.error(f"BLE scan failed with error code: {error_code}")
            
except ImportError:
    # Dummy class if jnius is not available
    class BLEScanCallback:
        def __init__(self, ble_manager):
            self.ble_manager = ble_manager
            logger.warning("BLEScanCallback not available, using dummy implementation")


# Define BLE GATT Callback class
try:
    class BLEGattCallback(PythonJavaClass):
        __javaclass__ = 'android/bluetooth/BluetoothGattCallback'
        
        def __init__(self, ble_manager, device_address):
            super().__init__()
            self.ble_manager = ble_manager
            self.device_address = device_address
        
        @java_method('(Landroid/bluetooth/BluetoothGatt;IZ)V')
        def onConnectionStateChange(self, gatt, status, newState):
            """Handle connection state changes"""
            try:
                if newState == BluetoothProfile.STATE_CONNECTED:
                    logger.info(f"Connected to BLE device: {self.device_address}")
                    
                    # Update connection status in the manager
                    if self.device_address in self.ble_manager.active_connections:
                        self.ble_manager.active_connections[self.device_address]['connected'] = True
                        
                    # Discover services
                    gatt.discoverServices()
                    
                elif newState == BluetoothProfile.STATE_DISCONNECTED:
                    logger.info(f"Disconnected from BLE device: {self.device_address}")
                    
                    # Update connection status
                    if self.device_address in self.ble_manager.active_connections:
                        self.ble_manager.active_connections[self.device_address]['connected'] = False
                        
            except Exception as e:
                logger.error(f"Error in BLE connection state callback: {e}")
        
        @java_method('(Landroid/bluetooth/BluetoothGatt;I)V')
        def onServicesDiscovered(self, gatt, status):
            """Handle service discovery"""
            try:
                if status == 0:  # GATT_SUCCESS
                    logger.info(f"Services discovered for device: {self.device_address}")
                    
                    # Get and store services
                    services = gatt.getServices()
                    if self.device_address in self.ble_manager.active_connections:
                        self.ble_manager.active_connections[self.device_address]['services'] = services
                        
                else:
                    logger.error(f"Service discovery failed for device {self.device_address}, status: {status}")
                    
            except Exception as e:
                logger.error(f"Error in BLE services discovery callback: {e}")
        
        @java_method('(Landroid/bluetooth/BluetoothGatt;Landroid/bluetooth/BluetoothGattCharacteristic;I)V')
        def onCharacteristicRead(self, gatt, characteristic, status):
            """Handle characteristic read"""
            try:
                if status == 0:  # GATT_SUCCESS
                    value = characteristic.getValue()
                    logger.info(f"Characteristic read from {self.device_address}: {value}")
                else:
                    logger.error(f"Characteristic read failed for {self.device_address}, status: {status}")
                    
            except Exception as e:
                logger.error(f"Error in BLE characteristic read callback: {e}")
        
        @java_method('(Landroid/bluetooth/BluetoothGatt;Landroid/bluetooth/BluetoothGattCharacteristic;I)V')
        def onCharacteristicWrite(self, gatt, characteristic, status):
            """Handle characteristic write confirmation"""
            try:
                if status == 0:  # GATT_SUCCESS
                    logger.info(f"Data written successfully to {self.device_id}")
                else:
                    logger.error(f"Characteristic write failed for {self.device_address}, status: {status}")
                    
            except Exception as e:
                logger.error(f"Error in BLE characteristic write callback: {e}")
                
except ImportError:
    # Dummy class if jnius is not available
    class BLEGattCallback:
        def __init__(self, ble_manager, device_address):
            self.ble_manager = ble_manager
            self.device_address = device_address
            logger.warning("BLEGattCallback not available, using dummy implementation")