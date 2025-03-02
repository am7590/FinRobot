import os
import sys
import logging
import traceback
import json
import base64
import re
from typing import Dict, Any, Optional, List, Tuple
import queue
import threading
import io
from textwrap import dedent
import time

import streamlit as st
from streamlit.runtime.scriptrunner import add_script_run_ctx
import autogen
import fitz  # PyMuPDF for PDF text extraction
from PIL import Image
from autogen.agentchat.conversable_agent import ConversableAgent

from finrobot.agents.workflow import SingleAssistantShadow
from finrobot.utils import register_keys_from_json
from finrobot.agents.streaming_agent import StreamingAgent
from pdf2image import convert_from_path

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('streamlit_app.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def disable_human_input():
    """Disable human input by overriding the get_human_input method"""
    def _get_human_input(self, prompt: str = "", **kwargs):
        logger.debug("Human input disabled, returning TERMINATE")
        return "TERMINATE"
    
    ConversableAgent.get_human_input = _get_human_input

class StreamlitAssistant:
    def __init__(self, agent_config: str, llm_config: Dict[str, Any],
                 max_consecutive_auto_reply: Optional[int] = None):
        try:
            logger.debug("Initializing StreamlitAssistant with config: %s", agent_config)
            
            # Create message queue for real-time updates
            self.message_queue = queue.Queue()
            
            # Disable human input in Docker
            if os.getenv("DOCKER_CONTAINER"):
                logger.debug("Running in Docker container, disabling human input")
                disable_human_input()
            else:
                logger.debug("Not running in Docker container (DOCKER_CONTAINER not set)")
            
            # Get report directory from environment or use default
            self.work_dir = os.getenv("FINROBOT_REPORT_DIR", "/app/report")
            logger.debug("Using report directory: %s", self.work_dir)
            
            # Create report directory and log its creation
            os.makedirs(self.work_dir, exist_ok=True)
            
            # Change working directory to report directory
            os.chdir(self.work_dir)
            logger.debug("Changed working directory to: %s", self.work_dir)
            
            # Set custom parameters to ensure proper chat flow
            custom_llm_config = dict(llm_config)
            
            # Ensure we have a temperature setting for variety in responses
            if "temperature" not in custom_llm_config:
                custom_llm_config["temperature"] = 0.7
                
            # Initialize the base assistant with modified message handlers
            logger.debug("Creating SingleAssistantShadow instance")
            self.assistant = SingleAssistantShadow(
                agent_config=agent_config,
                llm_config=custom_llm_config,
                max_consecutive_auto_reply=max_consecutive_auto_reply,
                human_input_mode="NEVER"  # Never ask for human input
            )
            
            # Override the message handlers
            self._setup_message_handlers()
            logger.debug("StreamlitAssistant initialization complete")
            
        except Exception as e:
            logger.error("Failed to initialize StreamlitAssistant: %s", str(e))
            logger.error("Traceback: %s", traceback.format_exc())
            raise
        
    def _setup_message_handlers(self):
        """Set up message handlers for the assistant"""
        try:
            # Store original receive methods
            original_receive = self.assistant.assistant.receive
            original_user_receive = self.assistant.user_proxy.receive
            
            def assistant_receive_wrapper(message, sender, request_reply=True, silent=False):
                try:
                    logger.info(f"Assistant received message: {type(message)} from {sender.name}")
                    
                    if isinstance(message, dict):
                        content = message.get("content", "")
                        tool_calls = message.get("tool_calls", [])
                        tool_responses = message.get("tool_responses", [])
                        
                        logger.info(f"Message content (first 50 chars): {content[:50] if content else 'empty'}")
                        
                        # If message has no content but has tool calls, create a better summary
                        if not content and tool_calls:
                            content = f"I'm processing your request using tools: {', '.join([tc.get('function', {}).get('name', 'unknown') for tc in tool_calls])}"
                        
                        # Handle empty content or None values
                        if content is None:
                            content = ""
                            logger.warning("Received None content in message, converting to empty string")
                        
                        # Only queue messages with meaningful content
                        if content and content.strip():
                            # Add message to queue
                            msg = {
                                "role": "assistant",
                                "content": content,
                                "metadata": {
                                    "tool_calls": tool_calls if tool_calls else {},
                                    "tool_responses": tool_responses if tool_responses else {}
                                }
                            }
                            
                            # Generate a stable ID for the message
                            current_time = str(time.time())
                            unique_str = f"{current_time}_{content[:50]}"
                            msg_id = abs(hash(unique_str))
                            msg['id'] = msg_id
                            
                            logger.info(f"Queuing assistant message with ID {msg_id}: {content[:50]}")
                            self.message_queue.put(msg)
                        else:
                            logger.warning("Skipping empty assistant message")
                        
                        # Process tool calls if present
                        if tool_calls:
                            for tool_call in tool_calls:
                                if 'arguments' in tool_call.get('function', {}):
                                    try:
                                        args = json.loads(tool_call['function']['arguments'])
                                        # Process file paths
                                        for arg_name in ['save_path', 'pdf_path', 'image_path', 'share_performance_image_path', 
                                                   'pe_eps_performance_image_path', 'file_path', 'target_file']:
                                            if arg_name in args and args[arg_name]:
                                                abs_path = os.path.join(self.work_dir, args[arg_name])
                                                # Create parent directory if it doesn't exist
                                                parent_dir = os.path.dirname(abs_path)
                                                os.makedirs(parent_dir, exist_ok=True)
                                                args[arg_name] = abs_path
                                        tool_call['function']['arguments'] = json.dumps(args)
                                    except Exception as e:
                                        logger.error(f"Error processing tool call: {str(e)}")
                        
                        return original_receive(message, sender, request_reply, silent)
                    else:
                        # For string messages or other types
                        msg_content = str(message)
                        logger.info(f"Non-dict message: {msg_content[:50]}")
                        
                        # Only queue non-empty messages
                        if msg_content and msg_content.strip():
                            msg = {
                                "role": "assistant",
                                "content": msg_content,
                                "metadata": {}
                            }
                            self.message_queue.put(msg)
                        
                        return original_receive(message, sender, request_reply, silent)
                except Exception as e:
                    logger.error(f"Error in assistant_receive_wrapper: {str(e)}", exc_info=True)
                    raise

            # Apply the overrides
            self.assistant.assistant.receive = assistant_receive_wrapper
            self.assistant.user_proxy.receive = original_user_receive
            
        except Exception as e:
            logger.error(f"Error setting up message handlers: {str(e)}", exc_info=True)
            raise
        
    def chat(self, message: str, **kwargs):
        """Start a chat session in a separate thread with proper cleanup"""
        def chat_worker():
            try:
                # Clear message queue
                while not self.message_queue.empty():
                    self.message_queue.get_nowait()
                
                # Log that we're starting the chat
                logger.info(f"Starting chat with message: {message}")
                
                # Make sure assistant is not None
                if not hasattr(self, 'assistant') or self.assistant is None:
                    logger.error("Assistant is None in chat_worker")
                    self.message_queue.put({
                        "role": "assistant",
                        "content": "Error: Assistant not properly initialized",
                        "metadata": {"error": True},
                        "id": abs(hash(f"error_init_{time.time()}"))
                    })
                    return
                
                # Start chat
                logger.info("Calling assistant.chat method")
                
                try:
                    # Create and send initial message to the user proxy
                    self.assistant.user_proxy.initiate_chat(
                        self.assistant.assistant,
                        message=message,
                        **kwargs
                    )
                except Exception as e:
                    logger.error(f"Error in initiate_chat: {str(e)}", exc_info=True)
                    error_msg = f"I'm sorry, but I encountered an issue processing your request: {str(e)}"
                    self.message_queue.put({
                        "role": "assistant",
                        "content": error_msg,
                        "metadata": {"error": True},
                        "id": abs(hash(f"error_chat_{time.time()}"))
                    })
                
                logger.info("Chat session completed")
                
            except Exception as e:
                logger.error(f"Error in chat worker: {str(e)}", exc_info=True)
                self.message_queue.put({
                    "role": "assistant",
                    "content": f"Error: {str(e)}",
                    "metadata": {"error": True},
                    "id": abs(hash(f"error_chat_{time.time()}"))
                })
        
        # Create thread with Streamlit context
        thread = threading.Thread(target=chat_worker)
        add_script_run_ctx(thread)
        thread.daemon = True
        thread.start()
        return thread

def initialize_session_state():
    """Initialize session state variables"""
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    if "assistant" not in st.session_state:
        try:
            # Define configuration paths
            api_keys_path = os.getenv("CONFIG_API_KEYS", "/config/config_api_keys")
            oai_config_path = os.getenv("OAI_CONFIG_LIST", "/config/OAI_CONFIG_LIST")
            
            # Check if configuration files exist
            config_missing = []
            if not os.path.exists(api_keys_path):
                logger.error(f"API keys file not found at: {api_keys_path}")
                config_missing.append(f"API keys file: {api_keys_path}")
            
            if not os.path.exists(oai_config_path):
                logger.error(f"OpenAI config file not found at: {oai_config_path}")
                config_missing.append(f"OpenAI config file: {oai_config_path}")
            
            # If any config files are missing, show error and return
            if config_missing:
                error_msg = "⚠️ Configuration files missing:\n" + "\n".join(config_missing)
                st.error(error_msg)
                logger.error("Missing configuration files, assistant not initialized")
                st.session_state.assistant = None
                return
                
            # Load API keys
            logger.debug("Loading API keys from %s", api_keys_path)
            register_keys_from_json(api_keys_path)
            
            # Load OpenAI config
            logger.debug("Loading OpenAI config from %s", oai_config_path)
            with open(oai_config_path, 'r') as f:
                oai_config = json.load(f)
            
            # Set up LLM config for regular chat
            llm_config = {
                "config_list": oai_config,
                "temperature": 0.7,
            }
            
            # Initialize the assistant for regular chat
            st.session_state.assistant = StreamlitAssistant(
                agent_config="Expert_Investor",
                llm_config=llm_config,
                max_consecutive_auto_reply=5
            )
            logger.info("Assistant initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize assistant: {str(e)}")
            st.error(f"Failed to initialize assistant: {str(e)}")
            st.session_state.assistant = None
        
    # Add these new state variables
    if "report_in_progress" not in st.session_state:
        st.session_state.report_in_progress = False
    
    if "last_update_time" not in st.session_state:
        st.session_state.last_update_time = time.time()
        
    # Initialize form input variables
    if "ticker_input" not in st.session_state:
        st.session_state.ticker_input = ""
    if "year_input" not in st.session_state:
        st.session_state.year_input = ""

def extract_file_paths(content: str) -> List[Tuple[str, str]]:
    """Extract file paths and their context from message content."""
    file_paths = []
    lines = content.split('\n')
    
    # Common phrases that might precede a file path
    path_indicators = [
        'saved to',
        'file:',
        'path:',
        'located at',
        'stored in',
        'generated at',
        'created at',
        'output:',
        'see:',
        'view:'
    ]
    
    # File extensions to look for
    extensions = ['.txt', '.pdf', '.png', '.jpg', '.jpeg', '.md', '.csv', '.xlsx', '.docx']
    
    for i, line in enumerate(lines):
        line_lower = line.lower()
        
        # Look for file paths after indicators
        for indicator in path_indicators:
            if indicator in line_lower:
                parts = line.split(indicator, 1)
                if len(parts) > 1:
                    potential_path = parts[1].strip()
                    if any(potential_path.lower().endswith(ext) for ext in extensions):
                        context = parts[0].strip()
                        file_paths.append((potential_path, context))
                        break
        
        # Also look for file paths that are just mentioned in the text
        words = line.split()
        for word in words:
            if any(word.lower().endswith(ext) for ext in extensions):
                if os.path.exists(word):
                    context = line.replace(word, '').strip()
                    file_paths.append((word, context))
    
    return file_paths

def interpret_document(file_path: str) -> str:
    """Extract and interpret the content of a document."""
    try:
        if file_path.lower().endswith('.pdf'):
            # Extract text from PDF
            doc = fitz.open(file_path)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            
            # Generate a summary
            summary = f"""
            Document Summary:
            - Type: PDF
            - Pages: {doc.page_count}
            - Content Overview: {text[:500]}...
            
            Key Points:
            - Contains tables: {"Table" in text}
            - Contains figures: {"Figure" in text}
            - Contains references: {"Reference" in text}
            """
            return summary
            
        elif file_path.lower().endswith('.txt'):
            with open(file_path, 'r') as f:
                text = f.read()
            return f"Text Document Summary:\n{text[:500]}..."
            
        elif file_path.lower().endswith(('.png', '.jpg', '.jpeg')):
            img = Image.open(file_path)
            return f"""
            Image Summary:
            - Format: {img.format}
            - Size: {img.size}
            - Mode: {img.mode}
            """
            
        return "Document type not supported for interpretation"
        
    except Exception as e:
        return f"Error interpreting document: {str(e)}"

def display_message(msg):
    """Display a message in the chat UI with a stable unique ID"""
    # Generate a unique ID that includes both content and timestamp components
    if 'content' in msg and msg['content']:
        # If the message already has a unique ID, use it
        if 'id' in msg:
            msg_id = msg['id']
        else:
            # Create a unique ID combining timestamp and content hash
            current_time = str(time.time())
            content_str = msg['content'][:50] if msg['content'] else ''
            unique_str = f"{current_time}_{content_str}"
            msg_id = abs(hash(unique_str))
            # Store the ID in the message for future reference
            msg['id'] = msg_id
    else:
        # For messages without content, use timestamp only
        msg_id = abs(hash(str(time.time())))
        msg['id'] = msg_id
    
    # Use the unique ID to create a stable container for this message
    with st.container(key=f"msg_{msg_id}"):
        if msg["role"] == "user":
            st.markdown(f"**You:** {msg['content']}")
        elif msg["role"] == "assistant":
            st.markdown(f"**FinRobot:** {msg['content']}")
        elif msg["role"] == "tool":
            # For tool responses, show in a different format
            st.markdown("**Tool Output:**")
            st.code(msg['content'], language="")
        
        # Handle image displays if present in the message
        if 'content' in msg and msg['content'] and '<img' in msg['content']:
            # Extract image path using regex
            match = re.search(r'<img\s+([^>]+)>', msg['content'])
            if match:
                img_path = match.group(1).strip()
                try:
                    # Display image directly in Streamlit
                    st.image(img_path, use_column_width=True)
                except Exception as e:
                    st.error(f"Error displaying image: {e}")

        # Display file viewers for found paths
        if 'content' in msg and isinstance(msg['content'], str):
            file_paths = extract_file_paths(msg['content'])
            for file_path, context in file_paths:
                try:
                    # Create a unique key for the expander based on message ID and file path
                    expander_key = f"exp_{msg_id}_{hash(file_path)}"
                    
                    with st.expander(f"📄 {os.path.basename(file_path)} - {context}", key=expander_key):
                        col1, col2 = st.columns([2, 1])
                        
                        with col1:
                            if file_path.lower().endswith('.txt'):
                                with open(file_path, 'r') as f:
                                    txt_content = f.read()
                                st.text(txt_content)
                                
                            elif file_path.lower().endswith('.pdf'):
                                # Display PDF using PDF display component
                                with open(file_path, "rb") as f:
                                    base64_pdf = base64.b64encode(f.read()).decode('utf-8')
                                pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="700" height="1000" type="application/pdf"></iframe>'
                                st.markdown(pdf_display, unsafe_allow_html=True)
                                
                            elif file_path.lower().endswith(('.png', '.jpg', '.jpeg')):
                                st.image(file_path)
                        
                        with col2:
                            st.markdown("### Document Analysis")
                            interpretation = interpret_document(file_path)
                            st.markdown(interpretation)
                            
                            # Add download button
                            with open(file_path, "rb") as f:
                                st.download_button(
                                    label="Download File",
                                    data=f.read(),
                                    file_name=os.path.basename(file_path),
                                    mime="application/octet-stream",
                                    key=f"download_{msg_id}_{hash(file_path)}"
                                )
                except Exception as e:
                    st.error(f"Error displaying file {file_path}: {str(e)}")

def display_pdf(pdf_path):
    """Display a PDF file in Streamlit"""
    try:
        # Generate a unique key based on the PDF path and timestamp
        pdf_key = abs(hash(f"{pdf_path}_{time.time()}"))
        
        # Check if file exists
        if not os.path.exists(pdf_path):
            logger.error(f"PDF file not found: {pdf_path}")
            st.error(f"PDF file not found: {pdf_path}")
            return
            
        # Create a download button for the PDF
        with open(pdf_path, "rb") as f:
            pdf_data = f.read()
            
        st.download_button(
            label="Download PDF Report",
            data=pdf_data,
            file_name=os.path.basename(pdf_path),
            mime="application/pdf",
            key=f"pdf_download_{pdf_key}"
        )
        
        # Also attempt to show PDF preview
        try:
            # Display PDF using PDF display component
            with open(pdf_path, "rb") as f:
                base64_pdf = base64.b64encode(f.read()).decode('utf-8')
            pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="700" height="1000" type="application/pdf"></iframe>'
            st.markdown(pdf_display, unsafe_allow_html=True, key=f"pdf_iframe_{pdf_key}")
            
            # Also try to convert first page to image for preview (as fallback)
            try:
                images = convert_from_path(pdf_path, first_page=1, last_page=1)
                if images:
                    st.image(images[0], caption="PDF Preview (first page)", use_column_width=True, key=f"pdf_img_{pdf_key}")
            except Exception as e:
                logger.debug(f"Could not convert PDF to image: {e}")
        except Exception as e:
            st.info(f"PDF generated successfully but preview not available. Please download to view.", key=f"pdf_info_{pdf_key}")
            logger.error(f"Error displaying PDF preview: {e}")
            
    except Exception as e:
        st.error(f"Error with PDF: {e}", key=f"pdf_error_{pdf_key}")
        logger.error(f"Error with PDF: {e}", exc_info=True)

def generate_annual_report():
    """Generate an annual report using the AI agent approach."""
    try:
        # Get inputs from session state
        ticker = st.session_state.ticker_input
        year = st.session_state.year_input
        
        # Display user message for context
        user_prompt = f"""
        With the tools you've been provided, write an annual report based on {ticker}'s {year} 10-k report, format it into a pdf.
        Pay attention to the followings:
        - Explicitly explain your working plan before you kick off.
        - Use tools one by one for clarity, especially when asking for instructions. 
        - All your file operations should be done in "/app/report". 
        - Display any image in the chat once generated.
        - All the paragraphs should combine between 400 and 450 words, don't generate the pdf until this is explicitly fulfilled.
        """
        
        # Add user message to chat history
        user_message = {"role": "user", "content": user_prompt}
        st.session_state.messages.append(user_message)
        display_message(user_message)
        
        # Define configuration paths
        api_keys_path = os.getenv("CONFIG_API_KEYS", "/config/config_api_keys")
        oai_config_path = os.getenv("OAI_CONFIG_LIST", "/config/OAI_CONFIG_LIST")
        
        # Set processing flag
        st.session_state.report_in_progress = True
        st.session_state.last_update_time = time.time()
        
        # Create progress indicators
        st.session_state.progress_bar = st.progress(0)
        st.session_state.status_placeholder = st.empty()
        st.session_state.status_placeholder.info("Starting report generation...")
        
        # Always create a fresh assistant for report generation
        logger.debug("Loading API keys from %s", api_keys_path)
        register_keys_from_json(api_keys_path)
        
        logger.debug("Loading OpenAI config from %s", oai_config_path)
        with open(oai_config_path, 'r') as f:
            oai_config = json.load(f)
        
        # Set up LLM config
        llm_config = {
            "config_list": oai_config,
            "cache": None,
            "temperature": 0.1,
        }
        
        # Create streaming agent - always create a fresh instance
        try:
            st.session_state.assistant = StreamingAgent(
                llm_config=llm_config,
                message_callback=None  # We'll use the queue instead
            )
            
            # Start the chat in a separate thread
            st.session_state.chat_thread = st.session_state.assistant.chat(user_prompt)
            
            # Trigger rerun to start message processing
            st.rerun()
        except Exception as e:
            logger.error(f"Error initializing streaming agent: {e}", exc_info=True)
            st.error(f"Error initializing streaming agent: {e}")
            st.session_state.report_in_progress = False
            
    except Exception as e:
        logger.error(f"Error in generate_annual_report: {e}", exc_info=True)
        st.error(f"Error generating report: {e}")
        if hasattr(st.session_state, "report_in_progress"):
            st.session_state.report_in_progress = False

def main():
    st.set_page_config(
        page_title="FinRobot",
        page_icon="🤖",
        layout="wide"
    )
    
    st.title("FinRobot Chat")
    initialize_session_state()
    
    # Add report generation section
    with st.expander("Generate Annual Report"):
        # Store form inputs in session state
        st.session_state.ticker_input = st.text_input("Enter ticker symbol (e.g., TSLA):")
        st.session_state.year_input = st.text_input("Enter year (e.g., 2023):")
        
        if st.button("Generate Report"):
            if st.session_state.ticker_input and st.session_state.year_input:
                generate_annual_report()
            else:
                st.warning("Please enter both ticker symbol and year")
    
    # Process messages from agent if report is in progress
    if hasattr(st.session_state, "report_in_progress") and st.session_state.report_in_progress:
        if hasattr(st.session_state, "assistant") and hasattr(st.session_state.assistant, "message_queue"):
            # Process any available messages
            queue_changed = False
            try:
                while not st.session_state.assistant.message_queue.empty():
                    msg = st.session_state.assistant.message_queue.get_nowait()
                    st.session_state.messages.append(msg)
                    display_message(msg)
                    queue_changed = True
                    
                # Update progress based on elapsed time (simple approach)
                if hasattr(st.session_state, "progress_bar"):
                    elapsed = min(time.time() - st.session_state.last_update_time, 900)
                    progress_value = min(elapsed / 900, 1.0)  # Max 15 minutes (900s)
                    st.session_state.progress_bar.progress(progress_value)
                
                # Check if thread is still alive
                thread_alive = hasattr(st.session_state, "chat_thread") and st.session_state.chat_thread.is_alive()
                
                # If thread is done and queue is empty, mark as complete
                if not thread_alive and not queue_changed and st.session_state.assistant.message_queue.empty():
                    st.session_state.report_in_progress = False
                    if hasattr(st.session_state, "status_placeholder"):
                        st.session_state.status_placeholder.success("Report generation complete!")
                    if hasattr(st.session_state, "progress_bar"):
                        st.session_state.progress_bar.progress(1.0)
                else:
                    # Still processing - update timestamp and force rerun after delay
                    if hasattr(st.session_state, "status_placeholder"):
                        st.session_state.status_placeholder.info(f"Generating report... Last update: {time.strftime('%H:%M:%S')}")
                    # Force rerun every 1-2 seconds for updates
                    time.sleep(1)
                    st.rerun()
                    
            except Exception as e:
                logger.error(f"Error processing message queue: {e}", exc_info=True)
                if hasattr(st.session_state, "status_placeholder"):
                    st.session_state.status_placeholder.error(f"Error: {str(e)}")
    
    # Display existing messages
    for msg in st.session_state.messages:
        display_message(msg)
        
        # Check for PDF references in message
        if 'content' in msg and msg['content'] and '.pdf' in msg['content']:
            # Look for PDF paths in Docker format or local format
            pdf_patterns = [
                r'(/app/report/[^)\s\'"]+\.pdf)',  # Docker path
                r'(report/[^)\s\'"]+\.pdf)',       # Relative path
                r'([^)\s\'"]+\.pdf)'               # Any PDF filename
            ]
            
            # Generate a unique identifier for this message's PDFs
            if 'id' in msg:
                pdf_msg_id = msg['id']
            else:
                pdf_msg_id = abs(hash(f"{msg.get('content', '')}_{time.time()}"))
                msg['id'] = pdf_msg_id
                
            # Track which PDFs we've already displayed for this message
            displayed_pdfs = set()
            
            for pattern in pdf_patterns:
                pdf_matches = re.findall(pattern, msg['content'])
                for pdf_path in pdf_matches:
                    # Skip if we've already displayed this PDF
                    if pdf_path in displayed_pdfs:
                        continue
                        
                    # For relative paths, make them absolute
                    if pdf_path.startswith('report/') and not pdf_path.startswith('/app/'):
                        pdf_path = os.path.join('/app', pdf_path)
                    
                    # Check if file exists
                    if os.path.exists(pdf_path):
                        logger.info(f"Found PDF file: {pdf_path}")
                        display_pdf(pdf_path)
                        displayed_pdfs.add(pdf_path)
                        break  # Only display the file once if multiple patterns match
    
    # Chat input
    if prompt := st.chat_input("Message FinRobot..."):
        logger.info("Received user input: %s", prompt)
        
        # Add user message to session state
        user_message = {"role": "user", "content": prompt}
        st.session_state.messages.append(user_message)
        display_message(user_message)
        
        try:
            # Check if assistant is initialized
            if not st.session_state.assistant:
                st.error("FinRobot assistant is not properly initialized. Please check the logs and configuration files.")
                logger.error("Assistant is None when attempting to chat - ensuring configuration files exist at /config")
                
                # Check config files explicitly
                api_keys_path = os.getenv("CONFIG_API_KEYS", "/config/config_api_keys")
                oai_config_path = os.getenv("OAI_CONFIG_LIST", "/config/OAI_CONFIG_LIST")
                
                if not os.path.exists(api_keys_path):
                    st.error(f"API keys file not found at: {api_keys_path}")
                if not os.path.exists(oai_config_path):
                    st.error(f"OpenAI config file not found at: {oai_config_path}")
                    
                return
                
            logger.info("Starting assistant chat with prompt: %s", prompt)
            
            # Start chat in background with progress indicator
            with st.spinner("Processing your request..."):
                chat_thread = st.session_state.assistant.chat(prompt)
                logger.info("Chat thread started, now waiting for responses")
                
                # Process messages with timeout
                start_time = time.time()
                timeout = 60  # 1 minute timeout
                message_received = False
                
                while (time.time() - start_time < timeout and 
                       (chat_thread.is_alive() or not st.session_state.assistant.message_queue.empty())):
                    try:
                        # Try to get message with short timeout
                        msg = st.session_state.assistant.message_queue.get(timeout=0.1)
                        logger.info(f"Received message from queue: {type(msg)} - {msg.get('content', '')[:50]}")
                        
                        # Check for error message
                        if isinstance(msg, dict) and msg.get("metadata", {}).get("error"):
                            st.error(msg["content"])
                            break
                        
                        # Make sure we're not echoing the user message
                        if msg.get("role") == "assistant" and msg.get("content") == prompt:
                            logger.warning("Detected echo of user message, skipping")
                            continue
                        
                        # Check if message contains error related to SEC filing date
                        if isinstance(msg, dict) and "content" in msg and msg["content"] and "unconverted data remains: 00:00:00" in msg["content"]:
                            logger.warning("Detected SEC filing date parsing error, cleaning up message")
                            # Clean up the error message
                            content = msg["content"].replace("Error analyzing business highlights: unconverted data remains: 00:00:00", 
                                                           "Note: There might be issues with the filing date format.")
                            msg["content"] = content
                        
                        # Handle Pydantic validation errors
                        if isinstance(msg, dict) and "content" in msg and msg["content"] and "validation error for ResponseModel" in msg["content"]:
                            logger.warning("Detected Pydantic validation error, cleaning up message")
                            # Extract the core message without the validation error
                            content_lines = msg["content"].split('\n')
                            clean_lines = []
                            skip_error = False
                            for line in content_lines:
                                if "validation error for ResponseModel" in line or "Input should be a valid dictionary" in line:
                                    skip_error = True
                                    continue
                                if skip_error and ("For further information" in line or line.startswith("Error:")):
                                    skip_error = False
                                    continue
                                clean_lines.append(line)
                            
                            msg["content"] = '\n'.join(clean_lines)
                            if not msg["content"].strip():
                                msg["content"] = "I'm working on your request. Let me analyze the data."
                        
                        # Handle NoneType error
                        if isinstance(msg, dict) and "content" in msg and msg["content"] and "NoneType" in msg["content"] and "subscriptable" in msg["content"]:
                            logger.warning("Detected NoneType error, cleaning up message")
                            # Clean up the error message
                            content_lines = msg["content"].split('\n')
                            clean_lines = []
                            for line in content_lines:
                                if "NoneType" not in line and "subscriptable" not in line and "Error:" not in line:
                                    clean_lines.append(line)
                            
                            msg["content"] = '\n'.join(clean_lines)
                            if not msg["content"].strip():
                                msg["content"] = "I'm working on processing your request. Let me get more information for you."
                        
                        # Additional check to ensure we have meaningful content
                        if msg.get("role") == "assistant" and msg.get("content") and len(msg.get("content").strip()) > 0:
                            # Add and display message
                            st.session_state.messages.append(msg)
                            display_message(msg)
                            message_received = True
                            # Reset timeout clock when we get a real message
                            start_time = time.time()
                        else:
                            logger.warning(f"Skipping message without meaningful content: {msg}")
                            
                    except queue.Empty:
                        # Wait a short time before checking again
                        time.sleep(0.2)
                        continue
                    except Exception as e:
                        logger.error("Error processing message: %s", str(e), exc_info=True)
                        st.error(f"Error processing message: {str(e)}")
                        break
                
                # If no message was received, show an error
                if not message_received:
                    logger.error("No response received from assistant")
                    error_msg = {
                        "role": "assistant", 
                        "content": "I apologize, but I was unable to generate a response. Please try again or check the logs for errors.",
                        "id": abs(hash(f"error_{time.time()}"))
                    }
                    st.session_state.messages.append(error_msg)
                    display_message(error_msg)
                
                # Check for timeout
                if time.time() - start_time >= timeout:
                    st.error("Request timed out. Please try again with a simpler query.")
                    
                # Clean up any remaining messages
                while not st.session_state.assistant.message_queue.empty():
                    try:
                        st.session_state.assistant.message_queue.get_nowait()
                    except queue.Empty:
                        break
                        
        except Exception as e:
            logger.error("Error in chat: %s", traceback.format_exc())
            st.error(f"An error occurred: {str(e)}")

if __name__ == "__main__":
    main()