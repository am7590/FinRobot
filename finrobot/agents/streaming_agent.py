"""
Streaming agent for Streamlit integration with direct UI updates
"""
import os
import json
import logging
import queue
import threading
import time
from typing import Any, Dict, List, Optional, Callable

import autogen
from autogen import AssistantAgent, UserProxyAgent

from .workflow import SingleAssistantShadow
from ..utils import register_keys_from_json

logger = logging.getLogger(__name__)

class StreamingAgent:
    """A wrapper around SingleAssistantShadow with direct UI streaming capabilities"""
    
    def __init__(self, 
                 llm_config: Dict[str, Any],
                 message_callback: Callable[[Dict], None] = None):
        """
        Initialize the streaming agent
        
        Args:
            llm_config: Configuration for the language model
            message_callback: Callback function to receive messages
        """
        self.llm_config = llm_config
        self.message_callback = message_callback
        self.message_queue = queue.Queue()
        self.error_event = threading.Event()  # Add error event flag
        self._setup_agent()
        
    def _setup_agent(self):
        """Initialize the agent with message capture"""
        try:
            # Initialize the base assistant
            self.assistant = SingleAssistantShadow(
                agent_config=self.llm_config.get("agent_config", "Expert_Investor"),
                llm_config=self.llm_config,
                max_consecutive_auto_reply=None,
                human_input_mode="NEVER"  # Never ask for human input
            )
            
            # Send an initial startup message to confirm agent is working
            startup_msg = {
                "role": "assistant",
                "content": "Starting analysis, preparing tools and environment..."
            }
            self.message_queue.put(startup_msg)
            if self.message_callback:
                self.message_callback(startup_msg)
            
            # Capture both incoming and outgoing messages
            
            # Capture assistant messages 
            original_receive = self.assistant.assistant.receive
            
            def receive_with_capture(message, sender, request_reply=True, silent=False):
                """Capture all messages going to the assistant"""
                try:
                    # Process the message before it goes to the assistant
                    if isinstance(message, dict):
                        # If this is a tool response, capture it
                        if message.get("role") == "tool" or "tool_call_id" in message:
                            tool_message = {
                                "role": "assistant", 
                                "content": f"Tool result: {message.get('content', '')}"
                            }
                            self.message_queue.put(tool_message)
                            if self.message_callback:
                                self.message_callback(tool_message)
                except Exception as e:
                    logger.error(f"Error in message interceptor: {e}")
                    error_msg = {
                        "role": "assistant",
                        "content": f"Error: {str(e)}"
                    }
                    self.message_queue.put(error_msg)
                    if self.message_callback:
                        self.message_callback(error_msg)
                
                # Call original method
                return original_receive(message, sender, request_reply, silent)
            
            # Apply the override to capture incoming messages
            self.assistant.assistant.receive = receive_with_capture
            
            # Intercept outgoing messages
            original_send = self.assistant.user_proxy.send
            
            def send_with_capture(message, recipient, request_reply=None, silent=False):
                try:
                    # Process outgoing messages
                    if isinstance(message, dict) and message.get("content"):
                        content = message.get("content", "")
                        
                        # Create a copy of the message for the queue
                        msg_copy = message.copy()
                        
                        # If message has file references or formatting, preserve it
                        self.message_queue.put(msg_copy)
                        if self.message_callback:
                            self.message_callback(msg_copy)
                except Exception as e:
                    logger.error(f"Error in send interceptor: {e}")
                    error_msg = {
                        "role": "assistant",
                        "content": f"Error: {str(e)}"
                    }
                    self.message_queue.put(error_msg)
                    if self.message_callback:
                        self.message_callback(error_msg)
                
                # Call the original send method
                return original_send(message, recipient, request_reply, silent)
            
            # Apply the override
            self.assistant.user_proxy.send = send_with_capture
            
        except Exception as e:
            logger.error(f"Failed to set up streaming agent: {e}")
            # Add error to queue
            error_msg = {
                "role": "assistant",
                "content": f"Error setting up agent: {str(e)}"
            }
            self.message_queue.put(error_msg)
            if self.message_callback:
                self.message_callback(error_msg)
            raise
    
    def chat(self, message: str) -> threading.Thread:
        """
        Start a chat with the given message
        
        Args:
            message: The message to send to the agent
            
        Returns:
            The thread running the chat
        """
        # Define thread function
        def run_chat():
            try:
                # Create report directory
                os.makedirs("/app/report", exist_ok=True)
                # Change working directory
                os.chdir("/app/report")
                
                # Send initial progress message to UI
                init_msg = {
                    "role": "assistant",
                    "content": "Starting analysis, preparing tools and environment..."
                }
                self.message_queue.put(init_msg)
                if self.message_callback:
                    self.message_callback(init_msg)
                
                # Run the chat
                self.assistant.chat(message)
                
                # Send completion message
                complete_msg = {
                    "role": "assistant",
                    "content": "Analysis completed. Thank you for your patience."
                }
                self.message_queue.put(complete_msg)
                if self.message_callback:
                    self.message_callback(complete_msg)
                    
            except Exception as e:
                # Set error flag
                self.error_event.set()
                
                logger.error(f"Chat thread error: {e}", exc_info=True)
                error_msg = {
                    "role": "assistant",
                    "content": f"Error in report generation: {str(e)}"
                }
                self.message_queue.put(error_msg)
                if self.message_callback:
                    self.message_callback(error_msg)
        
        # Start thread
        chat_thread = threading.Thread(target=run_chat)
        chat_thread.daemon = True
        chat_thread.start()
        
        return chat_thread 