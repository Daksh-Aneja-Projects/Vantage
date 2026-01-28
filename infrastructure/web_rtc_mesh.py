"""
WebRTC Mesh Networking for Project Vantage
Implements peer-to-peer communication with STUN/TURN servers for NAT traversal
"""
import asyncio
import logging
import json
import base64
import hashlib
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
import uuid

# WebRTC imports
try:
    from aiortc import (
        RTCPeerConnection,
        RTCSessionDescription,
        RTCIceCandidate,
        MediaStreamTrack,
        VideoStreamTrack,
        AudioStreamTrack
    )
    from aiortc.contrib.media import MediaBlackhole, MediaPlayer, MediaRecorder
    from aiortc.contrib.signaling import BYE, object_from_string, object_to_string
    WEBRTC_AVAILABLE = True
except ImportError:
    WEBRTC_AVAILABLE = False
    print("Warning: aiortc not available. WebRTC functionality disabled.")

logger = logging.getLogger(__name__)


class ConnectionRole(Enum):
    """Peer connection roles"""
    INITIATOR = "initiator"
    RECEIVER = "receiver"


class SignalingChannel:
    """Handles signaling messages for WebRTC connection establishment"""
    
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.peers: Dict[str, 'MeshPeer'] = {}
        self.pending_offers: Dict[str, Dict[str, Any]] = {}
        self.message_handlers: Dict[str, Callable] = {}
        
    async def send_signaling_message(self, target_peer_id: str, message: Dict[str, Any]):
        """Send signaling message to peer through discovery service"""
        # In production, this would use the network manager's discovery service
        # For now, we'll simulate direct peer communication
        if target_peer_id in self.peers:
            await self.peers[target_peer_id].handle_signaling_message(message)
            
    async def broadcast_signaling_message(self, message: Dict[str, Any]):
        """Broadcast signaling message to all peers"""
        for peer_id in self.peers:
            await self.send_signaling_message(peer_id, message)
            
    def register_message_handler(self, message_type: str, handler: Callable):
        """Register handler for specific message types"""
        self.message_handlers[message_type] = handler
        
    async def handle_incoming_message(self, message: Dict[str, Any]):
        """Handle incoming signaling message"""
        msg_type = message.get('type')
        if msg_type in self.message_handlers:
            await self.message_handlers[msg_type](message)


@dataclass
class PeerInfo:
    """Information about a peer in the mesh"""
    peer_id: str
    device_role: str
    capabilities: List[str]
    last_seen: datetime
    connection_status: str = "disconnected"
    public_key: Optional[str] = None


class MeshPeer:
    """Represents a peer in the WebRTC mesh network"""
    
    def __init__(self, peer_id: str, signaling_channel: SignalingChannel):
        self.peer_id = peer_id
        self.signaling_channel = signaling_channel
        self.connection: Optional[RTCPeerConnection] = None
        self.data_channel = None
        self.video_track = None
        self.audio_track = None
        self.is_connected = False
        self.role: Optional[ConnectionRole] = None
        self.peer_info: Optional[PeerInfo] = None
        
    async def initialize_connection(self, role: ConnectionRole) -> bool:
        """Initialize WebRTC peer connection with STUN/TURN servers for NAT traversal"""
        if not WEBRTC_AVAILABLE:
            logger.error("WebRTC not available")
            return False
            
        try:
            self.role = role
            
            # Configure the connection with STUN/TURN servers
            ice_servers = [
                {"urls": server} for server in self.signaling_channel.stun_servers
            ]
            
            # Add TURN servers if available
            if hasattr(self.signaling_channel, 'turn_servers'):
                ice_servers.extend(self.signaling_channel.turn_servers)
            
            # Add fallback STUN server
            if hasattr(self.signaling_channel, 'fallback_stun'):
                ice_servers.append({"urls": self.signaling_channel.fallback_stun})
            
            # Create connection with ICE servers configuration
            self.connection = RTCPeerConnection({'iceServers': ice_servers})
            
            # Set up connection event handlers
            self.connection.on("connectionstatechange", self._on_connection_state_change)
            self.connection.on("icecandidate", self._on_ice_candidate)
            self.connection.on("datachannel", self._on_data_channel)
            
            # Create data channel for messaging
            if role == ConnectionRole.INITIATOR:
                self.data_channel = self.connection.createDataChannel("vantage-mesh")
                self.data_channel.on("open", self._on_data_channel_open)
                self.data_channel.on("message", self._on_data_channel_message)
                
            logger.info(f"Initialized WebRTC connection for peer {self.peer_id} with {len(ice_servers)} ICE servers")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize WebRTC connection: {e}")
            return False
    
    async def create_offer(self) -> Optional[RTCSessionDescription]:
        """Create SDP offer for connection initiation"""
        try:
            if not self.connection:
                raise RuntimeError("Connection not initialized")
                
            # Add media tracks if needed
            # self.connection.addTrack(VideoStreamTrack())  # For video streaming
            # self.connection.addTrack(AudioStreamTrack())  # For audio streaming
            
            # Create offer
            offer = await self.connection.createOffer()
            await self.connection.setLocalDescription(offer)
            
            logger.info(f"Created SDP offer for peer {self.peer_id}")
            return offer
            
        except Exception as e:
            logger.error(f"Failed to create SDP offer: {e}")
            return None
    
    async def handle_offer(self, offer: RTCSessionDescription) -> Optional[RTCSessionDescription]:
        """Handle incoming SDP offer and create answer"""
        try:
            if not self.connection:
                await self.initialize_connection(ConnectionRole.RECEIVER)
                
            await self.connection.setRemoteDescription(offer)
            
            # Create answer
            answer = await self.connection.createAnswer()
            await self.connection.setLocalDescription(answer)
            
            logger.info(f"Created SDP answer for peer {self.peer_id}")
            return answer
            
        except Exception as e:
            logger.error(f"Failed to handle SDP offer: {e}")
            return None
    
    async def handle_answer(self, answer: RTCSessionDescription):
        """Handle SDP answer from peer"""
        try:
            if not self.connection:
                raise RuntimeError("Connection not initialized")
                
            await self.connection.setRemoteDescription(answer)
            logger.info(f"Set SDP answer from peer {self.peer_id}")
            
        except Exception as e:
            logger.error(f"Failed to handle SDP answer: {e}")
    
    async def add_ice_candidate(self, candidate: RTCIceCandidate):
        """Add ICE candidate for connection establishment"""
        try:
            if self.connection:
                await self.connection.addIceCandidate(candidate)
                logger.debug(f"Added ICE candidate for peer {self.peer_id}")
        except Exception as e:
            logger.error(f"Failed to add ICE candidate: {e}")
    
    async def send_message(self, message: Dict[str, Any]) -> bool:
        """Send message through data channel"""
        try:
            if not self.data_channel or self.data_channel.readyState != "open":
                logger.warning(f"Data channel not ready for peer {self.peer_id}")
                return False
                
            message_str = json.dumps(message)
            self.data_channel.send(message_str)
            logger.debug(f"Sent message to peer {self.peer_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send message to peer {self.peer_id}: {e}")
            return False
    
    async def close_connection(self):
        """Close the WebRTC connection"""
        try:
            if self.data_channel:
                self.data_channel.close()
                
            if self.connection:
                await self.connection.close()
                
            self.is_connected = False
            logger.info(f"Closed connection with peer {self.peer_id}")
            
        except Exception as e:
            logger.error(f"Error closing connection: {e}")
    
    def _on_connection_state_change(self):
        """Handle connection state changes"""
        if self.connection:
            state = self.connection.connectionState
            logger.info(f"Connection state changed for {self.peer_id}: {state}")
            
            if state == "connected":
                self.is_connected = True
            elif state in ["failed", "closed", "disconnected"]:
                self.is_connected = False
    
    def _on_ice_candidate(self, candidate):
        """Handle ICE candidate generation"""
        if candidate:
            # Send ICE candidate to peer through signaling
            signaling_msg = {
                "type": "ice_candidate",
                "candidate": {
                    "candidate": candidate.candidate,
                    "sdpMid": candidate.sdpMid,
                    "sdpMLineIndex": candidate.sdpMLineIndex
                },
                "sender": self.signaling_channel.device_id
            }
            asyncio.create_task(
                self.signaling_channel.send_signaling_message(self.peer_id, signaling_msg)
            )
    
    def _on_data_channel(self, channel):
        """Handle incoming data channel"""
        self.data_channel = channel
        channel.on("open", self._on_data_channel_open)
        channel.on("message", self._on_data_channel_message)
        logger.info(f"Data channel established with {self.peer_id}")
    
    def _on_data_channel_open(self):
        """Handle data channel opening"""
        logger.info(f"Data channel opened with {self.peer_id}")
        self.is_connected = True
        
    def _on_data_channel_message(self, message):
        """Handle incoming data channel message"""
        try:
            message_data = json.loads(message)
            logger.debug(f"Received message from {self.peer_id}: {message_data}")
            # Forward to signaling channel for processing
            asyncio.create_task(
                self.signaling_channel.handle_incoming_message(message_data)
            )
        except Exception as e:
            logger.error(f"Error processing data channel message: {e}")
    
    async def handle_signaling_message(self, message: Dict[str, Any]):
        """Handle signaling message from this peer"""
        msg_type = message.get('type')
        
        if msg_type == 'offer':
            offer = RTCSessionDescription(
                sdp=message['sdp'],
                type='offer'
            )
            answer = await self.handle_offer(offer)
            if answer:
                response = {
                    "type": "answer",
                    "sdp": answer.sdp,
                    "sender": self.signaling_channel.device_id
                }
                await self.signaling_channel.send_signaling_message(self.peer_id, response)
                
        elif msg_type == 'answer':
            answer = RTCSessionDescription(
                sdp=message['sdp'],
                type='answer'
            )
            await self.handle_answer(answer)
            
        elif msg_type == 'ice_candidate':
            candidate_data = message['candidate']
            candidate = RTCIceCandidate(
                candidate=candidate_data['candidate'],
                sdpMid=candidate_data['sdpMid'],
                sdpMLineIndex=candidate_data['sdpMLineIndex']
            )
            await self.add_ice_candidate(candidate)


class WebRTCMeshNetwork:
    """
    Main WebRTC mesh network manager implementing peer-to-peer communication
    """
    
    def __init__(self, device_id: str, device_role: str):
        self.device_id = device_id
        self.device_role = device_role
        self.signaling_channel = SignalingChannel(device_id)
        self.peers: Dict[str, MeshPeer] = {}
        self.peer_info: Dict[str, PeerInfo] = {}
        self.is_running = False
        self.stun_servers = [
            "stun:stun.l.google.com:19302",
            "stun:stun1.l.google.com:19302",
            "stun:stun.cloudflare.com:3478",
            "stun:stun.counterpath.com:3478"
        ]
        # TURN server configuration for NAT traversal
        self.turn_servers = [
            {
                "urls": ["turn:turn.example.com:3478?transport=udp"],
                "username": "vantage_user",
                "credential": "vantage_password"
            },
            {
                "urls": ["turn:turn.example.com:3478?transport=tcp"],
                "username": "vantage_user",
                "credential": "vantage_password"
            }
        ]
        # Fallback STUN server
        self.fallback_stun = "stun:global.stun.twilio.com:3478"
        
    async def initialize(self) -> bool:
        """Initialize the WebRTC mesh network"""
        try:
            # Register signaling message handlers
            self.signaling_channel.register_message_handler('mesh_discovery', self._handle_mesh_discovery)
            self.signaling_channel.register_message_handler('peer_join', self._handle_peer_join)
            self.signaling_channel.register_message_handler('peer_leave', self._handle_peer_leave)
            
            self.is_running = True
            logger.info("WebRTC mesh network initialized")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize WebRTC mesh: {e}")
            return False
    
    async def join_mesh(self, peer_discovery_info: Dict[str, Any]) -> bool:
        """Join an existing mesh network"""
        try:
            peer_id = peer_discovery_info['peer_id']
            
            # Create peer connection
            peer = MeshPeer(peer_id, self.signaling_channel)
            await peer.initialize_connection(ConnectionRole.INITIATOR)
            
            # Create and send offer
            offer = await peer.create_offer()
            if offer:
                signaling_message = {
                    "type": "offer",
                    "sdp": offer.sdp,
                    "sender": self.device_id,
                    "target": peer_id
                }
                
                await self.signaling_channel.send_signaling_message(peer_id, signaling_message)
                self.peers[peer_id] = peer
                
                # Store peer info
                self.peer_info[peer_id] = PeerInfo(
                    peer_id=peer_id,
                    device_role=peer_discovery_info.get('device_role', 'unknown'),
                    capabilities=peer_discovery_info.get('capabilities', []),
                    last_seen=datetime.now(),
                    connection_status="connecting"
                )
                
                logger.info(f"Initiated connection with peer {peer_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to join mesh: {e}")
            return False
    
    async def broadcast_message(self, message: Dict[str, Any]) -> Dict[str, bool]:
        """Broadcast message to all connected peers"""
        results = {}
        
        for peer_id, peer in self.peers.items():
            if peer.is_connected:
                success = await peer.send_message(message)
                results[peer_id] = success
            else:
                results[peer_id] = False
                
        return results
    
    async def send_direct_message(self, peer_id: str, message: Dict[str, Any]) -> bool:
        """Send direct message to specific peer"""
        if peer_id in self.peers and self.peers[peer_id].is_connected:
            return await self.peers[peer_id].send_message(message)
        return False
    
    async def get_mesh_status(self) -> Dict[str, Any]:
        """Get current mesh network status"""
        return {
            'device_id': self.device_id,
            'device_role': self.device_role,
            'is_running': self.is_running,
            'connected_peers': len([p for p in self.peers.values() if p.is_connected]),
            'total_peers': len(self.peers),
            'peer_details': [
                {
                    'peer_id': peer_id,
                    'is_connected': peer.is_connected,
                    'role': self.peer_info.get(peer_id, {}).device_role if peer_id in self.peer_info else 'unknown'
                }
                for peer_id, peer in self.peers.items()
            ],
            'timestamp': datetime.now().isoformat()
        }
    
    async def shutdown(self):
        """Shutdown the mesh network"""
        self.is_running = False
        
        # Close all peer connections
        for peer in self.peers.values():
            await peer.close_connection()
            
        self.peers.clear()
        self.peer_info.clear()
        logger.info("WebRTC mesh network shutdown complete")
    
    async def _handle_mesh_discovery(self, message: Dict[str, Any]):
        """Handle mesh discovery messages"""
        # Process discovery information and potentially initiate connections
        logger.debug(f"Received mesh discovery: {message}")
        
    async def _handle_peer_join(self, message: Dict[str, Any]):
        """Handle peer joining the mesh"""
        peer_id = message.get('peer_id')
        if peer_id and peer_id not in self.peers:
            # A new peer wants to join, create connection
            await self.join_mesh(message)
            
    async def _handle_peer_leave(self, message: Dict[str, Any]):
        """Handle peer leaving the mesh"""
        peer_id = message.get('peer_id')
        if peer_id in self.peers:
            await self.peers[peer_id].close_connection()
            del self.peers[peer_id]
            if peer_id in self.peer_info:
                del self.peer_info[peer_id]
            logger.info(f"Peer {peer_id} left the mesh")


# Backward compatibility alias
WebRTCNetworkManager = WebRTCMeshNetwork