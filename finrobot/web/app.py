import streamlit as st
import autogen
from finrobot.agents.workflow import SingleAssistantShadow
from finrobot.utils import register_keys_from_json
import os
import queue
import threading
from typing import Dict, Any, Optional
import logging
import sys
import io

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class StreamlitAssistant:
    def __init__(self, agent_config: str, llm_config: Dict[str, Any],
                 max_consecutive_auto_reply: Optional[int] = None):
        
        # Create message queue for real-time updates
        self.message_queue = queue.Queue()
        
        # Initialize the base assistant with modified message handlers
        self.assistant = SingleAssistantShadow(
            agent_config=agent_config,
            llm_config=llm_config,
            max_consecutive_auto_reply=max_consecutive_auto_reply,
            human_input_mode="ALWAYS"  # Changed to NEVER for Streamlit
        )
        
        # Override the message handlers
        self._setup_message_handlers()
        
    def _setup_message_handlers(self):
        # Store original receive method
        original_receive = self.assistant.assistant.receive
        original_user_receive = self.assistant.user_proxy.receive
        
        # Override assistant's receive method
        def assistant_receive_wrapper(message, sender, request_reply=True, silent=False):
            print(message)
            # Queue the message for UI
            # if message.get("content"):
            self.message_queue.put({
                "role": "assistant",
                "content": message,
                "metadata": message,
            })
            return original_receive(message, sender, request_reply, silent)
        
        # Override user proxy's receive method
        def user_receive_wrapper(message, sender, request_reply=True, silent=False):
            print(message)
            # Queue the message for UI
            # if message.get("content"):
            self.message_queue.put({
                "role": "user",
                "content": message,
                "metadata": message
            })
            return original_user_receive(message, sender, request_reply, silent)
        
        # Apply the overrides
        self.assistant.assistant.receive = assistant_receive_wrapper
        self.assistant.user_proxy.receive = user_receive_wrapper
            
    def chat(self, message: str, **kwargs):
        """Start a chat session in a separate thread"""
        def chat_thread():
            try:
                logger.info("Starting chat with message: %s", message)
                self.assistant.chat(message, **kwargs)
                logger.info("Chat completed")
            except Exception as e:
                logger.error("Error in chat: %s", str(e))
                raise
        
        thread = threading.Thread(target=chat_thread)
        thread.start()
        return thread

def initialize_session_state():
    """Initialize Streamlit session state"""
    if "messages" not in st.session_state:
        st.session_state.messages = []
        
    if "assistant" not in st.session_state:
        # Configure LLM
        llm_config = {
            "config_list": autogen.config_list_from_json(
                "OAI_CONFIG_LIST",
                filter_dict={
                    "model": ["gpt-4o-mini"],
                },
            ),
            "timeout": 120,
            "temperature": 0.5,
        }
        
        # Register API keys
        register_keys_from_json("config_api_keys")
        
        # Create report directory
        work_dir = "report"
        os.makedirs(work_dir, exist_ok=True)
        
        # Create assistant
        try:
            logger.info("Initializing StreamlitAssistant")
            st.session_state.assistant = StreamlitAssistant(
                agent_config="Expert_Investor",
                llm_config=llm_config,
                max_consecutive_auto_reply=None
            )
            logger.info("StreamlitAssistant initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize StreamlitAssistant: %s", str(e))
            raise

def display_message(message: Dict[str, Any]):
    print("display_message {message}")
    """Display a single message with metadata"""
    role = message["role"]
    content = message["content"]
    # metadata = message.get("metadata", {})
    
    # Display the message
    with st.chat_message(role):
        st.markdown(content)
        st.code(message, language="json")
    
        # Display tool calls if present
        # if metadata:
        #     with st.expander("Tool Calls"):
        #         st.code(metadata, language="json")

def main():
    st.set_page_config(
        page_title="FinRobot Chat",
        page_icon="💰",
        layout="wide"
    )
    
    st.title("FinRobot Chat")
    initialize_session_state()
    
    # Display existing messages
    for msg in st.session_state.messages:
        display_message(msg)
    
    # Chat input
    if prompt := st.chat_input("Message FinRobot..."):
        logger.info("Received user input: %s", prompt)
        
        # Add user message
        user_message = {"role": "user", "content": prompt}
        st.session_state.messages.append(user_message)
        
        # Display user message
        with st.chat_message("user"):
            st.markdown(prompt)
        
        try:
            # Start chat in background
            chat_thread = st.session_state.assistant.chat(prompt)
            
            # Process messages from queue
            with st.spinner("FinRobot is thinking..."):
                while chat_thread.is_alive() or not st.session_state.assistant.message_queue.empty():
                    try:
                        msg = st.session_state.assistant.message_queue.get_nowait()
                        logger.info("Received message: %s", msg)
                        st.session_state.messages.append(msg)
                        display_message(msg)
                    except queue.Empty:
                        continue
        except Exception as e:
            logger.error("Error processing chat: %s", str(e))
            st.error(f"An error occurred: {str(e)}")

if __name__ == "__main__":
    main()