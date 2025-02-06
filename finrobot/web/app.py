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
import traceback
import json

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class StreamlitAssistant:
    def __init__(self, agent_config: str, llm_config: Dict[str, Any],
                 max_consecutive_auto_reply: Optional[int] = None):
        try:
            logger.debug("Initializing StreamlitAssistant with config: %s", agent_config)
            
            # Create message queue for real-time updates
            self.message_queue = queue.Queue()
            
            # Set up the report directory with absolute path
            current_dir = os.path.dirname(os.path.abspath(__file__))
            root_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
            self.work_dir = os.path.abspath(os.path.join(root_dir, "report"))
            
            # Create report directory and log its creation
            logger.debug("Creating report directory at: %s", self.work_dir)
            os.makedirs(self.work_dir, exist_ok=True)
            
            # Change working directory to report directory
            os.chdir(self.work_dir)
            logger.debug("Changed working directory to: %s", self.work_dir)
            
            # Initialize the base assistant with modified message handlers
            self.assistant = SingleAssistantShadow(
                agent_config=agent_config,
                llm_config=llm_config,
                max_consecutive_auto_reply=max_consecutive_auto_reply,
                human_input_mode="NEVER"
            )
            
            # Override the message handlers
            self._setup_message_handlers()
            
        except Exception as e:
            logger.error("Failed to initialize StreamlitAssistant: %s", str(e))
            logger.error("Traceback: %s", traceback.format_exc())
            raise
        
    def _setup_message_handlers(self):
        try:
            # Store original receive method
            original_receive = self.assistant.assistant.receive
            original_user_receive = self.assistant.user_proxy.receive
            
            # Override assistant's receive method
            def assistant_receive_wrapper(message, sender, request_reply=True, silent=False):
                try:
                    logger.debug("Assistant received message: %s", message)
                    
                    if isinstance(message, dict):
                        content = message.get("content", "")
                        tool_calls = message.get("tool_calls", [])
                        
                        # Debug tool calls
                        if tool_calls:
                            logger.debug("Processing tool calls: %s", json.dumps(tool_calls, indent=2))
                            for tool_call in tool_calls:
                                if 'arguments' in tool_call.get('function', {}):
                                    try:
                                        logger.debug("Raw function arguments: %s", tool_call['function']['arguments'])
                                        args = json.loads(tool_call['function']['arguments'])
                                        logger.debug("Parsed arguments: %s", args)
                                        
                                        if 'save_path' in args:
                                            if not args['save_path']:
                                                logger.error("Empty save_path detected!")
                                                continue
                                                
                                            # Create absolute path using work_dir
                                            abs_path = os.path.join(self.work_dir, args['save_path'])
                                            logger.debug("Work directory: %s", self.work_dir)
                                            logger.debug("Converting save_path to absolute path: %s", abs_path)
                                            
                                            # Create parent directory if it doesn't exist
                                            parent_dir = os.path.dirname(abs_path)
                                            logger.debug("Creating parent directory: %s", parent_dir)
                                            os.makedirs(parent_dir, exist_ok=True)
                                            
                                            # Update the arguments with absolute path
                                            args['save_path'] = abs_path
                                            tool_call['function']['arguments'] = json.dumps(args)
                                            logger.debug("Updated tool call arguments: %s", tool_call['function']['arguments'])
                                    except json.JSONDecodeError as e:
                                        logger.error("Failed to parse tool call arguments: %s", e)
                                        continue
                                    except Exception as e:
                                        logger.error("Error processing tool call: %s", str(e))
                                        logger.error("Traceback: %s", traceback.format_exc())
                                        continue
                        
                        self.message_queue.put({
                            "role": "assistant",
                            "content": content or str(tool_calls),
                            "metadata": {"tool_calls": tool_calls} if tool_calls else {}
                        })
                        
                        return original_receive(message, sender, request_reply, silent)
                    else:
                        content = message
                        self.message_queue.put({
                            "role": "assistant",
                            "content": content,
                            "metadata": {}
                        })
                        return original_receive(message, sender, request_reply, silent)
                except Exception as e:
                    logger.error("Error in assistant_receive_wrapper: %s", str(e))
                    logger.error("Traceback: %s", traceback.format_exc())
                    raise
            
            # Override user proxy's receive method
            def user_receive_wrapper(message, sender, request_reply=True, silent=False):
                try:
                    logger.debug("User proxy received message: %s", message)
                    self.message_queue.put({
                        "role": "user",
                        "content": message,
                        "metadata": message
                    })
                    return original_user_receive(message, sender, request_reply, silent)
                except Exception as e:
                    logger.error("Error in user_receive_wrapper: %s", str(e))
                    logger.error("Traceback: %s", traceback.format_exc())
                    raise
            
            # Apply the overrides
            self.assistant.assistant.receive = assistant_receive_wrapper
            self.assistant.user_proxy.receive = user_receive_wrapper
            
        except Exception as e:
            logger.error("Error in _setup_message_handlers: %s", str(e))
            logger.error("Traceback: %s", traceback.format_exc())
            raise
        
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
        current_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
        config_path = os.path.join(root_dir, "OAI_CONFIG_LIST")
        api_keys_path = os.path.join(root_dir, "config_api_keys")
        
        logger.debug("Using config paths: config_path=%s, api_keys_path=%s", config_path, api_keys_path)
        
        # Create report directory with absolute path
        report_dir = os.path.join(root_dir, "report")
        logger.debug("Creating report directory at: %s", report_dir)
        os.makedirs(report_dir, exist_ok=True)
        
        llm_config = {
            "config_list": autogen.config_list_from_json(
                config_path,
                filter_dict={
                    "model": ["gpt-4o-mini"],
                },
            ),
            "timeout": 120,
            "temperature": 0.5,
        }
        
        # Register API keys with absolute path
        register_keys_from_json(api_keys_path)
        
        # Set the working directory
        os.chdir(report_dir)
        
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
        page_title="FinRobot",
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