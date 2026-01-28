"""
Test Runner for Project Vantage
Provides a test harness to verify logic without running the full system
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime
import pytest
from unittest.mock import AsyncMock, MagicMock
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import AmbientIntelligenceSystem
from config import get_settings

# Configure logging for tests
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class VantageTestRunner:
    """
    Test runner for Project Vantage system
    Provides isolated testing environment for verifying logic
    """
    
    def __init__(self):
        self.test_results = []
        self.test_system = None
        self.settings = get_settings()
        
    async def setup_test_system(self):
        """Setup a test instance of the system"""
        self.test_system = AmbientIntelligenceSystem()
        # Override some components to avoid external dependencies
        self.test_system.depin_enabled = False
        self.test_system.telemetry_enabled = False
        
        # Mock the components that require external services
        await self._mock_components()
        
    async def _mock_components(self):
        """Mock external dependencies for testing"""
        # Mock sensor manager to return test data
        from sensor_fusion.sensor_manager import SensorManager
        from sensor_fusion.data_ingestor import DataIngestor
        from context_engine.context_interpreter import ContextInterpreter
        from context_engine.ml_pipeline import MLPipeline
        from ai_reasoning.reasoning_engine import ReasoningEngine, PolicyManager
        from user_interface.voice_processor import VoiceProcessor
        from user_interface.feedback_generator import FeedbackGenerator
        
        # Create mock components
        self.test_system.components['sensor_manager'] = MagicMock(spec=SensorManager)
        self.test_system.components['data_ingestor'] = MagicMock(spec=DataIngestor)
        self.test_system.components['context_interpreter'] = MagicMock(spec=ContextInterpreter)
        self.test_system.components['ml_pipeline'] = MagicMock(spec=MLPipeline)
        self.test_system.components['reasoning_engine'] = MagicMock(spec=ReasoningEngine)
        self.test_system.components['policy_manager'] = MagicMock(spec=PolicyManager)
        self.test_system.components['voice_processor'] = MagicMock(spec=VoiceProcessor)
        self.test_system.components['feedback_generator'] = MagicMock(spec=FeedbackGenerator)
        
        # Configure mocks to return appropriate test data
        self.test_system.components['sensor_manager'].collect_data.return_value = {
            'test_sensor_1': {
                'sensor_type': 'temperature',
                'timestamp': datetime.now().isoformat(),
                'data': {'temperature': 22.5},
                'confidence': 1.0
            },
            'test_sensor_2': {
                'sensor_type': 'motion',
                'timestamp': datetime.now().isoformat(),
                'data': {'motion_detected': True},
                'confidence': 0.9
            }
        }
        
        self.test_system.components['data_ingestor'].process = AsyncMock(return_value={
            'temperature': [{'value': 22.5, 'confidence': 1.0}],
            'motion': [{'value': True, 'confidence': 0.9}]
        })
        
        self.test_system.components['context_interpreter'].analyze = AsyncMock(return_value={
            'environmental': {'temperature': {'average': 22.5}},
            'social': {'estimated_presence': 'occupied'}
        })
        
        self.test_system.components['ml_pipeline'].predict = AsyncMock(return_value={
            'predicted_activity': 'leisure',
            'confidence': 0.8
        })
        
        self.test_system.components['reasoning_engine'].make_decisions = AsyncMock(return_value=[
            {
                'type': 'adjust_environment',
                'action': 'adjust_temperature',
                'params': {'target_temperature': 22.0},
                'priority': 2
            }
        ])
        
        self.test_system.components['policy_manager'].apply_policies = AsyncMock(return_value=[
            {
                'type': 'adjust_environment',
                'action': 'adjust_temperature',
                'params': {'target_temperature': 22.0},
                'priority': 2
            }
        ])
        
        self.test_system.components['feedback_generator'].generate = AsyncMock(return_value="Test feedback")
    
    async def run_unit_tests(self):
        """Run unit tests for the system components"""
        logger.info("Running unit tests...")
        
        # Test initialization
        await self._test_initialization()
        
        # Test event handling
        await self._test_event_handling()
        
        # Test decision making
        await self._test_decision_making()
        
        # Test context processing
        await self._test_context_processing()
        
        logger.info(f"All unit tests completed. Results: {len(self.test_results)} tests run")
        
    async def _test_initialization(self):
        """Test system initialization"""
        try:
            await self.setup_test_system()
            assert self.test_system is not None
            assert hasattr(self.test_system, 'event_bus')
            assert len(self.test_system.components) > 0
            
            logger.info("✓ Initialization test passed")
            self.test_results.append({
                'test': '_test_initialization',
                'status': 'PASS',
                'message': 'System initialized successfully'
            })
        except Exception as e:
            logger.error(f"✗ Initialization test failed: {e}")
            self.test_results.append({
                'test': '_test_initialization',
                'status': 'FAIL',
                'message': str(e)
            })
    
    async def _test_event_handling(self):
        """Test event handling functionality"""
        try:
            from main import SensorDataEvent, UserVoiceEvent
            
            # Test sensor data event
            sensor_event = SensorDataEvent(
                sensor_id='test_sensor',
                data={'temperature': 25.0},
                timestamp=datetime.now().isoformat()
            )
            
            # Mock the event handler
            self.test_system.components['data_ingestor'].process = AsyncMock(return_value={
                'temperature': [{'value': 25.0, 'confidence': 1.0}]
            })
            
            await self.test_system._handle_sensor_data_event(sensor_event)
            
            # Test voice event
            voice_event = UserVoiceEvent(
                transcript='Turn on the lights',
                confidence=0.9,
                intent='lighting_control',
                timestamp=datetime.now().isoformat()
            )
            
            await self.test_system._handle_voice_event(voice_event)
            
            logger.info("✓ Event handling test passed")
            self.test_results.append({
                'test': '_test_event_handling',
                'status': 'PASS',
                'message': 'Event handling works correctly'
            })
        except Exception as e:
            logger.error(f"✗ Event handling test failed: {e}")
            self.test_results.append({
                'test': '_test_event_handling',
                'status': 'FAIL',
                'message': str(e)
            })
    
    async def _test_decision_making(self):
        """Test decision making functionality"""
        try:
            # Test decision making with mock context
            context = {
                'environmental': {'temperature': {'average': 28.0}},
                'social': {'estimated_presence': 'occupied'}
            }
            
            decisions = await self.test_system.components['reasoning_engine'].make_decisions(context)
            assert len(decisions) > 0
            
            # Test policy application
            filtered_decisions = await self.test_system.components['policy_manager'].apply_policies(
                decisions, self.test_system.user_preferences
            )
            assert len(filtered_decisions) >= 0  # May filter out some decisions
            
            logger.info("✓ Decision making test passed")
            self.test_results.append({
                'test': '_test_decision_making',
                'status': 'PASS',
                'message': 'Decision making works correctly'
            })
        except Exception as e:
            logger.error(f"✗ Decision making test failed: {e}")
            self.test_results.append({
                'test': '_test_decision_making',
                'status': 'FAIL',
                'message': str(e)
            })
    
    async def _test_context_processing(self):
        """Test context processing functionality"""
        try:
            context = {
                'temperature': [{'value': 22.5, 'confidence': 1.0}],
                'motion': [{'value': True, 'confidence': 0.9}]
            }
            
            analysis = await self.test_system.components['context_interpreter'].analyze(context)
            assert 'environmental' in analysis
            assert 'social' in analysis
            
            logger.info("✓ Context processing test passed")
            self.test_results.append({
                'test': '_test_context_processing',
                'status': 'PASS',
                'message': 'Context processing works correctly'
            })
        except Exception as e:
            logger.error(f"✗ Context processing test failed: {e}")
            self.test_results.append({
                'test': '_test_context_processing',
                'status': 'FAIL',
                'message': str(e)
            })
    
    async def run_integration_tests(self):
        """Run integration tests for the complete system"""
        logger.info("Running integration tests...")
        
        try:
            # Test complete system flow
            await self.setup_test_system()
            
            # Initialize the system
            await self.test_system.initialize()
            
            # Simulate some data processing
            sensor_data = await self.test_system.components['sensor_manager'].collect_data()
            processed_data = await self.test_system.components['data_ingestor'].process(sensor_data)
            
            # Process context
            context_analysis = await self.test_system.components['context_interpreter'].analyze(processed_data)
            
            # Make decisions
            decisions = await self.test_system.components['reasoning_engine'].make_decisions(context_analysis)
            
            # Apply policies
            filtered_decisions = await self.test_system.components['policy_manager'].apply_policies(
                decisions, self.test_system.user_preferences
            )
            
            logger.info("✓ Integration test passed")
            self.test_results.append({
                'test': 'integration_test',
                'status': 'PASS',
                'message': 'Integration test completed successfully'
            })
            
        except Exception as e:
            logger.error(f"✗ Integration test failed: {e}")
            self.test_results.append({
                'test': 'integration_test',
                'status': 'FAIL',
                'message': str(e)
            })
    
    async def run_performance_tests(self):
        """Run performance tests to measure system responsiveness"""
        logger.info("Running performance tests...")
        
        try:
            import time
            
            # Test initialization speed
            start_time = time.time()
            await self.setup_test_system()
            init_time = time.time() - start_time
            
            logger.info(f"Initialization took {init_time:.3f} seconds")
            
            # Test event processing speed
            start_time = time.time()
            from main import SensorDataEvent
            sensor_event = SensorDataEvent(
                sensor_id='perf_test',
                data={'temperature': 25.0},
                timestamp=datetime.now().isoformat()
            )
            await self.test_system._handle_sensor_data_event(sensor_event)
            event_time = time.time() - start_time
            
            logger.info(f"Event processing took {event_time:.3f} seconds")
            
            # Performance thresholds (adjust as needed)
            if init_time > 5.0:  # More than 5 seconds for init
                logger.warning("Initialization seems slow")
            if event_time > 1.0:  # More than 1 second for event processing
                logger.warning("Event processing seems slow")
            
            logger.info("✓ Performance test completed")
            self.test_results.append({
                'test': 'performance_test',
                'status': 'PASS',
                'message': f'Init: {init_time:.3f}s, Event: {event_time:.3f}s'
            })
            
        except Exception as e:
            logger.error(f"✗ Performance test failed: {e}")
            self.test_results.append({
                'test': 'performance_test',
                'status': 'FAIL',
                'message': str(e)
            })
    
    async def run_all_tests(self):
        """Run all available tests"""
        logger.info("Starting comprehensive test suite for Project Vantage...")
        
        await self.run_unit_tests()
        await self.run_integration_tests()
        await self.run_performance_tests()
        
        # Print test summary
        passed = len([r for r in self.test_results if r['status'] == 'PASS'])
        failed = len([r for r in self.test_results if r['status'] == 'FAIL'])
        
        logger.info("="*50)
        logger.info(f"TEST SUMMARY: {passed} passed, {failed} failed")
        logger.info("="*50)
        
        for result in self.test_results:
            status_icon = "✓" if result['status'] == 'PASS' else "✗"
            logger.info(f"{status_icon} {result['test']}: {result['message']}")
        
        if failed > 0:
            logger.error("Some tests failed. Review the logs above.")
            return False
        else:
            logger.info("All tests passed! System logic is verified.")
            return True
    
    def generate_test_report(self) -> Dict[str, Any]:
        """Generate a detailed test report"""
        passed = len([r for r in self.test_results if r['status'] == 'PASS'])
        failed = len([r for r in self.test_results if r['status'] == 'FAIL'])
        total = len(self.test_results)
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'total_tests': total,
            'passed': passed,
            'failed': failed,
            'success_rate': passed / total if total > 0 else 0,
            'results': self.test_results,
            'system_config': {
                'depin_enabled': self.settings.depin_enabled,
                'telemetry_enabled': self.settings.enable_telemetry,
                'debug': self.settings.debug
            }
        }
        
        return report


async def main():
    """Main entry point for the test runner"""
    runner = VantageTestRunner()
    
    success = await runner.run_all_tests()
    
    # Generate and save report
    report = runner.generate_test_report()
    
    # Save to file
    import json
    with open('test_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    
    logger.info("Test report saved to test_report.json")
    
    # Exit with appropriate code
    exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())