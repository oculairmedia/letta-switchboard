"""
Standalone FastAPI application for Letta Switchboard.
Replaces Modal with local file storage and APScheduler.
"""
import json
import logging
import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse, HTMLResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dateutil import parser as date_parser

from models import (
    RecurringScheduleCreate,
    RecurringSchedule,
    OneTimeScheduleCreate,
    OneTimeSchedule,
)
from scheduler import is_recurring_schedule_due, is_onetime_schedule_due
from letta_executor import execute_letta_message, validate_api_key
from crypto_utils import get_api_key_hash, get_encryption_key, encrypt_json, decrypt_json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

security = HTTPBearer()

# Configuration from environment
DATA_DIR = os.getenv("LETTA_SWITCHBOARD_DATA_DIR", "/data")
SCHEDULES_BASE = f"{DATA_DIR}/schedules"
RESULTS_BASE = f"{DATA_DIR}/results"

# Lazy-load encryption key
_encryption_key = None


def get_encryption_key_cached():
    global _encryption_key
    if _encryption_key is None:
        _encryption_key = get_encryption_key()
    return _encryption_key


def get_recurring_schedule_path(api_key: str, schedule_id: str) -> str:
    """Get file path for recurring schedule."""
    api_key_hash = get_api_key_hash(api_key)
    return f"{SCHEDULES_BASE}/recurring/{api_key_hash}/{schedule_id}.json"


def get_onetime_schedule_path(api_key: str, execute_at: str, schedule_id: str) -> str:
    """Get file path for one-time schedule with time bucketing."""
    api_key_hash = get_api_key_hash(api_key)
    dt = date_parser.parse(execute_at)
    date_str = dt.strftime("%Y-%m-%d")
    hour_str = dt.strftime("%H")
    return f"{SCHEDULES_BASE}/one-time/{date_str}/{hour_str}/{api_key_hash}/{schedule_id}.json"


def save_schedule(file_path: str, schedule_data: dict):
    """Save encrypted schedule to file."""
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    encrypted_data = encrypt_json(schedule_data, get_encryption_key_cached())
    with open(file_path, "wb") as f:
        f.write(encrypted_data)


def load_schedule(file_path: str) -> dict:
    """Load and decrypt schedule from file."""
    try:
        with open(file_path, "rb") as f:
            encrypted_data = f.read()
        return decrypt_json(encrypted_data, get_encryption_key_cached())
    except FileNotFoundError:
        return None


def delete_schedule(file_path: str):
    """Delete schedule file."""
    try:
        Path(file_path).unlink()
        return True
    except FileNotFoundError:
        return False


def list_recurring_schedules_for_user(api_key: str) -> List[dict]:
    """List all recurring schedules for a specific user."""
    api_key_hash = get_api_key_hash(api_key)
    user_dir = f"{SCHEDULES_BASE}/recurring/{api_key_hash}"
    schedules = []
    
    if not Path(user_dir).exists():
        return schedules
    
    for file_path in Path(user_dir).glob("*.json"):
        try:
            with open(file_path, "rb") as f:
                encrypted_data = f.read()
            schedule = decrypt_json(encrypted_data, get_encryption_key_cached())
            schedules.append(schedule)
        except Exception as e:
            logger.error(f"Failed to load schedule {file_path}: {e}")
    
    return schedules


def list_onetime_schedules_for_user(api_key: str) -> List[dict]:
    """List all one-time schedules for a specific user."""
    api_key_hash = get_api_key_hash(api_key)
    base_dir = f"{SCHEDULES_BASE}/one-time"
    schedules = []
    
    if not Path(base_dir).exists():
        return schedules
    
    for date_dir in Path(base_dir).iterdir():
        if not date_dir.is_dir():
            continue
        for hour_dir in date_dir.iterdir():
            if not hour_dir.is_dir():
                continue
            user_dir = hour_dir / api_key_hash
            if not user_dir.exists():
                continue
            
            for file_path in user_dir.glob("*.json"):
                try:
                    with open(file_path, "rb") as f:
                        encrypted_data = f.read()
                    schedule = decrypt_json(encrypted_data, get_encryption_key_cached())
                    schedules.append(schedule)
                except Exception as e:
                    logger.error(f"Failed to load schedule {file_path}: {e}")
    
    return schedules


def list_all_recurring_schedules() -> List[dict]:
    """List all recurring schedules across all users (for cron job)."""
    schedules = []
    recurring_dir = f"{SCHEDULES_BASE}/recurring"
    
    if not Path(recurring_dir).exists():
        return schedules
    
    for user_dir in Path(recurring_dir).iterdir():
        if not user_dir.is_dir():
            continue
        for file_path in user_dir.glob("*.json"):
            try:
                with open(file_path, "rb") as f:
                    encrypted_data = f.read()
                schedule = decrypt_json(encrypted_data, get_encryption_key_cached())
                schedules.append(schedule)
            except Exception as e:
                logger.error(f"Failed to load schedule {file_path}: {e}")
    
    return schedules


def list_onetime_schedules_for_time(date_str: str, hour_str: str) -> List[dict]:
    """List all one-time schedules for a specific date/hour (for cron job)."""
    schedules = []
    time_dir = f"{SCHEDULES_BASE}/one-time/{date_str}/{hour_str}"
    
    if not Path(time_dir).exists():
        return schedules
    
    for user_dir in Path(time_dir).iterdir():
        if not user_dir.is_dir():
            continue
        for file_path in user_dir.glob("*.json"):
            try:
                with open(file_path, "rb") as f:
                    encrypted_data = f.read()
                schedule = decrypt_json(encrypted_data, get_encryption_key_cached())
                schedules.append(schedule)
            except Exception as e:
                logger.error(f"Failed to load schedule {file_path}: {e}")
    
    return schedules


def find_onetime_schedule_for_user(api_key: str, schedule_id: str) -> tuple[dict, str]:
    """Find a one-time schedule by ID for a specific user. Returns (schedule, file_path)."""
    api_key_hash = get_api_key_hash(api_key)
    base_dir = f"{SCHEDULES_BASE}/one-time"
    
    if not Path(base_dir).exists():
        return None, None
    
    for date_dir in Path(base_dir).iterdir():
        if not date_dir.is_dir():
            continue
        for hour_dir in date_dir.iterdir():
            if not hour_dir.is_dir():
                continue
            user_dir = hour_dir / api_key_hash
            if not user_dir.exists():
                continue
            
            file_path = user_dir / f"{schedule_id}.json"
            if file_path.exists():
                try:
                    with open(file_path, "rb") as f:
                        encrypted_data = f.read()
                    schedule = decrypt_json(encrypted_data, get_encryption_key_cached())
                    return schedule, str(file_path)
                except Exception as e:
                    logger.error(f"Failed to load schedule {file_path}: {e}")
    
    return None, None


def save_execution_result(api_key: str, schedule_id: str, schedule_type: str, agent_id: str, message: str, run_id: str = None, error: str = None, status: str = "success"):
    """Save execution result to results folder."""
    api_key_hash = get_api_key_hash(api_key)
    result_dir = f"{RESULTS_BASE}/{api_key_hash}"
    Path(result_dir).mkdir(parents=True, exist_ok=True)
    
    result_file = f"{result_dir}/{schedule_id}.json"
    
    result_data = {
        "schedule_id": schedule_id,
        "schedule_type": schedule_type,
        "status": status,
        "agent_id": agent_id,
        "message": message,
        "executed_at": datetime.utcnow().isoformat(),
    }
    
    if run_id:
        result_data["run_id"] = run_id
    if error:
        result_data["error"] = error
    
    encrypted_data = encrypt_json(result_data, get_encryption_key_cached())
    with open(result_file, "wb") as f:
        f.write(encrypted_data)
    
    logger.info(f"Saved execution result for schedule {schedule_id}, run_id: {run_id}")


def cleanup_empty_directories():
    """Remove empty directories to keep filesystem clean."""
    removed_count = 0
    
    onetime_base = f"{SCHEDULES_BASE}/one-time"
    if Path(onetime_base).exists():
        for date_dir in Path(onetime_base).iterdir():
            if not date_dir.is_dir():
                continue
            
            for hour_dir in date_dir.iterdir():
                if not hour_dir.is_dir():
                    continue
                
                for user_dir in hour_dir.iterdir():
                    if user_dir.is_dir() and not any(user_dir.iterdir()):
                        user_dir.rmdir()
                        removed_count += 1
                
                if not any(hour_dir.iterdir()):
                    hour_dir.rmdir()
                    removed_count += 1
            
            if not any(date_dir.iterdir()):
                date_dir.rmdir()
                removed_count += 1
    
    recurring_base = f"{SCHEDULES_BASE}/recurring"
    if Path(recurring_base).exists():
        for user_dir in Path(recurring_base).iterdir():
            if user_dir.is_dir() and not any(user_dir.iterdir()):
                user_dir.rmdir()
                removed_count += 1
    
    if removed_count > 0:
        logger.info(f"Cleanup: Removed {removed_count} empty directories")


async def execute_schedule(
    schedule_id: str,
    agent_id: str,
    api_key: str,
    message: str,
    role: str,
    schedule_type: str,
    execute_at: str = None,
):
    """Execute a scheduled message."""
    logger.info(f"Executing {schedule_type} schedule {schedule_id} for agent {agent_id}")

    if schedule_type == "one-time" and execute_at:
        file_path = get_onetime_schedule_path(api_key, execute_at, schedule_id)
    else:
        file_path = get_recurring_schedule_path(api_key, schedule_id)

    schedule = load_schedule(file_path)
    if not schedule:
        if schedule_type == "one-time":
            logger.debug(f"One-time schedule {schedule_id} not found (already executed or deleted)")
        else:
            logger.info(f"Recurring schedule {schedule_id} was deleted, skipping execution")
        return {"success": False, "error": "Schedule deleted"}
    
    # For one-time schedules: DELETE IMMEDIATELY to prevent race condition
    if schedule_type == "one-time":
        try:
            Path(file_path).unlink()
            logger.info(f"Deleted one-time schedule {schedule_id} to prevent re-execution")
        except Exception as e:
            logger.error(f"Failed to delete schedule {schedule_id}, may re-execute: {e}")
            return {"success": False, "error": "Could not lock schedule for execution"}
    
    # For recurring schedules: update last_run timestamp
    elif schedule_type == "recurring":
        schedule["last_run"] = datetime.utcnow().isoformat()
        save_schedule(file_path, schedule)
        logger.info(f"Updated last_run for recurring schedule {schedule_id}")
    
    # Execute the message
    result = await execute_letta_message(agent_id, api_key, message, role)
    
    if result.get("success"):
        save_execution_result(
            api_key=api_key,
            schedule_id=schedule_id,
            schedule_type=schedule_type,
            agent_id=agent_id,
            message=message,
            run_id=result.get("run_id"),
            status="success"
        )
    else:
        error_msg = result.get("error", "Unknown error")
        logger.error(f"Execution failed for schedule {schedule_id}: {error_msg}")
        
        save_execution_result(
            api_key=api_key,
            schedule_id=schedule_id,
            schedule_type=schedule_type,
            agent_id=agent_id,
            message=message,
            error=error_msg,
            status="failed"
        )
        
        # Terminate recurring schedules on failure
        if schedule_type == "recurring":
            try:
                Path(file_path).unlink()
                logger.warning(f"Terminated recurring schedule {schedule_id} due to execution failure: {error_msg}")
            except Exception as e:
                logger.error(f"Failed to delete failed recurring schedule {schedule_id}: {e}")
    
    return result


async def check_and_execute_schedules():
    """Check all schedules and execute due ones."""
    logger.info("Checking schedules...")
    
    current_time = datetime.now(timezone.utc)
    
    # Check recurring schedules
    recurring_schedules = list_all_recurring_schedules()
    for schedule in recurring_schedules:
        if is_recurring_schedule_due(schedule, current_time):
            logger.info(f"Executing recurring schedule {schedule['id']}")
            asyncio.create_task(execute_schedule(
                schedule_id=schedule["id"],
                agent_id=schedule["agent_id"],
                api_key=schedule["api_key"],
                message=schedule["message"],
                role=schedule["role"],
                schedule_type="recurring",
            ))
    
    # Check one-time schedules
    date_str = current_time.strftime("%Y-%m-%d")
    hour_str = current_time.strftime("%H")
    onetime_schedules = list_onetime_schedules_for_time(date_str, hour_str)
    
    for schedule in onetime_schedules:
        if is_onetime_schedule_due(schedule, current_time):
            logger.info(f"Executing one-time schedule {schedule['id']}")
            asyncio.create_task(execute_schedule(
                schedule_id=schedule["id"],
                agent_id=schedule["agent_id"],
                api_key=schedule["api_key"],
                message=schedule["message"],
                role=schedule["role"],
                schedule_type="one-time",
                execute_at=schedule["execute_at"],
            ))
    
    cleanup_empty_directories()
    logger.info("Schedule check complete")


# APScheduler instance
scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage scheduler lifecycle."""
    # Start scheduler on startup
    scheduler.add_job(
        check_and_execute_schedules,
        CronTrigger(minute="*"),  # Every minute
        id="check_schedules",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started - checking schedules every minute")
    
    yield
    
    # Shutdown scheduler
    scheduler.shutdown()
    logger.info("Scheduler stopped")


# Create FastAPI app with lifespan
app = FastAPI(
    title="Letta Switchboard",
    description="Self-hosted message scheduling service for Letta agents",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def root(request: Request):
    """Landing page with usage instructions."""
    accept_header = request.headers.get("accept", "")
    wants_html = "text/html" in accept_header
    
    base_url = os.getenv("LETTA_SWITCHBOARD_BASE_URL", "http://localhost:8000")
    
    info = {
        "service": "Letta Switchboard",
        "description": "Self-hosted message scheduling service for Letta agents",
        "version": "1.0.0",
        "status": "operational",
        "scheduler": "running" if scheduler.running else "stopped",
        "endpoints": {
            "POST /schedules/one-time": "Create a one-time schedule",
            "POST /schedules/recurring": "Create a recurring schedule",
            "GET /schedules/one-time": "List your one-time schedules",
            "GET /schedules/recurring": "List your recurring schedules",
            "GET /schedules/one-time/{id}": "Get specific one-time schedule",
            "GET /schedules/recurring/{id}": "Get specific recurring schedule",
            "DELETE /schedules/one-time/{id}": "Delete one-time schedule",
            "DELETE /schedules/recurring/{id}": "Delete recurring schedule",
            "GET /results": "List execution results",
            "GET /results/{schedule_id}": "Get result for specific schedule",
            "GET /health": "Health check endpoint",
        },
        "authentication": "All endpoints require 'Authorization: Bearer YOUR_LETTA_API_KEY' header",
    }
    
    if wants_html:
        # Return dashboard
        dashboard_path = Path(__file__).parent / "dashboard.html"
        if dashboard_path.exists():
            with open(dashboard_path, "r") as f:
                return HTMLResponse(content=f.read())
    
    return info


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "scheduler": "running" if scheduler.running else "stopped",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/dashboard")
async def dashboard():
    """Dashboard UI for managing schedules."""
    dashboard_path = Path(__file__).parent / "dashboard.html"
    if dashboard_path.exists():
        with open(dashboard_path, "r") as f:
            return HTMLResponse(content=f.read())
    raise HTTPException(status_code=404, detail="Dashboard not found")


@app.post("/schedules/recurring")
async def create_recurring_schedule(schedule: RecurringScheduleCreate, credentials: HTTPAuthorizationCredentials = Security(security)):
    api_key = credentials.credentials
    if not validate_api_key(api_key):
        raise HTTPException(status_code=401, detail="Invalid Letta API key")
    
    schedule_obj = RecurringSchedule(api_key=api_key, **schedule.model_dump())
    schedule_dict = schedule_obj.model_dump(mode='json')
    file_path = get_recurring_schedule_path(api_key, schedule_obj.id)
    save_schedule(file_path, schedule_dict)
    response_dict = schedule_dict.copy()
    response_dict.pop("api_key", None)
    return JSONResponse(content=response_dict, status_code=201)


@app.post("/schedules/one-time")
async def create_onetime_schedule(schedule: OneTimeScheduleCreate, credentials: HTTPAuthorizationCredentials = Security(security)):
    api_key = credentials.credentials
    if not validate_api_key(api_key):
        raise HTTPException(status_code=401, detail="Invalid Letta API key")
    
    schedule_obj = OneTimeSchedule(api_key=api_key, **schedule.model_dump())
    schedule_dict = schedule_obj.model_dump(mode='json')
    file_path = get_onetime_schedule_path(api_key, schedule.execute_at, schedule_obj.id)
    save_schedule(file_path, schedule_dict)
    response_dict = schedule_dict.copy()
    response_dict.pop("api_key", None)
    return JSONResponse(content=response_dict, status_code=201)


@app.get("/schedules/recurring")
async def list_recurring_schedules(credentials: HTTPAuthorizationCredentials = Security(security)):
    api_key = credentials.credentials
    if not validate_api_key(api_key):
        raise HTTPException(status_code=401, detail="Invalid Letta API key")
    
    schedules = list_recurring_schedules_for_user(api_key)
    for schedule in schedules:
        schedule.pop("api_key", None)
    return JSONResponse(content=schedules)


@app.get("/schedules/one-time")
async def list_onetime_schedules(credentials: HTTPAuthorizationCredentials = Security(security)):
    api_key = credentials.credentials
    if not validate_api_key(api_key):
        raise HTTPException(status_code=401, detail="Invalid Letta API key")
    
    schedules = list_onetime_schedules_for_user(api_key)
    for schedule in schedules:
        schedule.pop("api_key", None)
    return JSONResponse(content=schedules)


@app.get("/schedules/recurring/{schedule_id}")
async def get_recurring_schedule(schedule_id: str, credentials: HTTPAuthorizationCredentials = Security(security)):
    api_key = credentials.credentials
    if not validate_api_key(api_key):
        raise HTTPException(status_code=401, detail="Invalid Letta API key")
    
    file_path = get_recurring_schedule_path(api_key, schedule_id)
    schedule = load_schedule(file_path)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if schedule.get("api_key") != api_key:
        raise HTTPException(status_code=403, detail="Forbidden")
    schedule_copy = schedule.copy()
    schedule_copy.pop("api_key", None)
    return JSONResponse(content=schedule_copy)


@app.get("/schedules/one-time/{schedule_id}")
async def get_onetime_schedule(schedule_id: str, credentials: HTTPAuthorizationCredentials = Security(security)):
    api_key = credentials.credentials
    if not validate_api_key(api_key):
        raise HTTPException(status_code=401, detail="Invalid Letta API key")
    
    schedule, _ = find_onetime_schedule_for_user(api_key, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if schedule.get("api_key") != api_key:
        raise HTTPException(status_code=403, detail="Forbidden")
    schedule_copy = schedule.copy()
    schedule_copy.pop("api_key", None)
    return JSONResponse(content=schedule_copy)


@app.delete("/schedules/recurring/{schedule_id}")
async def delete_recurring_schedule(schedule_id: str, credentials: HTTPAuthorizationCredentials = Security(security)):
    api_key = credentials.credentials
    if not validate_api_key(api_key):
        raise HTTPException(status_code=401, detail="Invalid Letta API key")
    
    file_path = get_recurring_schedule_path(api_key, schedule_id)
    schedule = load_schedule(file_path)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if schedule.get("api_key") != api_key:
        raise HTTPException(status_code=403, detail="Forbidden")
    if delete_schedule(file_path):
        return JSONResponse(content={"message": "Schedule deleted"})
    else:
        raise HTTPException(status_code=404, detail="Schedule not found")


@app.delete("/schedules/one-time/{schedule_id}")
async def delete_onetime_schedule(schedule_id: str, credentials: HTTPAuthorizationCredentials = Security(security)):
    api_key = credentials.credentials
    if not validate_api_key(api_key):
        raise HTTPException(status_code=401, detail="Invalid Letta API key")
    
    schedule, file_path = find_onetime_schedule_for_user(api_key, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if schedule.get("api_key") != api_key:
        raise HTTPException(status_code=403, detail="Forbidden")
    if delete_schedule(file_path):
        return JSONResponse(content={"message": "Schedule deleted"})
    else:
        raise HTTPException(status_code=404, detail="Schedule not found")


@app.get("/results")
async def list_execution_results(credentials: HTTPAuthorizationCredentials = Security(security)):
    """List all execution results for the authenticated user."""
    api_key = credentials.credentials
    if not validate_api_key(api_key):
        raise HTTPException(status_code=401, detail="Invalid Letta API key")
    
    api_key_hash = get_api_key_hash(api_key)
    results_dir = f"{RESULTS_BASE}/{api_key_hash}"
    results = []
    
    if Path(results_dir).exists():
        for result_file in Path(results_dir).glob("*.json"):
            try:
                with open(result_file, "rb") as f:
                    encrypted_data = f.read()
                result = decrypt_json(encrypted_data, get_encryption_key_cached())
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to load result {result_file}: {e}")
    
    return JSONResponse(content=results)


@app.get("/results/{schedule_id}")
async def get_execution_result(schedule_id: str, credentials: HTTPAuthorizationCredentials = Security(security)):
    """Get execution result for a specific schedule."""
    api_key = credentials.credentials
    if not validate_api_key(api_key):
        raise HTTPException(status_code=401, detail="Invalid Letta API key")
    
    api_key_hash = get_api_key_hash(api_key)
    result_file = f"{RESULTS_BASE}/{api_key_hash}/{schedule_id}.json"
    
    if not Path(result_file).exists():
        raise HTTPException(status_code=404, detail="Result not found")
    
    try:
        with open(result_file, "rb") as f:
            encrypted_data = f.read()
        result = decrypt_json(encrypted_data, get_encryption_key_cached())
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Failed to load result: {e}")
        raise HTTPException(status_code=500, detail="Failed to load result")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
