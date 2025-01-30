from fastapi import FastAPI, HTTPException
from typing import Dict, Optional
from pydantic import BaseModel
import json
from contextlib import asynccontextmanager
from .agent_session import AgentSession
import logging
import uvicorn
from finrobot.utils import register_keys_from_json
import os
from uuid import uuid4

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='[SERVER] %(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global sessions store
sessions: Dict[str, AgentSession] = {}

work_dir = "../report"
os.makedirs(work_dir, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== Starting FinRobot API server ===")
    register_keys_from_json("config_api_keys")
    yield
    logger.info("=== Shutting down FinRobot API server ===")
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
    logger.debug(f"Loaded LLM config: {json.dumps(config_list, indent=2)}")
    return {
        "config_list": config_list,
        "timeout": 120,
        "temperature": 0.5,
    }

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    session_id: str
    response: Optional[str] = None
    tool_call: Optional[dict] = None
    error: Optional[str] = None

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        # Get or create session
        session = None
        if request.session_id:
            session = sessions.get(request.session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
        else:
            # Create new agent session
            agent_config = {
                "agent_config": "Expert_Investor",
                "llm_config": get_default_llm_config(),
                "max_consecutive_auto_reply": None,
                "human_input_mode": "ALWAYS"
            }
            session = AgentSession(
                agent_type="SingleAssistantShadow",
                agent_config=agent_config
            )
            sessions[session.session_id] = session
            logger.info(f"Created new session: {session.session_id}")

        # Send message and get response
        logger.info(f"Processing message in session {session.session_id}")
        session.send_message(request.message)
        
        # Wait for initial response
        response = await session.get_next_response(timeout=30)
        
        if not response:
            return ChatResponse(
                session_id=session.session_id,
                error="No response received in time"
            )
            
        # Skip user messages
        while response and response.role == "user":
            response = await session.get_next_response(timeout=30)
            
        if not response:
            return ChatResponse(
                session_id=session.session_id,
                error="No assistant response received"
            )
            
        # Handle tool calls
        if response.metadata and response.metadata.get("tool_call"):
            return ChatResponse(
                session_id=session.session_id,
                tool_call=response.metadata.get("raw_message")
            )
            
        # Handle normal responses
        return ChatResponse(
            session_id=session.session_id,
            response=response.content
        )

    except Exception as e:
        logger.error(f"Error processing chat request: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/session/{session_id}")
async def end_session(session_id: str):
    if session_id in sessions:
        del sessions[session_id]
        return {"status": "success", "message": f"Session {session_id} ended"}
    raise HTTPException(status_code=404, detail="Session not found")

if __name__ == "__main__":
    logger.info("Starting server...")
    uvicorn.run(
        "finrobot.api.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="debug"
    ) 