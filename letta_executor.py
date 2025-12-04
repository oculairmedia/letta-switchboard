"""
Letta API executor for sending messages to agents.
"""
import os
import logging

from letta_client import Letta

logger = logging.getLogger(__name__)

# Get base URL from environment (for self-hosted Letta)
LETTA_BASE_URL = os.getenv("LETTA_BASE_URL", "https://api.letta.com")


def get_letta_client(api_key: str) -> Letta:
    """Create a Letta client with the given API key."""
    return Letta(
        api_key=api_key,
        base_url=LETTA_BASE_URL,
    )


def validate_api_key(api_key: str) -> bool:
    """Validate API key by attempting to list agents."""
    try:
        client = get_letta_client(api_key)
        client.agents.list(limit=1)
        return True
    except Exception as e:
        logger.error(f"API key validation failed: {str(e)}")
        return False


async def execute_letta_message(agent_id: str, api_key: str, message: str, role: str = "user"):
    """
    Execute a message to a Letta agent asynchronously.
    
    Args:
        agent_id: The agent ID to send the message to
        api_key: The Letta API key
        message: The message content
        role: The role (user/system/assistant)
    
    Returns:
        dict with success status and run_id or error
    """
    try:
        client = get_letta_client(api_key)
        
        # Use create_async() with simple input string
        run = client.agents.messages.create_async(
            agent_id=agent_id,
            input=message,
        )
        
        logger.info(f"Successfully queued message for agent {agent_id}, run_id: {run.id}")
        return {"success": True, "run_id": run.id}
    
    except Exception as e:
        logger.error(f"Failed to send message to agent {agent_id}: {str(e)}")
        return {"success": False, "error": str(e)}
