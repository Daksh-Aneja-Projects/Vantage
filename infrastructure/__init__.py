"""
Infrastructure components for Project Vantage
Includes DePIN (Decentralized Physical Infrastructure Network) integration,
wallet connectivity, ledger integrations, network management, supervision,
state management, and performance optimization
"""

# Import existing DePIN components
from . import (
    TransactionType,
    Transaction,
    WalletConnector,
    LedgerIntegration,
    DePINManager,
    get_depin_instance
)

# Import new infrastructure components
from .network_manager import NetworkManager, DeviceRole, ConnectionStatus
from .supervisor import ComponentSupervisor, RestartStrategy, ComponentHealth
from .state_store import GlobalStateStore, StateScope
from .performance_optimizer import PerformanceOptimizer, BufferPool

__all__ = [
    # DePIN components
    'TransactionType',
    'Transaction',
    'WalletConnector',
    'LedgerIntegration',
    'DePINManager',
    'get_depin_instance',
    
    # Network management
    'NetworkManager',
    'DeviceRole',
    'ConnectionStatus',
    
    # Supervision
    'ComponentSupervisor',
    'RestartStrategy',
    'ComponentHealth',
    
    # State management
    'GlobalStateStore',
    'StateScope',
    
    # Performance optimization
    'PerformanceOptimizer',
    'BufferPool'
]

import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import hashlib
import json
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class TransactionType(Enum):
    """Types of transactions in the DePIN ledger"""
    COMPUTE_JOB = "compute_job"
    DATA_STORAGE = "data_storage"
    SENSOR_FEED = "sensor_feed"
    REWARD_PAYOUT = "reward_payout"
    STAKING = "staking"
    WITHDRAWAL = "withdrawal"


@dataclass
class Transaction:
    """Represents a transaction in the DePIN ledger"""
    tx_id: str
    tx_type: TransactionType
    sender: str
    receiver: str
    amount: float
    timestamp: str
    signature: str
    data: Dict[str, Any]  # Additional transaction data


class WalletConnector:
    """Connects to cryptocurrency wallets for DePIN operations"""
    
    def __init__(self, wallet_provider: str = "metamask"):
        self.wallet_provider = wallet_provider
        self.connected_wallet = None
        self.accounts = []
        self.chain_id = None
        
    async def connect_wallet(self, wallet_address: str) -> bool:
        """Connect to a wallet address"""
        try:
            # In a real implementation, this would connect to the actual wallet
            # For simulation, we'll just set the address
            self.connected_wallet = wallet_address
            self.accounts = [wallet_address]
            logger.info(f"Connected to wallet: {wallet_address}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect wallet: {e}")
            return False
    
    async def disconnect_wallet(self):
        """Disconnect from the wallet"""
        self.connected_wallet = None
        self.accounts = []
        logger.info("Wallet disconnected")
    
    async def get_balance(self, token: str = "AVAI") -> float:
        """Get the balance of a specific token"""
        if not self.connected_wallet:
            logger.error("No wallet connected")
            return 0.0
        
        # In a real implementation, this would query the blockchain
        # For simulation, return a fixed balance
        return 100.0  # AVAI tokens
    
    async def sign_transaction(self, transaction_data: Dict[str, Any]) -> str:
        """Sign a transaction with the connected wallet"""
        if not self.connected_wallet:
            raise Exception("No wallet connected")
        
        # Create a simple signature by hashing the transaction data with wallet address
        tx_str = json.dumps(transaction_data, sort_keys=True)
        signature_data = f"{tx_str}:{self.connected_wallet}"
        signature = hashlib.sha256(signature_data.encode()).hexdigest()
        
        return signature
    
    async def send_transaction(self, to_address: str, amount: float, data: Dict[str, Any] = None) -> str:
        """Send a transaction to another address"""
        if not self.connected_wallet:
            raise Exception("No wallet connected")
        
        # Create transaction object
        tx_id = hashlib.sha256(f"{self.connected_wallet}:{to_address}:{amount}:{datetime.now().isoformat()}".encode()).hexdigest()
        
        transaction = {
            "from": self.connected_wallet,
            "to": to_address,
            "amount": amount,
            "timestamp": datetime.now().isoformat(),
            "data": data or {}
        }
        
        # Sign the transaction
        signature = await self.sign_transaction(transaction)
        
        logger.info(f"Transaction created: {tx_id}")
        return tx_id


class LedgerIntegration:
    """Integration with blockchain ledger for DePIN operations"""
    
    def __init__(self, chain_endpoint: str = "https://polygon-rpc.com"):
        self.chain_endpoint = chain_endpoint
        self.transactions = []
        self.blocks = []
        self.is_connected = False
        
    async def connect(self) -> bool:
        """Connect to the blockchain ledger"""
        try:
            # In a real implementation, this would connect to the actual blockchain
            # For simulation, we'll just set the connection status
            self.is_connected = True
            logger.info(f"Connected to ledger at {self.chain_endpoint}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to ledger: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from the blockchain ledger"""
        self.is_connected = False
        logger.info("Disconnected from ledger")
    
    async def record_transaction(self, transaction: Transaction) -> bool:
        """Record a transaction in the ledger"""
        if not self.is_connected:
            logger.error("Ledger not connected")
            return False
        
        try:
            self.transactions.append(transaction)
            logger.info(f"Recorded transaction: {transaction.tx_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to record transaction: {e}")
            return False
    
    async def get_transaction_history(self, address: str, limit: int = 10) -> List[Transaction]:
        """Get transaction history for an address"""
        if not self.is_connected:
            logger.error("Ledger not connected")
            return []
        
        # Filter transactions for the specific address
        address_transactions = [
            tx for tx in self.transactions
            if tx.sender == address or tx.receiver == address
        ]
        
        # Return the most recent transactions
        return address_transactions[-limit:]
    
    async def get_ledger_stats(self) -> Dict[str, Any]:
        """Get statistics about the ledger"""
        if not self.is_connected:
            logger.error("Ledger not connected")
            return {}
        
        total_transactions = len(self.transactions)
        compute_jobs = len([tx for tx in self.transactions if tx.tx_type == TransactionType.COMPUTE_JOB])
        rewards_paid = len([tx for tx in self.transactions if tx.tx_type == TransactionType.REWARD_PAYOUT])
        
        return {
            "total_transactions": total_transactions,
            "compute_jobs_processed": compute_jobs,
            "rewards_paid": rewards_paid,
            "connected": self.is_connected
        }


class DePINManager:
    """Main manager for DePIN operations"""
    
    def __init__(self, wallet_address: str, chain_endpoint: str = "https://polygon-rpc.com"):
        self.wallet_connector = WalletConnector()
        self.ledger_integration = LedgerIntegration(chain_endpoint)
        self.wallet_address = wallet_address
        self.is_initialized = False
        self.jobs_queue = []
        self.completed_jobs = []
        self.rewards_balance = 0.0
        self.staked_amount = 0.0
        
    async def initialize(self) -> bool:
        """Initialize the DePIN manager"""
        try:
            # Connect wallet
            wallet_connected = await self.wallet_connector.connect_wallet(self.wallet_address)
            if not wallet_connected:
                logger.error("Failed to connect wallet")
                return False
            
            # Connect to ledger
            ledger_connected = await self.ledger_integration.connect()
            if not ledger_connected:
                logger.error("Failed to connect to ledger")
                return False
            
            # Load initial state
            await self._load_state()
            
            self.is_initialized = True
            logger.info("DePIN manager initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize DePIN manager: {e}")
            return False
    
    async def _load_state(self):
        """Load the current state from ledger"""
        try:
            # Get transaction history for this wallet
            transactions = await self.ledger_integration.get_transaction_history(
                self.wallet_address, limit=50
            )
            
            # Calculate rewards balance from reward payout transactions
            for tx in transactions:
                if tx.tx_type == TransactionType.REWARD_PAYOUT and tx.receiver == self.wallet_address:
                    self.rewards_balance += tx.amount
                elif tx.tx_type == TransactionType.STAKING and tx.sender == self.wallet_address:
                    self.staked_amount += tx.amount
            
            logger.info(f"Loaded state: rewards={self.rewards_balance}, staked={self.staked_amount}")
            
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
    
    async def submit_compute_job(self, job_data: Dict[str, Any], bid_price: float) -> str:
        """Submit a compute job to the DePIN network"""
        if not self.is_initialized:
            raise Exception("DePIN manager not initialized")
        
        try:
            # Create transaction for the compute job
            job_id = hashlib.sha256(
                f"{self.wallet_address}:{job_data}:{datetime.now().isoformat()}".encode()
            ).hexdigest()
            
            transaction = Transaction(
                tx_id=job_id,
                tx_type=TransactionType.COMPUTE_JOB,
                sender=self.wallet_address,
                receiver="network",  # Will be assigned to a provider
                amount=bid_price,
                timestamp=datetime.now().isoformat(),
                signature="",  # Will be filled in after signing
                data={
                    "job_id": job_id,
                    "job_type": job_data.get("type", "generic"),
                    "requirements": job_data.get("requirements", {}),
                    "deadline": job_data.get("deadline", ""),
                    "result_callback": job_data.get("callback", "")
                }
            )
            
            # Sign the transaction
            signature = await self.wallet_connector.sign_transaction({
                "tx_id": transaction.tx_id,
                "tx_type": transaction.tx_type.value,
                "sender": transaction.sender,
                "receiver": transaction.receiver,
                "amount": transaction.amount,
                "timestamp": transaction.timestamp,
                "data": transaction.data
            })
            
            transaction.signature = signature
            
            # Record in ledger
            success = await self.ledger_integration.record_transaction(transaction)
            if success:
                # Add to jobs queue
                self.jobs_queue.append({
                    "job_id": job_id,
                    "data": job_data,
                    "bid_price": bid_price,
                    "status": "submitted",
                    "submitted_at": datetime.now().isoformat()
                })
                
                logger.info(f"Submitted compute job: {job_id}")
                return job_id
            else:
                raise Exception("Failed to record transaction in ledger")
                
        except Exception as e:
            logger.error(f"Failed to submit compute job: {e}")
            raise
    
    async def process_compute_job(self, job_id: str, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process a compute job (simulated)"""
        try:
            # In a real implementation, this would execute the actual computation
            # For simulation, we'll return a mock result
            result = {
                "job_id": job_id,
                "result": "computation_result",
                "processed_at": datetime.now().isoformat(),
                "execution_time_ms": 1234
            }
            
            # Update job status
            for job in self.jobs_queue:
                if job["job_id"] == job_id:
                    job["status"] = "completed"
                    job["completed_at"] = datetime.now().isoformat()
                    break
            
            # Add to completed jobs
            self.completed_jobs.append({
                "job_id": job_id,
                "result": result,
                "completed_at": datetime.now().isoformat()
            })
            
            # Issue reward for processing the job
            await self._issue_reward(job_id, job_data)
            
            logger.info(f"Processed compute job: {job_id}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to process compute job {job_id}: {e}")
            raise
    
    async def _issue_reward(self, job_id: str, job_data: Dict[str, Any]):
        """Issue a reward for completing a job"""
        try:
            # Calculate reward amount
            base_reward = job_data.get("reward", 0.1)  # Default to 0.1 AVAI
            reward_amount = base_reward
            
            # Create reward transaction
            reward_tx = Transaction(
                tx_id=hashlib.sha256(f"reward:{job_id}:{self.wallet_address}:{reward_amount}".encode()).hexdigest(),
                tx_type=TransactionType.REWARD_PAYOUT,
                sender="network",  # Reward comes from network
                receiver=self.wallet_address,
                amount=reward_amount,
                timestamp=datetime.now().isoformat(),
                signature="",  # Will be filled in by network
                data={
                    "job_id": job_id,
                    "reward_type": "compute_job_completion"
                }
            )
            
            # In a real implementation, network would sign this
            # For simulation, we'll just record it
            success = await self.ledger_integration.record_transaction(reward_tx)
            if success:
                self.rewards_balance += reward_amount
                logger.info(f"Issued reward {reward_amount} AVAI for job {job_id}")
            
        except Exception as e:
            logger.error(f"Failed to issue reward for job {job_id}: {e}")
    
    async def stake_tokens(self, amount: float) -> bool:
        """Stake tokens to participate in the DePIN network"""
        if not self.is_initialized:
            raise Exception("DePIN manager not initialized")
        
        try:
            # Check balance
            balance = await self.wallet_connector.get_balance("AVAI")
            if balance < amount:
                raise Exception(f"Insufficient balance. Have {balance}, need {amount}")
            
            # Create staking transaction
            tx_id = hashlib.sha256(
                f"stake:{self.wallet_address}:{amount}:{datetime.now().isoformat()}".encode()
            ).hexdigest()
            
            transaction = Transaction(
                tx_id=tx_id,
                tx_type=TransactionType.STAKING,
                sender=self.wallet_address,
                receiver="network_staking_contract",
                amount=amount,
                timestamp=datetime.now().isoformat(),
                signature="",  # Will be filled in after signing
                data={"action": "stake"}
            )
            
            # Sign the transaction
            signature = await self.wallet_connector.sign_transaction({
                "tx_id": transaction.tx_id,
                "tx_type": transaction.tx_type.value,
                "sender": transaction.sender,
                "receiver": transaction.receiver,
                "amount": transaction.amount,
                "timestamp": transaction.timestamp,
                "data": transaction.data
            })
            
            transaction.signature = signature
            
            # Record in ledger
            success = await self.ledger_integration.record_transaction(transaction)
            if success:
                self.staked_amount += amount
                logger.info(f"Staked {amount} AVAI tokens")
                return True
            else:
                raise Exception("Failed to record staking transaction in ledger")
                
        except Exception as e:
            logger.error(f"Failed to stake tokens: {e}")
            return False
    
    async def withdraw_rewards(self, amount: float = None) -> bool:
        """Withdraw earned rewards"""
        if not self.is_initialized:
            raise Exception("DePIN manager not initialized")
        
        try:
            # Determine withdrawal amount
            if amount is None:
                amount = self.rewards_balance
            elif amount > self.rewards_balance:
                raise Exception(f"Insufficient rewards balance. Have {self.rewards_balance}, requested {amount}")
            
            # Create withdrawal transaction
            tx_id = hashlib.sha256(
                f"withdraw:{self.wallet_address}:{amount}:{datetime.now().isoformat()}".encode()
            ).hexdigest()
            
            transaction = Transaction(
                tx_id=tx_id,
                tx_type=TransactionType.WITHDRAWAL,
                sender="network_reward_contract",
                receiver=self.wallet_address,
                amount=amount,
                timestamp=datetime.now().isoformat(),
                signature="",  # Will be filled in by network
                data={"action": "withdraw_rewards"}
            )
            
            # In a real implementation, network would sign this
            # For simulation, we'll just record it and update balance
            success = await self.ledger_integration.record_transaction(transaction)
            if success:
                self.rewards_balance -= amount
                logger.info(f"Withdrew {amount} AVAI rewards")
                return True
            else:
                raise Exception("Failed to record withdrawal transaction in ledger")
                
        except Exception as e:
            logger.error(f"Failed to withdraw rewards: {e}")
            return False
    
    async def get_network_stats(self) -> Dict[str, Any]:
        """Get statistics about the DePIN network participation"""
        if not self.is_initialized:
            raise Exception("DePIN manager not initialized")
        
        ledger_stats = await self.ledger_integration.get_ledger_stats()
        
        return {
            "wallet_address": self.wallet_address,
            "rewards_balance": self.rewards_balance,
            "staked_amount": self.staked_amount,
            "jobs_submitted": len(self.jobs_queue),
            "jobs_completed": len(self.completed_jobs),
            "ledger_stats": ledger_stats,
            "initialized": self.is_initialized
        }
    
    async def cleanup(self):
        """Clean up resources"""
        await self.wallet_connector.disconnect_wallet()
        await self.ledger_integration.disconnect()
        self.is_initialized = False
        logger.info("DePIN manager cleaned up")


# Global instance for easy access
depin_instance = None


async def get_depin_instance(wallet_address: str, chain_endpoint: str = "https://polygon-rpc.com") -> DePINManager:
    """Get or create the DePIN instance"""
    global depin_instance
    if depin_instance is None:
        depin_instance = DePINManager(wallet_address, chain_endpoint)
        await depin_instance.initialize()
    return depin_instance