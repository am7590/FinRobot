import asyncio
import websockets
import json
import sys
import click
from typing import Dict
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.progress import Progress

console = Console()

def format_tool_call(content: Dict) -> str:
    """Format tool call content for display"""
    if not isinstance(content, dict):
        return str(content)
        
    tool_calls = content.get('tool_calls', [])
    if not tool_calls:
        return str(content)
        
    tool_call = tool_calls[0]
    return f"""Tool: {tool_call['function']['name']}
Arguments: {tool_call['function']['arguments']}
"""

async def chat_session(uri: str, agent_type: str, agent_config: Dict):
    """Interactive chat session with the agent"""
    try:
        async with websockets.connect(uri) as websocket:
            # Initialize session
            console.print("\n[bold blue]Initializing chat session...[/]")
            await websocket.send(json.dumps({
                "type": "config",
                "agent_type": agent_type,
                "agent_config": agent_config
            }))
            
            while True:
                # Get user input
                user_input = Prompt.ask("\n[bold green]You[/]")
                if user_input.lower() in ['exit', 'quit']:
                    break
                    
                # Send message
                await websocket.send(json.dumps({
                    "type": "message",
                    "content": user_input
                }))
                
                # Handle responses
                with Progress() as progress:
                    task = progress.add_task("[cyan]Thinking...", total=None)
                    
                    while True:
                        try:
                            response = json.loads(await websocket.recv())
                            message = response['message']
                            progress.update(task, visible=False)
                            
                            # Handle different message types
                            if message['role'] == 'assistant':
                                if isinstance(message.get('content'), dict):
                                    # Show tool calls
                                    if message['content'].get('tool_calls'):
                                        tool_call = message['content']['tool_calls'][0]
                                        console.print(Panel(
                                            f"Tool: {tool_call['function']['name']}\nArguments: {tool_call['function']['arguments']}",
                                            title="[bold yellow]Tool Call[/]",
                                            border_style="yellow"
                                        ))
                                else:
                                    # Show normal assistant messages
                                    console.print(Panel(
                                        str(message['content']),
                                        title="[bold blue]Assistant[/]",
                                        border_style="blue"
                                    ))

                            elif message['role'] == 'system':
                                # Handle system messages that need input
                                if message.get('metadata', {}).get('request_reply'):
                                    console.print(Panel(
                                        str(message['content']),
                                        title="[bold yellow]Input Required[/]",
                                        border_style="yellow"
                                    ))
                                    feedback = Prompt.ask("[bold yellow]Your response[/]")
                                    await websocket.send(json.dumps({
                                        "type": "message",
                                        "content": feedback
                                    }))
                                    if feedback.lower() in ['exit', 'quit']:
                                        return
                                else:
                                    # Show other system messages
                                    console.print(Panel(
                                        str(message['content']),
                                        title="[bold red]System[/]",
                                        border_style="red"
                                    ))
                            
                            # Show conversation markers
                            if message.get('metadata', {}).get('conversation_marker'):
                                console.print("\n[dim]" + "-" * 80 + "[/]\n")
                            
                            # Break if this was the last message in the sequence
                            if not message.get('metadata', {}).get('request_reply'):
                                break
                                
                        except websockets.exceptions.ConnectionClosed:
                            console.print("\n[bold red]Connection closed. Reconnecting...[/]")
                            return await chat_session(uri, agent_type, agent_config)
                            
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/]")
        if "connection" in str(e).lower():
            console.print("[yellow]Attempting to reconnect...[/]")
            await asyncio.sleep(1)
            return await chat_session(uri, agent_type, agent_config)
        raise

@click.command()
@click.option('--host', default='127.0.0.1', help='Server host')
@click.option('--port', default=8000, help='Server port')
@click.option('--agent', default='SingleAssistantShadow', help='Agent type')
def main(host: str, port: int, agent: str):
    """FinRobot CLI Chat Interface"""
    uri = f"ws://{host}:{port}/ws/chat"
    
    # Basic agent config
    config = {
        "agent_config": "Expert_Investor",
        "llm_config": {}  # Set by server
    }
    
    console.print("[bold]FinRobot Chat[/]")
    console.print("Type 'exit' or 'quit' to end the session\n")
    
    try:
        asyncio.run(chat_session(uri, agent, config))
    except KeyboardInterrupt:
        console.print("\n[bold]Session ended[/]")

if __name__ == "__main__":
    main() 