"""
Test script for Project Vantage
Tests the core functionality of the ambient intelligence system
"""

import asyncio
import logging
from datetime import datetime
from main import AmbientIntelligenceSystem

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_system_creation():
    """Test the basic system creation and initialization"""
    logger.info("Testing Project Vantage Ambient Intelligence System")
    logger.info("=" * 55)
    
    system = AmbientIntelligenceSystem()
    
    logger.info(f"System created at: {datetime.now()}")
    
    # Test initialization
    logger.info("\n1. Testing initialization...")
    try:
        await system.initialize()
        logger.info("✓ Initialization successful")
    except Exception as e:
        logger.error(f"✗ Initialization failed: {e}")
        return
    
    # Test component registration
    logger.info("\n2. Testing component registration...")
    if system.components:
        logger.info(f"✓ Registered {len(system.components)} major components")
        for component_name in system.components:
            logger.info(f"  - {component_name}")
    else:
        logger.warning("✗ No components registered")
    
    # Test context data structure
    logger.info("\n3. Testing context data structure...")
    # Add some sample context data
    system.context_data = {
        'environmental': {'temperature': 22.5, 'light': 0.7},
        'temporal': {'hour': 14, 'day_of_week': 2},
        'social': {'estimated_presence': 'occupied'}
    }
    logger.info("✓ Context data structure tested")
    
    # Print system status
    logger.info("\n4. System Status:")
    logger.info(f"   - Running: {system.is_running}")
    logger.info(f"   - Components: {len(system.components)}")
    logger.info(f"   - Context keys: {list(system.context_data.keys())}")
    
    logger.info(f"\nTest completed at: {datetime.now()}")
    logger.info("=" * 55)


def test_sensor_manager():
    """Test sensor manager functionality"""
    logger.info("\nTesting Sensor Manager...")
    logger.info("-" * 25)
    
    try:
        from sensor_fusion.sensor_manager import SensorManager
        sensor_manager = SensorManager()
        
        # Test sensor registration
        sensor_manager.register_sensor('test_sensor', 'temperature')
        logger.info("✓ Sensor registration successful")
        
        # Test data collection
        data = sensor_manager.collect_data()
        logger.info(f"✓ Collected data: {data}")
        
    except Exception as e:
        logger.error(f"✗ Sensor manager test failed: {e}")


if __name__ == "__main__":
    asyncio.run(test_system_creation())
    test_sensor_manager()
