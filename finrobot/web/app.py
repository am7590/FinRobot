import streamlit as st
import websockets
import asyncio
import json
import os
from websockets.exceptions import ConnectionClosed

st.title("FinRobot Chat")

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat messages from history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Accept user input
if prompt := st.chat_input("What would you like to analyze?"):
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    # Display user message in chat message container
    with st.chat_message("user"):
        st.markdown(prompt)

    # Display assistant response in chat message container
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = []
        
        async def get_bot_response():
            try:
                async with websockets.connect("ws://localhost:8000/ws/chat", ping_interval=None) as websocket:
                    # Initialize session
                    await websocket.send(json.dumps({
                        "type": "config",
                        "agent_type": "SingleAssistantShadow",
                        "agent_config": {
                            "agent_config": "Expert_Investor",
                            "llm_config": {}
                        }
                    }))
                    
                    # Send message
                    await websocket.send(json.dumps({
                        "type": "message", 
                        "content": prompt
                    }))
                    
                    while True:
                        try:
                            response = json.loads(await websocket.recv())
                            message = response['message']
                            
                            # Show all messages except system prompts
                            if message['role'] != 'system' or not message.get('metadata', {}).get('prompt'):
                                # Handle tool calls
                                if tool_calls := message.get('metadata', {}).get('tool_call'):
                                    for call in tool_calls:
                                        full_response.append(f"🔧 **Tool Call**: {call['function']['name']}\n```json\n{call['function']['arguments']}\n```")
                                
                                # Handle tool responses
                                elif tool_responses := message.get('raw_message', {}).get('tool_responses'):
                                    for resp in tool_responses:
                                        full_response.append(f"📊 **Tool Response**: \n```\n{resp.get('content')}\n```")
                                
                                # Show normal messages
                                elif message.get('content'):
                                    full_response.append(f"**{message['role'].title()}**: {message['content']}")
                                
                                # Update display
                                message_placeholder.markdown('\n\n'.join(full_response) + "▌")
                            
                            # Handle input requests
                            if message.get('metadata', {}).get('request_reply'):
                                # Auto-reply with empty string to continue
                                await websocket.send(json.dumps({
                                    "type": "message",
                                    "content": ""
                                }))
                                continue
                            
                            # Check for completion
                            if message.get('content') and "TERMINATE" in message.get('content'):
                                break
                                
                        except ConnectionClosed:
                            if full_response:
                                break
                            full_response.append("❌ **Error**: Connection closed unexpectedly")
                            break
                        except Exception as e:
                            full_response.append(f"❌ **Error**: {str(e)}")
                            break
                    
                    final_response = '\n\n'.join(full_response)
                    message_placeholder.markdown(final_response)
                    return final_response

            except Exception as e:
                error_msg = f"❌ **Connection Error**: {str(e)}"
                message_placeholder.markdown(error_msg)
                return error_msg

        final_response = asyncio.run(get_bot_response())
        if final_response:  # Only append if we got a response
            st.session_state.messages.append({"role": "assistant", "content": final_response})