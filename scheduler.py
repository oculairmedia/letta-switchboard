from croniter import croniter
from datetime import datetime, timezone
from dateutil import parser
import logging

logger = logging.getLogger(__name__)


def is_recurring_schedule_due(schedule_dict: dict, current_time: datetime) -> bool:
    cron_expression = schedule_dict["cron"]
    last_run = schedule_dict.get("last_run")
    
    if last_run:
        last_run_dt = parser.parse(last_run)
    else:
        last_run_dt = parser.parse(schedule_dict["created_at"])
    
    if last_run_dt.tzinfo is None:
        last_run_dt = last_run_dt.replace(tzinfo=timezone.utc)
    
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    
    cron = croniter(cron_expression, last_run_dt)
    next_run = cron.get_next(datetime)
    
    if next_run.tzinfo is None:
        next_run = next_run.replace(tzinfo=timezone.utc)
    
    return current_time >= next_run


def is_onetime_schedule_due(schedule_dict: dict, current_time: datetime) -> bool:
    if schedule_dict.get("executed", False):
        return False
    
    execute_at_str = schedule_dict["execute_at"]
    execute_at = parser.parse(execute_at_str)
    
    if execute_at.tzinfo is None:
        execute_at = execute_at.replace(tzinfo=timezone.utc)
    
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    
    return current_time >= execute_at
