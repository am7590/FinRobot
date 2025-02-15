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

from finrobot.agents.workflow import SingleAssistantShadow
from finrobot.utils import register_keys_from_json

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
                max_consecutive_auto_reply=1,  # Limit auto-replies in general chat
                human_input_mode="TERMINATE"  # Stop after one response
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
                    # logger.debug("Assistant received message: %s", message)
                    
                    if isinstance(message, dict):
                        content = message.get("content", "")
                        tool_calls = message.get("tool_calls", [])
                        
                        # Add message to queue before processing tool calls
                        self.message_queue.put({
                            "role": "assistant",
                            "content": content,
                            "metadata": {"tool_calls": tool_calls} if tool_calls else {}
                        })
                        
                        # Process tool calls if present
                        if tool_calls:
                            logger.debug("Processing tool calls: %s", json.dumps(tool_calls, indent=2))
                            for tool_call in tool_calls:
                                if 'arguments' in tool_call.get('function', {}):
                                    try:
                                        logger.debug("Raw function arguments: %s", tool_call['function']['arguments'])
                                        args = json.loads(tool_call['function']['arguments'])
                                        logger.debug("Parsed arguments: %s", args)
                                        
                                        # List of argument names that should be treated as paths
                                        path_args = ['save_path', 'pdf_path', 'image_path', 'share_performance_image_path', 
                                                   'pe_eps_performance_image_path', 'file_path', 'target_file']
                                        
                                        # Process all path arguments
                                        for arg_name in path_args:
                                            if arg_name in args:
                                                if not args[arg_name]:
                                                    logger.error(f"Empty {arg_name} detected!")
                                                    continue
                                                    
                                                # Create absolute path using work_dir
                                                abs_path = os.path.join(self.work_dir, args[arg_name])
                                                logger.debug(f"Converting {arg_name} to absolute path: {abs_path}")
                                                
                                                # Create parent directory if it doesn't exist
                                                parent_dir = os.path.dirname(abs_path)
                                                logger.debug(f"Creating parent directory for {arg_name}: {parent_dir}")
                                                os.makedirs(parent_dir, exist_ok=True)
                                                
                                                # Update the argument with absolute path
                                                args[arg_name] = abs_path
                                        
                                        # Update the tool call arguments
                                        tool_call['function']['arguments'] = json.dumps(args)
                                        logger.debug("Updated tool call arguments: %s", tool_call['function']['arguments'])
                                        
                                    except json.JSONDecodeError as e:
                                        logger.error("Failed to parse tool call arguments: %s", e)
                                        continue
                                    except Exception as e:
                                        logger.error("Error processing tool call: %s", str(e))
                                        logger.error("Traceback: %s", traceback.format_exc())
                                        continue
                        
                       
                        
                        return original_receive(message, sender, request_reply, silent)
                    else:
                        content = str(message)
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
                    
                    if isinstance(message, dict):
                        content = message.get("content", "")
                        tool_calls = message.get("tool_calls", [])
                        tool_responses = message.get("tool_responses", [])
                        
                        self.message_queue.put({
                            "role": "assistant",
                            "content": content,
                            "metadata": {
                                "tool_calls": tool_calls if tool_calls else {},
                                "tool_responses": tool_responses if tool_responses else {}
                            }
                        })
                    else:
                        content = str(message)
                        self.message_queue.put({
                            "role": "assistant",
                            "content": content,
                            "metadata": {}
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
        """Start a chat session in a separate thread with proper cleanup"""
        def chat_thread():
            try:
                logger.info("Starting chat with message: %s", message)
                # Clear any existing messages in queue
                while not self.message_queue.empty():
                    try:
                        self.message_queue.get_nowait()
                    except queue.Empty:
                        break
                
                # Start the chat
                self.assistant.chat(message, **kwargs)
                logger.info("Chat completed")
            except Exception as e:
                logger.error("Error in chat: %s", str(e))
                # Add error message to queue
                self.message_queue.put({
                    "role": "assistant",
                    "content": f"An error occurred: {str(e)}",
                    "metadata": {"error": True}
                })
                raise
        
        # Create and start thread with Streamlit context
        thread = threading.Thread(target=chat_thread)
        add_script_run_ctx(thread)
        thread.daemon = True  # Make thread daemon so it doesn't block program exit
        thread.start()
        return thread

def initialize_session_state():
    """Initialize session state variables."""
    if "messages" not in st.session_state:
        st.session_state.messages = []
        
    if "assistant" not in st.session_state:
        try:
            # Get the root directory of the project
            current_dir = os.path.dirname(os.path.abspath(__file__))
            root_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
            
            # Set up config paths
            config_path = os.path.join(root_dir, "OAI_CONFIG_LIST")
            api_keys_path = os.path.join(root_dir, "config_api_keys")
            
            logger.debug("Using config paths: config_path=%s, api_keys_path=%s", config_path, api_keys_path)
            
            # Verify config files exist
            if not os.path.exists(config_path):
                raise FileNotFoundError(
                    f"OpenAI config file not found at: {config_path}\n"
                    "Please create this file with your OpenAI API configuration."
                )
            if not os.path.exists(api_keys_path):
                raise FileNotFoundError(
                    f"API keys file not found at: {api_keys_path}\n"
                    "Please create this file with your API keys."
                )
            
            # Create report directory
            report_dir = os.path.join(root_dir, "report")
            logger.debug("Creating report directory at: %s", report_dir)
            os.makedirs(report_dir, exist_ok=True)
            
            # Load API keys first
            register_keys_from_json(api_keys_path)
            
            # Verify FMP API key is loaded
            if 'FMP_API_KEY' not in os.environ:
                raise ValueError(
                    "FMP_API_KEY not found in config_api_keys\n"
                    "Please add your Financial Modeling Prep API key to the config file."
                )
            
            # Initialize assistant
            logger.info("Initializing StreamlitAssistant")
            
            # Change working directory to report directory
            logger.debug("Changed working directory to: %s", report_dir)
            os.chdir(report_dir)
            
            # Load LLM config
            with open(config_path, 'r') as f:
                llm_config = json.load(f)[0]
            
            st.session_state.assistant = StreamlitAssistant(
                agent_config="Expert_Investor",
                llm_config=llm_config,
                max_consecutive_auto_reply=None
            )
            logger.info("StreamlitAssistant initialized successfully")
            
        except FileNotFoundError as e:
            error_msg = f"""
            {str(e)}
            
            Please ensure you have the following files in your project root:
            1. OAI_CONFIG_LIST - Contains your OpenAI API configuration
            2. config_api_keys - Contains your API keys (including FMP_API_KEY)
            
            Example OAI_CONFIG_LIST:
            ```json
            [
                {{
                    "model": "gpt-4",
                    "api_key": "your-openai-api-key"
                }}
            ]
            ```
            
            Example config_api_keys:
            ```json
            {{
                "FMP_API_KEY": "your-fmp-api-key",
                "OPENAI_API_KEY": "your-openai-api-key"
            }}
            ```
            """
            logger.error("Configuration error: %s", str(e))
            st.error(error_msg)
            raise
        except Exception as e:
            logger.error("Failed to initialize StreamlitAssistant: %s", str(e))
            st.error(f"Failed to initialize assistant: {str(e)}")
            raise

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

def display_message(message: Dict[str, Any]):
    """Display a message in the Streamlit chat interface."""
    with st.chat_message(message["role"]):
        content = message.get("content", "")
        metadata = message.get("metadata", {})
        
        # Handle case where content is None or not a string
        if content is None:
            content = ""
        elif isinstance(content, dict):
            content = json.dumps(content, indent=2)
        elif not isinstance(content, str):
            content = str(content)
        
        # Display the message content if it exists
        if content:
            # Check if content contains an error message
            if "Error:" in content or "Traceback" in content:
                st.error(content)
            else:
                st.markdown(content)
        
        # Display tool calls if present
        tool_calls = metadata.get("tool_calls", [])
        if tool_calls:
            with st.expander("Tool Calls"):
                for tool_call in tool_calls:
                    st.code(json.dumps(tool_call, indent=2), language="json")
        
        # Display tool responses if present
        tool_responses = metadata.get("tool_responses", [])
        if tool_responses:
            with st.expander("Tool Responses"):
                for response in tool_responses:
                    # Check if response is an error
                    if isinstance(response, dict) and ('error' in response or 'traceback' in response):
                        st.error(json.dumps(response, indent=2))
                    else:
                        st.code(json.dumps(response, indent=2), language="json")
        
        # Extract and display file paths
        file_paths = extract_file_paths(content)
        
        # Display file viewers for found paths
        for file_path, context in file_paths:
            try:
                # Create a unique key for the expander
                expander_key = f"{file_path}_{hash(context)}"
                
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
                                mime="application/octet-stream"
                            )
                        
            except Exception as e:
                st.error(f"Error displaying file {file_path}: {str(e)}")

def generate_annual_report(ticker: str, year: str):
    """Generate an annual report using the AI agent approach."""
    try:
        # Get the root directory path
        current_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
        
        # Set up config paths
        config_path = os.path.join(root_dir, "OAI_CONFIG_LIST")
        api_keys_path = os.path.join(root_dir, "config_api_keys")
        
        # Load API keys first
        register_keys_from_json(api_keys_path)
        
        # Load OpenAI config
        with open(config_path, 'r') as f:
            config_list = json.load(f)
        
        # Initialize the AI assistant with proper configuration
        llm_config = {
            "config_list": config_list,
            "timeout": 120,
            "temperature": 0.5,
            "model": config_list[0]["model"],
            "api_key": config_list[0]["api_key"]
        }
        
        work_dir = os.path.join(root_dir, "report")
        os.makedirs(work_dir, exist_ok=True)
        
        # Change to work directory
        os.chdir(work_dir)
        
        # Format the date for the PDF filename (using December 31st of the year)
        report_date = f"{year}-12-31"
        pdf_filename = f"{ticker}_{report_date}_Equity_Research_report.pdf"
        
        assistant = SingleAssistantShadow(
            agent_config="Expert_Investor",
            llm_config=llm_config,
            max_consecutive_auto_reply=None,  # Allow unlimited auto-replies for PDF generation
            human_input_mode="NEVER"  # Keep automated for PDF generation
        )
        
        # Create the report generation message with more practical guidelines
        message = dedent(
            f"""
            Generate an annual report for {ticker}'s {year} 10-k report, following these guidelines:

            1. Working Plan:
            - First, explain your step-by-step plan before starting
            - Use tools one by one for clarity
            - All file operations should be done in "{work_dir}"
            - Display any generated images in the chat
            - Save the final PDF as "{pdf_filename}"

            2. Content Guidelines:
            - Each section should be 500-1000 words, focusing on quality and readability
            - Include the full analysis text directly in the PDF, not just references to text files
            - Ensure key information is clearly presented
            - Avoid redundancy and filler content
            - Use bullet points or numbered lists where appropriate

            3. Section Requirements:
            - Business Overview: Company background, core business model, market overview
            - Market Position: Industry standing, competitive advantages, growth opportunities
            - Operating Results: Key financial metrics, performance analysis, segment breakdown
            - Risk Assessment: Major risks and mitigation strategies
            - Charts: Include performance visualizations

            4. PDF Generation:
            - Include the complete text of each analysis directly in the PDF
            - DO NOT just reference text files in the PDF
            - Ensure proper formatting and readability
            - Include all charts and visualizations
            - Save the PDF as "{pdf_filename}"

            Begin by outlining your plan, then proceed with the analysis step by step.
            """
        )
        
        # Add initial message to chat
        user_message = {"role": "user", "content": f"Generating annual report for {ticker} ({year})..."}
        st.session_state.messages.append(user_message)
        
        # Start the chat in a separate thread
        def chat_thread():
            try:
                # Create message queue for real-time updates
                message_queue = queue.Queue()
                
                # Start the chat
                thread = assistant.chat(message, max_turns=50)
                
                # Process messages from queue
                while thread.is_alive() or not assistant.message_queue.empty():
                    try:
                        msg = assistant.message_queue.get_nowait()
                        st.session_state.messages.append(msg)
                        display_message(msg)
                    except queue.Empty:
                        continue
                        
            except Exception as e:
                logger.error("Error in chat thread: %s", str(e))
                logger.error("Traceback: %s", traceback.format_exc())
                st.error(f"Error generating report: {str(e)}")
        
        thread = threading.Thread(target=chat_thread)
        add_script_run_ctx(thread)
        thread.start()
        
        # Wait for the thread to complete
        while thread.is_alive():
            st.spinner("Generating annual report...")
            thread.join(0.1)
        
        # Display the generated PDF
        pdf_path = os.path.join(work_dir, pdf_filename)
        if os.path.exists(pdf_path):
            # Add PDF message to chat
            pdf_message = {
                "role": "assistant",
                "content": f"Report generated successfully! Here's the PDF report for {ticker} ({report_date}):",
                "metadata": {"file_path": pdf_path}
            }
            st.session_state.messages.append(pdf_message)
            display_message(pdf_message)
            
            # Display PDF in chat
            with st.chat_message("assistant"):
                with open(pdf_path, "rb") as f:
                    base64_pdf = base64.b64encode(f.read()).decode('utf-8')
                pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="700" height="1000" type="application/pdf"></iframe>'
                st.markdown(pdf_display, unsafe_allow_html=True)
        else:
            error_message = {
                "role": "assistant",
                "content": "Failed to generate PDF report. Please try again.",
                "metadata": {}
            }
            st.session_state.messages.append(error_message)
            display_message(error_message)
            
    except Exception as e:
        error_message = {
            "role": "assistant",
            "content": f"Error: {str(e)}",
            "metadata": {}
        }
        st.session_state.messages.append(error_message)
        display_message(error_message)
        logger.error("Error generating annual report: %s", traceback.format_exc())

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
        ticker = st.text_input("Enter ticker symbol (e.g., TSLA):")
        year = st.text_input("Enter year (e.g., 2023):")
        if st.button("Generate Report"):
            if ticker and year:
                generate_annual_report(ticker, year)
            else:
                st.warning("Please enter both ticker symbol and year")
    
    # Display existing messages
    for msg in st.session_state.messages:
        display_message(msg)
    
    # Chat input
    if prompt := st.chat_input("Message FinRobot..."):
        logger.info("Received user input: %s", prompt)
        
        # Add user message to session state
        user_message = {"role": "user", "content": prompt}
        st.session_state.messages.append(user_message)
        
        try:
            # Start chat in background with progress indicator
            with st.spinner("Processing your request..."):
                chat_thread = st.session_state.assistant.chat(prompt)
                
                # Process messages with timeout
                start_time = time.time()
                timeout = 60  # 1 minute timeout
                
                while (time.time() - start_time < timeout and 
                       (chat_thread.is_alive() or not st.session_state.assistant.message_queue.empty())):
                    try:
                        # Try to get message with short timeout
                        msg = st.session_state.assistant.message_queue.get(timeout=0.1)
                        
                        # Check for error message
                        if isinstance(msg, dict) and msg.get("metadata", {}).get("error"):
                            st.error(msg["content"])
                            break
                            
                        # Add and display message
                        st.session_state.messages.append(msg)
                        display_message(msg)
                        
                    except queue.Empty:
                        continue
                    except Exception as e:
                        logger.error("Error processing message: %s", str(e))
                        st.error(f"Error processing message: {str(e)}")
                        break
                
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