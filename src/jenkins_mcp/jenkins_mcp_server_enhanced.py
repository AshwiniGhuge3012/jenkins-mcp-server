# jenkins_mcp_server.py

import os
import sys
import argparse
import logging
from typing import Optional, Dict, List, Union, Any
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import requests
from urllib.parse import urlencode, quote
import uuid
from fastapi import status
from fastapi.responses import JSONResponse
import threading
from datetime import datetime, timedelta
import fnmatch

# Load environment variables
load_dotenv()

# --- Enhanced Logging Setup ---
# Create a custom logger
logger = logging.getLogger("jenkins_mcp")
logger.setLevel(logging.INFO)

# Create a handler
handler = logging.StreamHandler()

# Create a more detailed formatter and add it to the handler
# This formatter includes a timestamp, logger name, log level, and the message.
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

# Add the handler to the logger
# This prevents duplication of logs if basicConfig was called elsewhere.
if not logger.handlers:
    logger.addHandler(handler)

# Jenkins configuration
JENKINS_URL = os.getenv("JENKINS_URL", "http://localhost:8080")
JENKINS_USER = os.getenv("JENKINS_USER")
JENKINS_API_TOKEN = os.getenv("JENKINS_API_TOKEN")

if not JENKINS_USER or not JENKINS_API_TOKEN:
    logger.error("Missing Jenkins credentials. Please set JENKINS_USER and JENKINS_API_TOKEN.")
    sys.exit(1)

# Global CSRF crumb cache
_crumb_cache = {
    "token": None,
    "expires": None,
    "lock": threading.Lock()
}
# --- LLM Integration Resources ---

# This section includes resources, prompts, and sampling configurations for LLM integration.
LLM_RESOURCES = {
    "prompts": {
        "summarize_log": "Summarize the following Jenkins console log. Identify any errors, critical warnings, or the root cause of a failure. Provide a concise summary of the build's outcome:\n\n{log_text}",
        "suggest_job_from_request": "Based on the user's request, suggest a Jenkins job to run and the necessary parameters. \nUser request: '{user_request}'. \n\nAvailable jobs and their descriptions:\n{job_list_details}",
        "analyze_build_status": "The build {build_number} for job '{job_name}' finished with status '{status}'. Explain what this status likely means in a Jenkins context and suggest potential next steps for the user.",
        "generate_parameters": "A user wants to run the Jenkins job '{job_name}'. Based on the job's purpose ('{job_description}') and the user's goal ('{user_goal}'), suggest appropriate values for the following parameters:\n{parameter_list}"
    },
    "sampling_config": {
        "temperature": 0.5,
        "top_p": 0.95,
        "max_tokens": 1024,
        "frequency_penalty": 0,
        "presence_penalty": 0
    }
}


# Helper to process multiselect parameters
def process_jenkins_parameters(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, str]:
    """
    Process parameters for Jenkins, handling multiselect and other parameter types.
    Jenkins expects all parameters as strings, with multiselect values comma-separated.
    """
    processed_params = {}
    
    for key, value in params.items():
        if isinstance(value, list):
            processed_params[key] = ','.join(str(v) for v in value)
            logger.info(f"[{context['request_id']}] Processed multiselect parameter '{key}': {value} -> '{processed_params[key]}'")
        elif isinstance(value, bool):
            processed_params[key] = str(value).lower()
            logger.info(f"[{context['request_id']}] Processed boolean parameter '{key}': {value} -> '{processed_params[key]}'")
        else:
            processed_params[key] = str(value)
    
    return processed_params

# Pydantic models
class TriggerJobResponse(BaseModel):
    job_name: str
    status: str
    queue_url: Optional[str] = None
    processed_params: Optional[Dict[str, str]] = None

class BuildStatusResponse(BaseModel):
    job_name: str
    build_number: int
    status: str = "UNKNOWN"
    timestamp: Optional[int] = None
    duration: Optional[int] = None
    url: Optional[str] = None

class ConsoleLogResponse(BaseModel):
    log: str
    has_more: bool = False
    log_size: Optional[int] = None

class JobParameter(BaseModel):
    name: str
    type: str
    default_value: Optional[Any] = None
    description: Optional[str] = None
    choices: Optional[List[str]] = None

class JobInfo(BaseModel):
    name: str
    description: Optional[str] = None
    parameters: List[JobParameter] = []
    last_build_number: Optional[int] = None
    last_build_status: Optional[str] = None

class JobInfoResponse(BaseModel):
    """Response for get_job_info that can contain either direct job info or search results."""
    success: bool
    job_info: Optional[JobInfo] = None
    search_results: Optional[List[Dict[str, Any]]] = None
    message: str
    suggestions: Optional[List[str]] = None

class SummarizeBuildLogResponse(BaseModel):
    summary: str
    prompt_used: str
    sampling_config: Dict[str, Union[float, int]]

class HealthCheckResponse(BaseModel):
    status: str
    details: Optional[str] = None

class JobTreeItem(BaseModel):
    name: str
    full_name: str
    type: str  # "job" or "folder"
    url: Optional[str] = None
    description: Optional[str] = None

class FolderInfo(BaseModel):
    name: str
    full_name: str
    description: Optional[str] = None
    jobs: List[JobTreeItem] = []
    folders: List[JobTreeItem] = []

# CSRF Crumb token management
def get_jenkins_crumb(context: Dict[str, Any]) -> Optional[str]:
    """Get Jenkins CSRF crumb token for POST operations."""
    request_id = context.get('request_id', 'N/A')
    
    with _crumb_cache["lock"]:
        # Check if we have a valid cached crumb
        if (_crumb_cache["token"] and _crumb_cache["expires"] and 
            datetime.now() < _crumb_cache["expires"]):
            logger.info(f"[{request_id}] Using cached crumb token")
            return _crumb_cache["token"]
        
        # Fetch new crumb
        try:
            logger.info(f"[{request_id}] Fetching new CSRF crumb token")
            url = f"{JENKINS_URL}/crumbIssuer/api/json"
            auth = (JENKINS_USER, JENKINS_API_TOKEN)
            response = requests.get(url, auth=auth, timeout=10)
            response.raise_for_status()
            
            crumb_data = response.json()
            crumb_token = crumb_data.get("crumb")
            
            if crumb_token:
                # Cache crumb for 30 minutes
                _crumb_cache["token"] = crumb_token
                _crumb_cache["expires"] = datetime.now() + timedelta(minutes=30)
                logger.info(f"[{request_id}] Successfully fetched and cached new crumb token")
                return crumb_token
            else:
                logger.warning(f"[{request_id}] No crumb token in response")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.warning(f"[{request_id}] Failed to fetch crumb token: {e}")
            return None

# Helper to make Jenkins requests for nested job paths
def jenkins_request_nested(method, job_path, endpoint_suffix, context: Dict[str, Any], **kwargs):
    """Make Jenkins request handling nested job paths like 'folder1/subfolder/jobname'."""
    request_id = context.get('request_id', 'N/A')
    
    # URL encode each path segment
    path_parts = job_path.split('/')
    encoded_parts = [quote(part, safe='') for part in path_parts]
    encoded_path = '/job/'.join(encoded_parts)
    
    url = f"{JENKINS_URL}/job/{encoded_path}/{endpoint_suffix}"
    
    auth = (JENKINS_USER, JENKINS_API_TOKEN)
    headers = kwargs.get('headers', {})
    
    # Add CSRF crumb for POST operations
    if method.upper() in ['POST', 'PUT', 'DELETE']:
        crumb = get_jenkins_crumb(context)
        if crumb:
            headers['Jenkins-Crumb'] = crumb
            logger.info(f"[{request_id}] Added CSRF crumb to {method} request")
    
    kwargs['headers'] = headers
    
    logger.info(f"[{request_id}] Making nested Jenkins API request: {method} {url}")
    try:
        response = requests.request(method, url, auth=auth, **kwargs)
        response.raise_for_status()
        logger.info(f"[{request_id}] Nested Jenkins API request successful (Status: {response.status_code})")
        return response
    except requests.exceptions.RequestException as e:
        logger.error(f"[{request_id}] Nested Jenkins API request failed: {e}")
        raise

# Helper to make authenticated Jenkins requests
def jenkins_request(method, endpoint, context: Dict[str, Any], is_job_specific: bool = True, **kwargs):
    request_id = context.get('request_id', 'N/A')
    if is_job_specific:
        url = f"{JENKINS_URL}/job/{endpoint}"
    else:
        url = f"{JENKINS_URL}/{endpoint}"
    
    auth = (JENKINS_USER, JENKINS_API_TOKEN)
    headers = kwargs.get('headers', {})
    
    # Add CSRF crumb for POST operations
    if method.upper() in ['POST', 'PUT', 'DELETE']:
        crumb = get_jenkins_crumb(context)
        if crumb:
            headers['Jenkins-Crumb'] = crumb
            logger.info(f"[{request_id}] Added CSRF crumb to {method} request")
    
    kwargs['headers'] = headers
    
    logger.info(f"[{request_id}] Making Jenkins API request: {method} {url}")
    try:
        response = requests.request(method, url, auth=auth, **kwargs)
        response.raise_for_status()
        logger.info(f"[{request_id}] Jenkins API request successful (Status: {response.status_code})")
        return response
    except requests.exceptions.RequestException as e:
        logger.error(f"[{request_id}] Jenkins API request failed: {e}")
        raise

# Initialize FastMCP
parser = argparse.ArgumentParser(description="Jenkins MCP Server", add_help=False)
parser.add_argument("--port", type=str, default=os.getenv("MCP_PORT", "8010"),
                    help="Port for the MCP server (default: 8010 or from MCP_PORT env var)")
parser.add_argument("--host", type=str, default=os.getenv("MCP_HOST", "0.0.0.0"),
                    help="Host for the MCP server (default: 0.0.0.0 or from MCP_HOST env var)")
args, unknown = parser.parse_known_args()

mcp = FastMCP("jenkins_server", port=args.port, host=args.host)

# --- Context Generation ---
def get_request_context() -> Dict[str, Any]:
    """Creates a context dictionary for a single request."""
    return {"request_id": str(uuid.uuid4())}

def create_job_not_found_error(job_name: str, operation: str) -> str:
    """Create helpful error message when job is not found."""
    suggestions = []
    
    # Add search_jobs suggestions
    suggestions.append(f"search_jobs('{job_name}')")
    if not '*' in job_name:
        suggestions.append(f"search_jobs('*{job_name}*')")
    
    # Add list_jobs suggestion
    suggestions.append("list_jobs(recursive=True)")
    
    # Add get_job_info with auto_search suggestion
    suggestions.append(f"get_job_info('{job_name}', auto_search=True)")
    
    error_msg = f"Job '{job_name}' not found for {operation}. Try these discovery tools:\n"
    for i, suggestion in enumerate(suggestions, 1):
        error_msg += f"  {i}. {suggestion}\n"
    
    return error_msg.strip()

# --- MCP Tools with Enhanced Logging and Context ---

@mcp.tool()
def trigger_job(job_name: str, params: Optional[Dict[str, Any]] = None) -> TriggerJobResponse:
    """
    Trigger a Jenkins job with optional parameters.
    Supports nested job paths like 'folder1/subfolder/jobname'.
    
    Args:
        job_name: Name or path of the Jenkins job (e.g., 'my-job' or 'folder1/my-job')
        params: Job parameters. For multiselect parameters, pass as a list.
    """
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Received request to trigger job: '{job_name}' with params: {params}")
    
    try:
        jenkins_params = params.get('args', {}).get('params', params) if params else None
        logger.info(f"[{context['request_id']}] Extracted Jenkins params: {jenkins_params}")

        processed_params = None
        
        # Check if this is a nested job path
        if '/' in job_name:
            # Handle nested job path
            if jenkins_params:
                processed_params = process_jenkins_parameters(jenkins_params, context)
                headers = {"Content-Type": "application/x-www-form-urlencoded"}
                encoded_params = urlencode(processed_params)
                logger.info(f"[{context['request_id']}] Triggering nested job '{job_name}' with processed params: {processed_params}")
                resp = jenkins_request_nested("POST", job_name, "buildWithParameters", context, data=encoded_params, headers=headers)
            else:
                logger.info(f"[{context['request_id']}] Triggering nested job '{job_name}' without parameters")
                resp = jenkins_request_nested("POST", job_name, "build", context)
        else:
            # Handle simple job name (legacy behavior)
            if jenkins_params:
                processed_params = process_jenkins_parameters(jenkins_params, context)
                build_url = f"{job_name}/buildWithParameters"
                headers = {"Content-Type": "application/x-www-form-urlencoded"}
                encoded_params = urlencode(processed_params)
                logger.info(f"[{context['request_id']}] Triggering job '{job_name}' with processed params: {processed_params}")
                resp = jenkins_request("POST", build_url, context, data=encoded_params, headers=headers)
            else:
                build_url = f"{job_name}/build"
                logger.info(f"[{context['request_id']}] Triggering job '{job_name}' without parameters")
                resp = jenkins_request("POST", build_url, context)

        queue_url = resp.headers.get("Location")
        logger.info(f"[{context['request_id']}] Job '{job_name}' triggered successfully. Queue URL: {queue_url}")
        
        return TriggerJobResponse(
            job_name=job_name, 
            status="Triggered", 
            queue_url=queue_url,
            processed_params=processed_params
        )

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            # Job not found - provide helpful suggestions
            helpful_error = create_job_not_found_error(job_name, "triggering")
            logger.error(f"[{context.get('request_id', 'N/A')}] {helpful_error}")
            raise ValueError(helpful_error)
        else:
            logger.error(f"[{context.get('request_id', 'N/A')}] Failed to trigger job '{job_name}': {e}")
            raise
    except Exception as e:
        logger.error(f"[{context.get('request_id', 'N/A')}] Failed to trigger job '{job_name}': {e}")
        raise

@mcp.tool()
def get_job_info(job_name: str, auto_search: bool = True) -> Dict[str, Any]:
    """
    Get detailed information about a Jenkins job including its parameters.
    Supports nested job paths and automatic search fallback.
    
    Args:
        job_name: Name or path of the Jenkins job
        auto_search: If True, perform pattern search when direct lookup fails
    
    Returns:
        JobInfoResponse with either direct job info or search results
    """
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Received request for job info: '{job_name}' (auto_search={auto_search})")
    
    try:
        # Try direct lookup first
        try:
            if '/' in job_name:
                resp = jenkins_request_nested("GET", job_name, "api/json", context)
            else:
                endpoint = f"{job_name}/api/json"
                resp = jenkins_request("GET", endpoint, context)
            
            data = resp.json()
            
            # Parse job parameters
            parameters = []
            param_prop = next((p for p in data.get("property", []) if p.get("_class") == "hudson.model.ParametersDefinitionProperty"), None)
            if param_prop:
                for param_def in param_prop.get("parameterDefinitions", []):
                    parameters.append(JobParameter(
                        name=param_def.get("name", ""),
                        type=param_def.get("type", "unknown"),
                        default_value=param_def.get("defaultParameterValue", {}).get("value"),
                        description=param_def.get("description", ""),
                        choices=param_def.get("choices")
                    ))
            
            last_build = data.get("lastBuild")
            last_build_number = last_build.get("number") if last_build else None
            
            job_info = JobInfo(
                name=job_name,
                description=data.get("description"),
                parameters=parameters,
                last_build_number=last_build_number,
                last_build_status=None
            )
            
            logger.info(f"[{context['request_id']}] Successfully retrieved direct job info for '{job_name}'. Found {len(parameters)} parameters.")
            
            return JobInfoResponse(
                success=True,
                job_info=job_info,
                message=f"Found job '{job_name}' directly"
            ).model_dump()
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404 and auto_search:
                # Job not found - try search fallback
                logger.info(f"[{context['request_id']}] Direct lookup failed, attempting search fallback for '{job_name}'")
                
                # Search for matching jobs
                all_items = _collect_jobs_recursive("", context, 10)
                jobs_only = [item for item in all_items if item.type == "job"]
                
                # Pattern matching
                matching_jobs = []
                for job in jobs_only:
                    if (fnmatch.fnmatch(job.name.lower(), job_name.lower()) or 
                        fnmatch.fnmatch(job.full_name.lower(), job_name.lower()) or
                        job_name.lower() in job.name.lower() or
                        job_name.lower() in job.full_name.lower()):
                        matching_jobs.append(job)
                
                search_results = [job.model_dump() for job in matching_jobs]
                
                if matching_jobs:
                    suggestions = [
                        f"Use exact path: get_job_info('{matching_jobs[0].full_name}')",
                        "Or try search_jobs() for more search options"
                    ]
                    
                    return JobInfoResponse(
                        success=False,
                        search_results=search_results,
                        message=f"Job '{job_name}' not found directly, but found {len(matching_jobs)} similar jobs",
                        suggestions=suggestions
                    ).model_dump()
                else:
                    suggestions = [
                        f"Try: search_jobs('*{job_name}*')",
                        "Or: list_jobs(recursive=True) to see all available jobs"
                    ]
                    
                    return JobInfoResponse(
                        success=False,
                        message=f"Job '{job_name}' not found and no similar jobs found",
                        suggestions=suggestions
                    ).model_dump()
            else:
                # Re-raise non-404 errors or when auto_search is disabled
                raise
                
    except Exception as e:
        logger.error(f"[{context.get('request_id', 'N/A')}] Failed to get job info for '{job_name}': {e}")
        raise

@mcp.tool()
def get_build_status(job_name: str, build_number: int) -> BuildStatusResponse:
    """Get the status of a specific build. Supports nested job paths."""
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Received request for build status: Job '{job_name}', Build #{build_number}")
    
    try:
        # Check if this is a nested job path
        if '/' in job_name:
            resp = jenkins_request_nested("GET", job_name, f"{build_number}/api/json", context)
        else:
            endpoint = f"{job_name}/{build_number}/api/json"
            resp = jenkins_request("GET", endpoint, context)
        
        data = resp.json()
        
        status = data.get("result", "BUILDING" if data.get("building") else "UNKNOWN")
        
        logger.info(f"[{context['request_id']}] Status for '{job_name}' #{build_number} is '{status}'")
        
        return BuildStatusResponse(
            job_name=job_name,
            build_number=build_number,
            status=status,
            timestamp=data.get("timestamp"),
            duration=data.get("duration"),
            url=data.get("url")
        )
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            # Job not found - provide helpful suggestions
            helpful_error = create_job_not_found_error(job_name, "getting build status")
            logger.error(f"[{context.get('request_id', 'N/A')}] {helpful_error}")
            raise ValueError(helpful_error)
        else:
            logger.error(f"[{context.get('request_id', 'N/A')}] Failed to get build status for '{job_name}' #{build_number}: {e}")
            raise
    except Exception as e:
        logger.error(f"[{context.get('request_id', 'N/A')}] Failed to get build status for '{job_name}' #{build_number}: {e}")
        raise

@mcp.tool()
def get_console_log(job_name: str, build_number: int, start: int = 0) -> ConsoleLogResponse:
    """
    Get console log for a specific build. Supports nested job paths.
    """
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Received request for console log: Job '{job_name}', Build #{build_number}, Start: {start}")
    
    try:
        # Check if this is a nested job path
        if '/' in job_name:
            resp = jenkins_request_nested("GET", job_name, f"{build_number}/logText/progressiveText", context, params={"start": start})
        else:
            endpoint = f"{job_name}/{build_number}/logText/progressiveText"
            resp = jenkins_request("GET", endpoint, context, params={"start": start})
        
        has_more = resp.headers.get("X-More-Data", "false").lower() == "true"
        log_size = int(resp.headers.get("X-Text-Size", 0))
        
        logger.info(f"[{context['request_id']}] Fetched console log for '{job_name}' #{build_number}. Size: {len(resp.text)} bytes. More available: {has_more}")
        
        return ConsoleLogResponse(log=resp.text, has_more=has_more, log_size=log_size)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            # Job not found - provide helpful suggestions
            helpful_error = create_job_not_found_error(job_name, "getting console log")
            logger.error(f"[{context.get('request_id', 'N/A')}] {helpful_error}")
            raise ValueError(helpful_error)
        else:
            logger.error(f"[{context.get('request_id', 'N/A')}] Failed to fetch console log for '{job_name}' #{build_number}: {e}")
            raise
    except Exception as e:
        logger.error(f"[{context.get('request_id', 'N/A')}] Failed to fetch console log for '{job_name}' #{build_number}: {e}")
        raise

@mcp.tool()
def list_jobs(recursive: bool = True, max_depth: int = 10, include_folders: bool = False) -> List[Dict[str, Any]]:
    """
    List Jenkins jobs with optional recursive traversal.
    
    Args:
        recursive: If True, recursively traverse folders (default: True)
        max_depth: Maximum depth to recurse when recursive=True (default: 10)
        include_folders: Whether to include folder items in results (default: False)
    
    Returns:
        List of jobs with metadata (name, full_name, type, url, description)
    """
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Received request to list jobs (recursive={recursive}, max_depth={max_depth}, include_folders={include_folders})")
    
    try:
        if recursive:
            # Use existing recursive collection function
            all_items = _collect_jobs_recursive("", context, max_depth)
            
            # Filter based on include_folders setting
            if include_folders:
                result_items = all_items
            else:
                result_items = [item for item in all_items if item.type == "job"]
            
            # Convert to dict format for JSON serialization
            result = [item.model_dump() for item in result_items]
            logger.info(f"[{context['request_id']}] Found {len(result)} items recursively (total with folders: {len(all_items)})")
            
        else:
            # Top-level only (legacy behavior)
            resp = jenkins_request("GET", "api/json", context, is_job_specific=False)
            jobs = resp.json().get("jobs", [])
            
            result = []
            for job in jobs:
                job_name = job.get("name", "")
                job_class = job.get("_class", "")
                item_type = "folder" if "folder" in job_class.lower() else "job"
                
                # Include based on type and include_folders setting
                if item_type == "job" or (item_type == "folder" and include_folders):
                    result.append({
                        "name": job_name,
                        "full_name": job_name,
                        "type": item_type,
                        "url": job.get("url", ""),
                        "description": job.get("description", "")
                    })
            
            logger.info(f"[{context['request_id']}] Found {len(result)} top-level items")
        
        return result
        
    except Exception as e:
        logger.error(f"[{context.get('request_id', 'N/A')}] Failed to list jobs: {e}")
        raise

def _collect_jobs_recursive(path: str, context: Dict[str, Any], max_depth: int = 10, current_depth: int = 0) -> List[JobTreeItem]:
    """Recursively collect all jobs from Jenkins folders."""
    request_id = context.get('request_id', 'N/A')
    
    if current_depth >= max_depth:
        logger.warning(f"[{request_id}] Max depth {max_depth} reached at path '{path}'")
        return []
    
    jobs = []
    
    try:
        if path:
            # For nested paths, use the nested request function
            endpoint = f"api/json"
            resp = jenkins_request_nested("GET", path, endpoint, context)
        else:
            # For root level
            resp = jenkins_request("GET", "api/json", context, is_job_specific=False)
        
        data = resp.json()
        items = data.get("jobs", [])
        
        for item in items:
            item_name = item.get("name", "")
            item_class = item.get("_class", "")
            item_url = item.get("url", "")
            item_description = item.get("description", "")
            
            # Build full path
            full_name = f"{path}/{item_name}" if path else item_name
            
            # Check if it's a folder
            if "folder" in item_class.lower():
                # Add folder to list
                jobs.append(JobTreeItem(
                    name=item_name,
                    full_name=full_name,
                    type="folder",
                    url=item_url,
                    description=item_description
                ))
                
                # Recursively collect jobs from this folder
                logger.info(f"[{request_id}] Exploring folder: {full_name} (depth {current_depth + 1})")
                sub_jobs = _collect_jobs_recursive(full_name, context, max_depth, current_depth + 1)
                jobs.extend(sub_jobs)
            else:
                # It's a job
                jobs.append(JobTreeItem(
                    name=item_name,
                    full_name=full_name,
                    type="job",
                    url=item_url,
                    description=item_description
                ))
        
        return jobs
        
    except Exception as e:
        logger.error(f"[{request_id}] Failed to collect jobs from path '{path}': {e}")
        return []


@mcp.tool()
def get_folder_info(folder_path: str) -> Dict[str, Any]:
    """
    Get information about a specific Jenkins folder.
    
    Args:
        folder_path: Path to the folder (e.g., 'folder1/subfolder')
    """
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Received request for folder info: '{folder_path}'")
    
    try:
        endpoint = "api/json"
        resp = jenkins_request_nested("GET", folder_path, endpoint, context)
        data = resp.json()
        
        # Separate jobs and folders
        jobs = []
        folders = []
        
        for item in data.get("jobs", []):
            item_name = item.get("name", "")
            item_class = item.get("_class", "")
            item_url = item.get("url", "")
            item_description = item.get("description", "")
            
            full_name = f"{folder_path}/{item_name}"
            
            tree_item = JobTreeItem(
                name=item_name,
                full_name=full_name,
                type="folder" if "folder" in item_class.lower() else "job",
                url=item_url,
                description=item_description
            )
            
            if "folder" in item_class.lower():
                folders.append(tree_item)
            else:
                jobs.append(tree_item)
        
        folder_info = FolderInfo(
            name=folder_path.split('/')[-1],
            full_name=folder_path,
            description=data.get("description", ""),
            jobs=jobs,
            folders=folders
        )
        
        logger.info(f"[{context['request_id']}] Folder '{folder_path}' contains {len(jobs)} jobs and {len(folders)} folders")
        return folder_info.model_dump()
        
    except Exception as e:
        logger.error(f"[{context.get('request_id', 'N/A')}] Failed to get folder info for '{folder_path}': {e}")
        raise

@mcp.tool()
def search_jobs(pattern: str, job_type: str = "job", max_depth: int = 10) -> List[Dict[str, Any]]:
    """
    Search for Jenkins jobs using pattern matching.
    
    Args:
        pattern: Pattern to match job names (supports wildcards like 'build*', '*test*', etc.)
        job_type: Filter by type - "job", "folder", or "all" (default: "job")
        max_depth: Maximum depth to search (default: 10)
    
    Returns:
        List of matching items with their full paths and metadata
    """
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Searching for items with pattern: '{pattern}' (type: {job_type}, max_depth: {max_depth})")
    
    try:
        # Get all items using existing recursive function
        all_items = _collect_jobs_recursive("", context, max_depth)
        
        # Filter by type
        if job_type == "job":
            filtered_items = [item for item in all_items if item.type == "job"]
        elif job_type == "folder":
            filtered_items = [item for item in all_items if item.type == "folder"]
        else:  # "all"
            filtered_items = all_items
        
        # Apply pattern matching
        matching_items = []
        for item in filtered_items:
            # Match against both name and full_name
            if (fnmatch.fnmatch(item.name.lower(), pattern.lower()) or 
                fnmatch.fnmatch(item.full_name.lower(), pattern.lower())):
                matching_items.append(item)
        
        # Convert to dict format for JSON serialization
        result = [item.model_dump() for item in matching_items]
        
        logger.info(f"[{context['request_id']}] Found {len(result)} items matching pattern '{pattern}'")
        return result
        
    except Exception as e:
        logger.error(f"[{context.get('request_id', 'N/A')}] Failed to search for items with pattern '{pattern}': {e}")
        raise

@mcp.tool()
def search_and_trigger(pattern: str, params: Optional[Dict[str, Any]] = None, max_depth: int = 10) -> Dict[str, Any]:
    """
    Search for a job by pattern and trigger it if exactly one match is found.
    
    Args:
        pattern: Pattern to match job names
        params: Job parameters for triggering
        max_depth: Maximum search depth
    
    Returns:
        Either trigger result or error with suggestions
    """
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Search and trigger with pattern: '{pattern}'")
    
    try:
        # Find matching jobs
        matches = search_jobs(pattern, "job", max_depth)
        
        if len(matches) == 0:
            return {
                "error": "No jobs found",
                "pattern": pattern,
                "suggestion": f"Try using search_jobs('{pattern}*') or search_jobs('*{pattern}*') for broader search"
            }
        elif len(matches) == 1:
            # Exactly one match - trigger it
            job_path = matches[0]["full_name"]
            logger.info(f"[{context['request_id']}] Found unique match: '{job_path}', triggering job")
            trigger_result = trigger_job(job_path, params)
            return {
                "success": True,
                "matched_job": matches[0],
                "trigger_result": trigger_result.model_dump()
            }
        else:
            # Multiple matches - return for disambiguation
            return {
                "error": "Multiple jobs match pattern",
                "pattern": pattern,
                "matches": matches,
                "suggestion": "Use a more specific pattern or call trigger_job with the exact path"
            }
            
    except Exception as e:
        logger.error(f"[{context.get('request_id', 'N/A')}] Failed search and trigger with pattern '{pattern}': {e}")
        raise

@mcp.tool()
def get_queue_info() -> List[Dict[str, Any]]:
    """Get information about queued builds."""
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Received request for queue info.")
    try:
        resp = jenkins_request("GET", "queue/api/json", context, is_job_specific=False)
        queue_data = resp.json().get("items", [])
        logger.info(f"[{context['request_id']}] Found {len(queue_data)} items in the queue.")
        return queue_data
    except Exception as e:
        logger.error(f"[{context.get('request_id', 'N/A')}] Failed to get queue info: {e}")
        raise

@mcp.tool()
def server_info() -> Dict[str, Any]:
    """Get Jenkins server information."""
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Received request for server info.")
    try:
        resp = jenkins_request("GET", "api/json", context, is_job_specific=False)
        data = resp.json()
        info = {
            "version": data.get("jenkinsVersion"),
            "url": JENKINS_URL
        }
        logger.info(f"[{context['request_id']}] Jenkins version: {info['version']}")
        return info
    except Exception as e:
        logger.error(f"[{context.get('request_id', 'N/A')}] Failed to fetch Jenkins info: {e}")
        raise

@mcp.tool()
def summarize_build_log(job_name: str, build_number: int) -> dict:
    """
    Summarizes the console log of a Jenkins build using a configured LLM prompt.
    (Note: This is a demonstration tool and does not execute a real LLM call.)
    """
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Received request to summarize log for '{job_name}' #{build_number}")
    try:
        log_response = get_console_log(job_name, build_number)
        prompt_template = LLM_RESOURCES["prompts"]["summarize_log"]
        prompt = prompt_template.format(log_text=log_response.log)
        sampling_config = LLM_RESOURCES["sampling_config"]
        
        placeholder_summary = f"LLM summary for '{job_name}' build #{build_number} would be generated here."
        logger.info(f"[{context['request_id']}] Successfully constructed prompt for summarization.")
        
        response_data = SummarizeBuildLogResponse(
            summary=placeholder_summary,
            prompt_used=prompt,
            sampling_config=sampling_config
        )
        
        return {"result": response_data.model_dump()}

    except Exception as e:
        logger.error(f"[{context.get('request_id', 'N/A')}] Failed to summarize build log for '{job_name}' #{build_number}: {e}")
        raise

@mcp.resource("status://health")
def get_health() -> HealthCheckResponse:
    """
    Performs a health check on the server and its connection to Jenkins.
    """
    try:
        # Verify connection to Jenkins by making a simple request to the base URL
        auth = (JENKINS_USER, JENKINS_API_TOKEN)
        response = requests.get(f"{JENKINS_URL}/api/json", auth=auth, timeout=5)
        response.raise_for_status()

        # Check if we get a valid response
        if "x-jenkins" not in response.headers:
            raise ValueError("Endpoint did not respond like a Jenkins instance.")

        logger.info("Health check successful: Connected to Jenkins.")
        return HealthCheckResponse(status="ok")

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthCheckResponse(status="error", details=f"Failed to connect to Jenkins: {str(e)}")

if __name__ == "__main__":
    try:
        logger.info(f"Starting Jenkins MCP server on port {args.port}")
        sys.argv = [sys.argv[0]] + unknown
        mcp.run(transport="streamable-http")
    except Exception as e:
        logger.exception("Fatal error in MCP server runtime:")
        sys.exit(1)

