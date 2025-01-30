from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
from queue import Queue, Empty
import threading
import time
import uuid
import logging
import asyncio
import os
import json

logger = logging.getLogger(__name__)

@dataclass
class Message:
    """Message format for API communication"""
    role: str  # 'assistant', 'user', 'system', 'tool' 
    content: str
    timestamp: float
    metadata: Optional[Dict] = None  # For tool calls, outputs, etc

class AgentSession:
    """Generic wrapper for any FinRobot agent workflow"""
    
    def __init__(self, agent_type: str, agent_config: Dict):
        """Initialize agent session"""
        self.session_id = str(uuid.uuid4())
        self.agent_type = agent_type
        self.agent_config = agent_config
        self.response_queue = asyncio.Queue()
        self.messages: List[Message] = []
        self.input_queue = Queue()
        self.output_queue = Queue()
        
        # Create report directory with absolute path
        self.report_dir = os.path.abspath("report")
        os.makedirs(self.report_dir, exist_ok=True)
        
        # Create the appropriate agent type
        logger.info(f"Creating {agent_type} session with config: {agent_config}")
        if agent_type == "SingleAssistantShadow":
            from finrobot.agents.workflow import SingleAssistantShadow
            # Add report_dir to config
            agent_config["report_dir"] = self.report_dir
            self.agent = SingleAssistantShadow(**agent_config)
            # Preserve original receive methods
            self._original_assistant_receive = self.agent.assistant.receive
            self._original_user_receive = self.agent.user_proxy.receive
            self._original_get_human_input = self.agent.user_proxy.get_human_input
        else:
            raise ValueError(f"Unknown agent type: {agent_type}")
        
        # Set up message handlers
        self._setup_handlers()
        self.agent_thread = None

    def _setup_handlers(self):
        """Set up message and input handlers for the agent"""
        if hasattr(self.agent, "assistant"):
            self.agent.assistant.receive = self._wrap_receive("assistant", self._original_assistant_receive)
        if hasattr(self.agent, "user_proxy"):
            self.agent.user_proxy.receive = self._wrap_receive("user", self._original_user_receive)
            self.agent.user_proxy.get_human_input = self._handle_input

    def _wrap_receive(self, role: str, original_receive):
        """Wrap the original receive method to capture messages"""
        def wrapped_receive(message: Any, sender: Any, request_reply: bool = False, silent: bool = False):
            try:
                # Determine if this is a tool call
                is_tool_call = isinstance(message, dict) and (
                    message.get("function_call") or 
                    message.get("tool_calls") or
                    message.get("suggested_tool_call")
                )
                
                # Handle message content properly
                content = None
                if isinstance(message, str):
                    content = message
                elif isinstance(message, dict):
                    content = message.get("content")
                    if not content and is_tool_call:
                        content = json.dumps(message, indent=2)
                
                # Create message with metadata
                msg = Message(
                    role=role,
                    content=content,
                    timestamp=time.time(),
                    metadata={
                        "tool_call": is_tool_call,
                        "request_reply": request_reply,
                        "raw_message": message  # Preserve original message structure
                    }
                )
                
                # Queue the message
                self.messages.append(msg)
                self.output_queue.put(msg)
                logger.info(f"Queued message from {role}: {content[:100]}...")
                
                # Call original receive method
                return original_receive(message, sender, request_reply, silent)
            except Exception as e:
                logger.exception(f"Error in {role} receive handler: {e}")
                raise
        return wrapped_receive

    def _handle_input(self, prompt: str) -> str:
        """Handle input requests from the agent"""
        logger.info(f"Handling input request: {prompt[:100]}...")
        
        # Queue system message requesting input with explicit request_reply flag
        msg = Message(
            role="system", 
            content=prompt,
            timestamp=time.time(),
            metadata={
                "request_reply": True,  # This is critical
                "prompt": True  # Add an extra flag to be sure
            }
        )
        self.messages.append(msg)
        self.output_queue.put(msg)
        logger.info("Waiting for user input...")
        
        # Wait for input from client
        response = self.input_queue.get()
        logger.info(f"Received user input: {response[:100] if response else 'None'}")
        return response if response else ""

    def send_message(self, content: str) -> Message:
        """Send a message to the agent"""
        logger.info(f"Sending message: {content[:100]}...")
        message = Message(
            role="user",
            content=content, 
            timestamp=time.time()
        )
        self.messages.append(message)
        
        # Start or continue chat
        if not self.agent_thread or not self.agent_thread.is_alive():
            self.agent_thread = threading.Thread(
                target=lambda: self.agent.chat(content, max_turns=50),
                daemon=True
            )
            self.agent_thread.start()
        else:
            self.input_queue.put(content)
            
        return message

    def get_response(self, timeout: float = None) -> Optional[Message]:
        """Get next response from the agent"""
        try:
            return self.output_queue.get(timeout=timeout)
        except Empty:
            return None

    def get_history(self) -> List[Message]:
        """Get chat history"""
        return self.messages 

    async def send_message_and_get_response(self, content: str, timeout: float = None) -> Optional[Message]:
        """Send a message and wait for the response in one step"""
        self.send_message(content)
        
        # Wait for response
        try:
            start_time = time.time()
            while True:
                if timeout and (time.time() - start_time) > timeout:
                    return None
                    
                try:
                    response = self.output_queue.get(timeout=1 if timeout is None else min(1, timeout/2))
                    
                    # Return immediately if it's a tool call
                    if response.metadata and response.metadata.get("tool_call"):
                        return response
                        
                    # For regular messages, ensure it's not an echo
                    if response.content != content:
                        return response
                        
                except Empty:
                    continue
                    
        except Exception as e:
            logger.error(f"Error getting response: {str(e)}")
            return None 

    async def get_next_response(self, timeout: float = None) -> Optional[Message]:
        """Get the next response from the output queue"""
        try:
            start_time = time.time()
            while True:
                if timeout and (time.time() - start_time) > timeout:
                    return None
                    
                try:
                    response = self.output_queue.get(timeout=1 if timeout is None else min(1, timeout/2))
                    logger.debug(f"Got response from queue: {response.role} - {response.content[:100]}...")
                    return response
                except Empty:
                    continue
                    
        except Exception as e:
            logger.error(f"Error getting response: {str(e)}")
            return None 