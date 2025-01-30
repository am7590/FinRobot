from fastapi import FastAPI, WebSocket
from typing import Dict, Optional
import json
from contextlib import asynccontextmanager
from .agent_session import AgentSession
import logging
import uvicorn
from finrobot.utils import register_keys_from_json
import os

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global sessions store
sessions: Dict[str, AgentSession] = {}

work_dir = "../report"
os.makedirs(work_dir, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting FinRobot API server...")
    register_keys_from_json("config_api_keys")
    yield
    logger.info("Shutting down FinRobot API server...")
    sessions.clear()

app = FastAPI(lifespan=lifespan)

def get_default_llm_config():
    import autogen
    config_list = autogen.config_list_from_json(
        "OAI_CONFIG_LIST",
        filter_dict={
            "model": ["gpt-4o-mini"],
        },
    )
    logger.info(f"Loaded LLM config: {config_list}")
    return {
        "config_list": config_list,
        "timeout": 120,
        "temperature": 0.5,
    }

@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    logger.info("New WebSocket connection...")
    await websocket.accept()
    logger.info("WebSocket connection accepted")
    session: Optional[AgentSession] = None
    
    try:
        while True:
            data = await websocket.receive_json()
            logger.info(f"Received websocket data: {data}")
            
            # Handle configuration message
            if data.get("type") == "config":
                logger.info("Creating new session...")
                # Match test.py's initialization
                agent_config = {
                    "agent_config": data["agent_config"]["agent_config"],
                    "llm_config": get_default_llm_config(),
                    "max_consecutive_auto_reply": None,
                    "human_input_mode": "ALWAYS"
                }
                session = AgentSession(
                    agent_type=data["agent_type"],
                    agent_config=agent_config
                )
                sessions[session.session_id] = session
                logger.info(f"Created session {session.session_id}")
                continue
            
            # Handle chat messages
            if session:
                logger.info("Sending message to session...")
                session.send_message(data["content"])
                
                # Stream responses
                while True:
                    response = session.get_response(timeout=1)
                    if not response:
                        logger.info("No more responses")
                        break
                        
                    logger.info(f"Sending response: {response}")
                    await websocket.send_json({
                        "session_id": session.session_id,
                        "message": {
                            "role": response.role,
                            "content": response.content,
                            "metadata": response.metadata
                        }
                    })
            else:
                logger.error("No session found!")
                    
    except Exception as e:
        logger.exception(f"WebSocket error: {e}")
    finally:
        if session and session.session_id in sessions:
            del sessions[session.session_id]
            logger.info(f"Cleaned up session {session.session_id}")

if __name__ == "__main__":
    logger.info("Starting server...")
    uvicorn.run(
        "finrobot.api.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info"
    ) 