import asyncio
import websockets
import json
import sys
import time
from typing import Dict
import logging

logger = logging.getLogger(__name__)

async def wait_for_server(uri: str, max_attempts: int = 5, delay: int = 2) -> bool:
    """Wait for server to become available"""
    for attempt in range(max_attempts):
        try:
            async with websockets.connect(uri) as ws:
                return True
        except Exception as e:
            logger.warning(f"Server not ready (attempt {attempt + 1}/{max_attempts}): {e}")
            if attempt < max_attempts - 1:
                await asyncio.sleep(delay)
    return False

async def test_agent(agent_type: str, agent_config: Dict, initial_message: str):
    """Test an agent workflow"""
    uri = "ws://127.0.0.1:8000/ws/chat"
    
    # Wait for server
    logger.info("Checking server availability...")
    if not await wait_for_server(uri):
        logger.error("Server not available")
        return
    
    try:
        logger.info(f"Connecting to {uri}...")
        async with websockets.connect(uri) as websocket:
            logger.info(f"Testing {agent_type} agent...")
            
            # Send initial configuration
            config_msg = {
                "type": "config",
                "agent_type": agent_type,
                "agent_config": agent_config
            }
            logger.info(f"Sending config: {config_msg}")
            await websocket.send(json.dumps(config_msg))
            
            # Send initial message
            msg = {
                "type": "message",
                "content": initial_message
            }
            logger.info(f"Sending message: {msg}")
            await websocket.send(json.dumps(msg))
            
            # Handle responses
            while True:
                response = json.loads(await websocket.recv())
                logger.info(f"Received response: {response}")
                message = response['message']
                
                # Print message based on role
                print(f"\n{'='*50}")
                print(f"Role: {message['role']}")
                
                # Format content nicely
                if message['role'] == 'assistant':
                    print("\nAssistant:")
                    print(message['content'])
                elif message['role'] == 'system':
                    print("\nSystem:")
                    print(message['content'])
                    print("\nProviding input: proceed with analysis")
                    await websocket.send(json.dumps({
                        "type": "message",
                        "content": "proceed with analysis"
                    }))
                elif message['role'] == 'user':
                    print("\nUser:")
                    print(message['content'])
                
                # Show any metadata (like tool calls)
                if message.get('metadata'):
                    print("\nMetadata:")
                    for k, v in message['metadata'].items():
                        print(f"  {k}: {v}")
                
                sys.stdout.flush()
                
    except Exception as e:
        logger.exception(f"Test failed: {e}")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Test configuration for SingleAssistantShadow
    config = {
        "agent_config": "Expert_Investor",
        "llm_config": {}  # Will be set by server
    }
    
    message = "analyze microsoft for 2023"
    
    logger.info("Starting agent test...")
    asyncio.run(test_agent("SingleAssistantShadow", config, message)) 