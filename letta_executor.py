from letta_client import Letta, MessageCreate, TextContent
import logging

logger = logging.getLogger(__name__)


def validate_api_key(api_key: str) -> bool:
    try:
        client = Letta(token=api_key)
        client.agents.list(limit=1)
        return True
    except Exception as e:
        logger.error(f"API key validation failed: {str(e)}")
        return False


async def execute_letta_message(agent_id: str, api_key: str, message: str, role: str = "user"):
    try:
        client = Letta(token=api_key)
        
        # Use create_async() with proper MessageCreate objects
        run = client.agents.messages.create_async(
            agent_id=agent_id,
            messages=[
                MessageCreate(
                    role=role,
                    content=[
                        TextContent(text=message)
                    ]
                )
            ]
        )
        
        logger.info(f"Successfully queued message for agent {agent_id}, run_id: {run.id}")
        return {"success": True, "run_id": run.id}
    
    except Exception as e:
        logger.error(f"Failed to send message to agent {agent_id}: {str(e)}")
        return {"success": False, "error": str(e)}
