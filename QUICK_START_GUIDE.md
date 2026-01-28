# Vantage System - Quick Start Guide

## Prerequisites

```bash
# Install required dependencies
pip install -r requirements.txt

# Additional system packages (Ubuntu/Debian)
sudo apt-get install libatlas-base-dev libopenblas-dev
```

## Quick Installation

```bash
# Clone the repository
git clone <repository-url>
cd Vantage

# Install dependencies
pip install -r requirements.txt

# Set environment variables
cp .env.example .env
# Edit .env with your configuration
```

## Basic Usage

### 1. Starting the System

```python
import asyncio
from main import AmbientIntelligenceSystem

async def main():
    # Initialize system
    system = AmbientIntelligenceSystem()
    
    # Start all components
    await system.start()
    
    # System runs indefinitely
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await system.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

### 2. Adding Custom Sensors

```python
from sensor_fusion.real_data_ingestor import RealDataIngestor, SensorType

# Create ingestor
ingestor = RealDataIngestor()

# Register custom sensor
await ingestor.register_sensor(
    sensor_id="living_room_temp",
    sensor_type=SensorType.TEMPERATURE,
    host="192.168.1.100",
    port=8081
)
```

### 3. Defining Custom Rules

```python
from ai_reasoning.real_reasoning_engine import RealReasoningEngine, Rule, Action

engine = RealReasoningEngine()

# Create custom rule
custom_rule = Rule(
    rule_id="custom_comfort_rule",
    name="Custom Comfort Adjustment",
    conditions=[
        ContextCondition("environmental.temperature.average", "<", 18.0)
    ],
    actions=[
        Action("adjust_heating", {"target_temp": 22.0}, priority=RulePriority.HIGH)
    ],
    priority=RulePriority.HIGH,
    base_confidence=0.9
)

# Add rule to engine
engine.add_rule(custom_rule)
```

## Configuration

### Environment Variables (.env)

```bash
# Server Configuration
SERVER_HOST=0.0.0.0
SERVER_PORT=8000

# Security Settings
SECRET_KEY=your-secret-key-here
WALLET_ADDRESS=your-wallet-address

# Model Paths
MODEL_PATH=./models/
DEFAULT_MODEL_NAME=ambient_intelligence.onnx

# Feature Flags
ENABLE_TELEMETRY=true
ENABLE_DEPIN=true
ENABLE_ONNX=true
```

## API Endpoints

### WebSocket Interface

```javascript
// Connect to WebSocket endpoint
const ws = new WebSocket('ws://localhost:8000/ws');

ws.onmessage = function(event) {
    const data = JSON.parse(event.data);
    // Handle UI state updates
    updateUI(data);
};
```

### REST API

```bash
# Get system status
GET /api/status

# Submit sensor data
POST /api/sensor-data
{
    "sensor_id": "temp_001",
    "sensor_type": "temperature",
    "value": 22.5,
    "timestamp": "2024-01-01T12:00:00Z"
}

# Get current UI state
GET /api/ui-state

# Submit compute job (DePIN)
POST /api/compute-job
{
    "job_type": "ml_inference",
    "data": {...},
    "bid_price": 0.1
}
```

## Development Workflow

### 1. Component Development

```python
# Create new component
class MyComponent:
    def __init__(self):
        self.is_initialized = False
    
    async def initialize(self):
        # Component initialization
        self.is_initialized = True
    
    async def process(self, data):
        # Component processing logic
        return processed_data
    
    async def cleanup(self):
        # Cleanup resources
        pass

# Register with supervisor
from infrastructure.supervisor import global_supervisor
from infrastructure.supervisor import RestartStrategy

await global_supervisor.register_component(
    "my_component",
    MyComponent(),
    RestartStrategy(policy=RestartPolicy.EXPONENTIAL_BACKOFF)
)
```

### 2. State Management

```python
from infrastructure.state_store import global_state_store, StateScope

# Set state
await global_state_store.set(
    "user.preferences.theme", 
    "dark", 
    scope=StateScope.USER
)

# Get state with observer
current_theme = await global_state_store.get("user.preferences.theme")

# Register state observer
async def theme_change_handler(change_event):
    print(f"Theme changed from {change_event.old_value} to {change_event.new_value}")

await global_state_store.register_observer(
    "theme_watcher",
    theme_change_handler,
    interested_keys=["user.preferences.theme"]
)
```

### 3. Performance Monitoring

```python
from infrastructure.performance_optimizer import global_optimizer

# Start performance monitoring
await global_optimizer.start_optimization()

# Get performance report
report = await global_optimizer.get_optimization_report()
print(f"CPU Usage: {report['current_metrics']['cpu_percent']}%")
print(f"Memory Usage: {report['current_metrics']['memory_percent']}%")

# Use pooled buffers
with global_optimizer.pooled_buffer('sensor_small') as buffer:
    # Process sensor data using pre-allocated buffer
    process_sensor_data(buffer)
```

## Testing

### Unit Tests

```bash
# Run all tests
python -m pytest tests/

# Run specific test module
python -m pytest tests/test_sensor_fusion.py

# Run with coverage
python -m pytest --cov=vantage tests/
```

### Integration Tests

```python
import pytest
from main import AmbientIntelligenceSystem

@pytest.mark.asyncio
async def test_full_system_integration():
    system = AmbientIntelligenceSystem()
    await system.initialize()
    
    # Test sensor data flow
    test_data = {"temperature": {"average": 22.0}}
    result = await system.components['ml_pipeline'].predict(test_data)
    
    assert 'predictions' in result
    await system.stop()
```

## Deployment

### Docker Deployment

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 8000

CMD ["python", "main.py"]
```

```bash
# Build and run
docker build -t vantage-system .
docker run -p 8000:8000 vantage-system
```

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vantage-system
spec:
  replicas: 3
  selector:
    matchLabels:
      app: vantage
  template:
    metadata:
      labels:
        app: vantage
    spec:
      containers:
      - name: vantage
        image: vantage-system:latest
        ports:
        - containerPort: 8000
        envFrom:
        - configMapRef:
            name: vantage-config
```

## Troubleshooting

### Common Issues

1. **Module Import Errors**
   ```bash
   # Install missing dependencies
   pip install -r requirements.txt
   ```

2. **Permission Denied**
   ```bash
   # Fix file permissions
   chmod +x scripts/*.sh
   ```

3. **Memory Issues**
   ```python
   # Enable memory monitoring
   from infrastructure.performance_optimizer import global_optimizer
   await global_optimizer.start_optimization()
   ```

4. **Network Connectivity**
   ```python
   # Check network manager status
   from infrastructure.network_manager import NetworkManager
   nm = NetworkManager()
   status = await nm.get_network_status()
   print(status)
   ```

### Logging

```python
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Enable debug logging for specific modules
logging.getLogger('vantage.sensor_fusion').setLevel(logging.DEBUG)
logging.getLogger('vantage.ai_reasoning').setLevel(logging.DEBUG)
```

## Support

For issues and questions:
- GitHub Issues: [Repository Issues](https://github.com/your-repo/issues)
- Documentation: [Project Wiki](https://github.com/your-repo/wiki)
- Community: [Discord Channel](https://discord.gg/vantage)

## Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request