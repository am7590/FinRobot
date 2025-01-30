import streamlit as st
import requests
import json

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    st.session_state.session_id = None

st.title("FinRobot Chat")

# Chat interface
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

# Chat input
if prompt := st.chat_input("What would you like to chat about?"):
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    try:
        # Send message to API
        response = requests.post(
            "http://localhost:8000/chat",
            json={
                "message": prompt,
                "session_id": st.session_state.session_id
            }
        )
        response.raise_for_status()
        data = response.json()

        # Store session ID
        st.session_state.session_id = data["session_id"]

        # Handle response
        if data.get("error"):
            with st.chat_message("assistant"):
                st.error(data["error"])
            st.session_state.messages.append({"role": "assistant", "content": f"Error: {data['error']}"})
        elif data.get("tool_call"):
            with st.chat_message("assistant"):
                st.info(f"Processing request: {json.dumps(data['tool_call'], indent=2)}")
            st.session_state.messages.append({"role": "assistant", "content": f"Processing: {json.dumps(data['tool_call'], indent=2)}"})
        else:
            with st.chat_message("assistant"):
                st.write(data["response"])
            st.session_state.messages.append({"role": "assistant", "content": data["response"]})

    except Exception as e:
        st.error(f"Error: {str(e)}")
        st.session_state.messages.append({"role": "assistant", "content": f"Error: {str(e)}"})