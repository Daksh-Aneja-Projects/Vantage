"""
Voice Processor for Project Vantage
Handles voice input and natural language processing
"""

import asyncio
import logging
from typing import Dict, Any, Optional, AsyncGenerator
from datetime import datetime
import numpy as np

# Import universal dubber
from ..voice_processing.universal_dubber import universal_dubber, initialize_universal_dubber, get_universal_dubber
from ..voice_processing.universal_dubber import LanguageCode, DubbingQuality

logger = logging.getLogger(__name__)


class VoiceActivityDetector:
    """Voice Activity Detection implementation"""
    
    def __init__(self, silence_threshold=0.01, speech_threshold=0.05, frame_duration=0.03):
        self.silence_threshold = silence_threshold
        self.speech_threshold = speech_threshold
        self.frame_duration = frame_duration
        self.is_speaking = False
        self.frames_of_silence = 0
        self.min_silence_frames = 10  # Minimum frames of silence to stop
        
    def detect_vad(self, audio_frame: np.ndarray) -> bool:
        """
        Detect voice activity in an audio frame
        Returns True if speech is detected, False if silence
        """
        # Calculate RMS energy of the frame
        rms_energy = np.sqrt(np.mean(audio_frame ** 2))
        
        if rms_energy > self.speech_threshold:
            # Speech detected
            self.is_speaking = True
            self.frames_of_silence = 0
            return True
        elif rms_energy < self.silence_threshold:
            # Silence detected
            self.frames_of_silence += 1
            if self.is_speaking and self.frames_of_silence >= self.min_silence_frames:
                # End of speech segment
                self.is_speaking = False
            return False
        else:
            # Between thresholds - maintain current state
            if self.is_speaking:
                self.frames_of_silence = 0
            return self.is_speaking


class StreamingSTTInterface:
    """Streaming Speech-to-Text interface"""
    
    def __init__(self, vad_detector: VoiceActivityDetector):
        self.vad_detector = vad_detector
        self.is_listening = False
        self.audio_buffer = []
        self.transcription_buffer = ""
        
    async def start_streaming(self):
        """Start the streaming STT service"""
        self.is_listening = True
        logger.info("Started streaming STT service")
        
    async def stop_streaming(self):
        """Stop the streaming STT service"""
        self.is_listening = False
        logger.info("Stopped streaming STT service")
        
    async def process_audio_chunk(self, audio_chunk: bytes) -> Optional[str]:
        """
        Process an audio chunk and return transcription if available
        """
        if not self.is_listening:
            return None
            
        # Convert audio chunk to numpy array for VAD
        try:
            # Simulate converting bytes to numpy array
            # In a real implementation, this would decode the audio
            audio_array = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32) / 32768.0
        except:
            # If conversion fails, simulate with random data
            audio_array = np.random.rand(1024).astype(np.float32)
        
        # Run VAD on the audio
        is_speech = self.vad_detector.detect_vad(audio_array)
        
        if is_speech:
            # Accumulate audio for transcription
            self.audio_buffer.append(audio_chunk)
            # For simulation, return a simulated transcription
            return self._simulate_transcription(audio_chunk)
        else:
            # If we were speaking and now we're silent, transcribe accumulated audio
            if len(self.audio_buffer) > 0:
                # Transcribe the accumulated audio
                final_transcription = await self._finalize_transcription()
                self.audio_buffer.clear()
                return final_transcription
        
        return None
    
    def _simulate_transcription(self, audio_chunk: bytes) -> str:
        """Simulate STT transcription for demonstration purposes"""
        # In a real implementation, this would call a real STT service
        import random
        possible_phrases = [
            "Turn on the lights",
            "What's the weather like?",
            "Set temperature to 22 degrees",
            "Play some music",
            "Good morning",
            "How are you today?",
            "Increase brightness",
            "Dim the lights"
        ]
        return random.choice(possible_phrases)
    
    async def _finalize_transcription(self) -> str:
        """Finalize transcription of accumulated audio"""
        # Simulate final transcription
        import random
        possible_final_phrases = [
            "Turn on the lights",
            "What's the weather like?",
            "Set temperature to 22 degrees",
            "Play some music",
            "Good morning",
            "How are you today?",
            "Increase brightness",
            "Dim the lights"
        ]
        return random.choice(possible_final_phrases)


class VoiceProcessor:
    """
    Handles voice input and natural language processing
    """
    
    def __init__(self):
        self.is_active = False
        self.listening_keywords = []
        self.command_history = []
        self.language_model = None
        self.vad_detector = VoiceActivityDetector()
        self.streaming_stt = StreamingSTTInterface(self.vad_detector)
        self.universal_dubber = None  # Initialize later
        
        # Initialize default keywords
        self._setup_default_keywords()
        
    async def initialize(self):
        """Initialize the voice processor with additional components"""
        # Initialize universal dubber
        self.universal_dubber = get_universal_dubber()
        if not await initialize_universal_dubber():
            logger.warning("Failed to initialize universal dubber")
        else:
            logger.info("Universal dubber initialized successfully")
    
    def _setup_default_keywords(self):
        """Setup default listening keywords"""
        self.listening_keywords = [
            'Hey Vantage',
            'Project Vantage',
            'Hello',
            'Vantage'
        ]
        
    async def start_listening(self):
        """Start listening for voice commands"""
        self.is_active = True
        await self.streaming_stt.start_streaming()
        logger.info("Voice processor started listening")
        
    async def stop_listening(self):
        """Stop listening for voice commands"""
        self.is_active = False
        await self.streaming_stt.stop_streaming()
        logger.info("Voice processor stopped listening")
        
    async def process_audio_input(self, audio_data: bytes) -> Dict[str, Any]:
        """
        Process raw audio input and convert to text/command
        """
        # Use streaming STT to process the audio
        transcription = await self.streaming_stt.process_audio_chunk(audio_data)
        
        if transcription:
            result = {
                'transcript': transcription,
                'confidence': 0.85,  # Higher confidence for streaming STT
                'intent': 'unknown',
                'entities': [],
                'timestamp': datetime.now().isoformat()
            }
            
            # Parse intent from the transcript
            intent_result = await self.parse_intent(transcription)
            result['intent'] = intent_result['intent']
            result['entities'] = intent_result['entities']
            result['confidence'] = intent_result['confidence']
            
            # Log the command
            self.command_history.append(result)
            if len(self.command_history) > 100:
                self.command_history = self.command_history[-50:]  # Keep last 50 commands
            
            return result
        else:
            # No speech detected in this chunk
            return {
                'transcript': '',
                'confidence': 0.0,
                'intent': 'silence',
                'entities': [],
                'timestamp': datetime.now().isoformat()
            }
    
    async def detect_wake_word(self, audio_data: bytes) -> bool:
        """
        Detect wake word in audio input using VAD
        """
        # Convert audio to numpy array for VAD processing
        try:
            audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
        except:
            audio_array = np.random.rand(1024).astype(np.float32)
        
        # Use VAD to detect if there's speech
        is_speech = self.vad_detector.detect_vad(audio_array)
        
        if is_speech:
            # If speech is detected, we'd need to run keyword spotting
            # For simulation, return True occasionally when speech is detected
            import random
            return random.random() < 0.3  # 30% chance of wake word detection when speech is present
        else:
            return False
    
    async def parse_intent(self, text: str) -> Dict[str, Any]:
        """
        Parse intent from text input
        """
        # Simple rule-based intent parsing
        text_lower = text.lower()
        
        if any(word in text_lower for word in ['temperature', 'heat', 'cool', 'warm']):
            intent = 'temperature_control'
        elif any(word in text_lower for word in ['light', 'lamp', 'brightness', 'brighten', 'dim']):
            intent = 'lighting_control'
        elif any(word in text_lower for word in ['security', 'safe', 'alarm', 'monitor']):
            intent = 'security_control'
        elif any(word in text_lower for word in ['hello', 'hi', 'hey', 'good morning', 'good evening']):
            intent = 'greeting'
        elif any(word in text_lower for word in ['help', 'assist', 'what can you do']):
            intent = 'help_request'
        elif any(word in text_lower for word in ['turn on', 'activate', 'enable']):
            intent = 'activate_device'
        elif any(word in text_lower for word in ['turn off', 'deactivate', 'disable']):
            intent = 'deactivate_device'
        elif any(word in text_lower for word in ['set', 'change', 'adjust']):
            intent = 'adjust_setting'
        # Add new intents for dubbing functionality
        elif any(word in text_lower for word in ['dub', 'translate', 'language', 'subtitle', 'sync']):
            intent = 'dubbing_request'
        else:
            intent = 'unknown'
        
        result = {
            'intent': intent,
            'confidence': 0.9 if intent != 'unknown' else 0.3,
            'entities': await self._extract_entities(text)
        }
        
        # Handle dubbing request specifically
        if intent == 'dubbing_request':
            result.update(await self._handle_dubbing_request(text))
        
        return result

    async def _handle_dubbing_request(self, text: str) -> Dict[str, Any]:
        """Handle dubbing-specific requests"""
        entities = await self._extract_entities(text)
        result = {'dubbing_action': 'none'}
        
        if self.universal_dubber:
            # Extract language information from the request
            target_language = entities.get('target_language', 'english')
            source_language = entities.get('source_language', 'english')
            
            # Map language names to LanguageCode enums
            lang_map = {
                'english': LanguageCode.ENGLISH,
                'spanish': LanguageCode.SPANISH,
                'french': LanguageCode.FRENCH,
                'german': LanguageCode.GERMAN,
                'japanese': LanguageCode.JAPANESE,
                'korean': LanguageCode.KOREAN,
                'chinese': LanguageCode.CHINESE,
                'portuguese': LanguageCode.PORTUGUESE,
                'russian': LanguageCode.RUSSIAN,
                'arabic': LanguageCode.ARABIC
            }
            
            source_lang = lang_map.get(source_language.lower(), LanguageCode.ENGLISH)
            target_lang = lang_map.get(target_language.lower(), LanguageCode.ENGLISH)
            
            result['dubbing_action'] = 'available'
            result['supported_languages'] = [lang.value for lang in await self.universal_dubber.get_supported_languages()]
            result['source_language'] = source_lang.value
            result['target_language'] = target_lang.value
            
            # Extract any video content reference if available
            if 'video' in entities or 'content' in entities:
                result['video_available'] = True
                result['can_process_dubbing'] = True
        else:
            result['dubbing_action'] = 'unavailable'
            result['error'] = 'Universal dubber not initialized'
        
        return result
    
    async def process_video_dubbing(self, video_bytes: bytes, 
                                  source_language: str = 'english', 
                                  target_language: str = 'spanish') -> Optional[Dict[str, Any]]:
        """Process video dubbing request"""
        if not self.universal_dubber:
            logger.error("Universal dubber not initialized")
            return None
        
        # Map language names to LanguageCode enums
        lang_map = {
            'english': LanguageCode.ENGLISH,
            'spanish': LanguageCode.SPANISH,
            'french': LanguageCode.FRENCH,
            'german': LanguageCode.GERMAN,
            'japanese': LanguageCode.JAPANESE,
            'korean': LanguageCode.KOREAN,
            'chinese': LanguageCode.CHINESE,
            'portuguese': LanguageCode.PORTUGUESE,
            'russian': LanguageCode.RUSSIAN,
            'arabic': LanguageCode.ARABIC
        }
        
        source_lang = lang_map.get(source_language.lower(), LanguageCode.ENGLISH)
        target_lang = lang_map.get(target_language.lower(), LanguageCode.SPANISH)
        
        # Perform the dubbing
        result = await self.universal_dubber.dub_video_content(
            video_bytes=video_bytes,
            source_language=source_lang,
            target_language=target_lang,
            quality=DubbingQuality.HIGH
        )
        
        return result

    async def _extract_entities(self, text: str) -> Dict[str, Any]:
        """
        Extract entities from text
        """
        entities = {}
        
        # Simple entity extraction
        if 'degrees' in text or '°' in text:
            import re
            matches = re.findall(r'(\d+)\s*°?F?|C?', text)
            if matches:
                entities['temperature'] = float(matches[0])
        
        if any(word in text.lower() for word in ['high', 'maximum', 'full']):
            entities['intensity'] = 'high'
        elif any(word in text.lower() for word in ['low', 'minimum', 'dim']):
            entities['intensity'] = 'low'
        elif any(word in text.lower() for word in ['medium', 'middle', 'half']):
            entities['intensity'] = 'medium'
        
        # Extract device names
        if 'lights' in text.lower() or 'light' in text.lower():
            entities['device'] = 'light'
        elif 'temperature' in text.lower() or 'thermostat' in text.lower():
            entities['device'] = 'thermostat'
        elif 'music' in text.lower() or 'audio' in text.lower():
            entities['device'] = 'audio'
        
        return entities
    
    async def get_command_history(self, limit: int = 10) -> list:
        """
        Get recent command history
        """
        return self.command_history[-limit:]
    
    async def add_listening_keyword(self, keyword: str):
        """
        Add a new keyword to listen for
        """
        if keyword not in self.listening_keywords:
            self.listening_keywords.append(keyword)
            logger.info(f"Added new listening keyword: {keyword}")
    
    async def remove_listening_keyword(self, keyword: str):
        """
        Remove a keyword from listening list
        """
        if keyword in self.listening_keywords:
            self.listening_keywords.remove(keyword)
            logger.info(f"Removed listening keyword: {keyword}")
    
    async def is_listening_for_keyword(self, text: str) -> bool:
        """
        Check if text contains any listening keywords
        """
        text_lower = text.lower()
        return any(keyword.lower() in text_lower for keyword in self.listening_keywords)
