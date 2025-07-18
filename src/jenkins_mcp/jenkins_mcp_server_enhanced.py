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
from urllib.parse import urlencode
import uuid
from fastapi import status
from fastapi.responses import JSONResponse

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

class SummarizeBuildLogResponse(BaseModel):
    summary: str
    prompt_used: str
    sampling_config: Dict[str, Union[float, int]]

class HealthCheckResponse(BaseModel):
    status: str
    details: Optional[str] = None

# Helper to make authenticated Jenkins requests
def jenkins_request(method, endpoint, context: Dict[str, Any], is_job_specific: bool = True, **kwargs):
    request_id = context.get('request_id', 'N/A')
    if is_job_specific:
        url = f"{JENKINS_URL}/job/{endpoint}"
    else:
        url = f"{JENKINS_URL}/{endpoint}"
    
    auth = (JENKINS_USER, JENKINS_API_TOKEN)
    
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
args, unknown = parser.parse_known_args()

mcp = FastMCP("jenkins_server", port=args.port)

# --- Context Generation ---
def get_request_context() -> Dict[str, Any]:
    """Creates a context dictionary for a single request."""
    return {"request_id": str(uuid.uuid4())}

# --- MCP Tools with Enhanced Logging and Context ---

@mcp.tool()
def trigger_job(job_name: str, params: Optional[Dict[str, Any]] = None) -> TriggerJobResponse:
    """
    Trigger a Jenkins job with optional parameters.
    
    Args:
        job_name: Name of the Jenkins job
        params: Job parameters. For multiselect parameters, pass as a list.
    """
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Received request to trigger job: '{job_name}' with params: {params}")
    
    try:
        jenkins_params = params.get('args', {}).get('params', params)
        logger.info(f"[{context['request_id']}] Extracted Jenkins params: {jenkins_params}")

        processed_params = None
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

    except Exception as e:
        logger.error(f"[{context.get('request_id', 'N/A')}] Failed to trigger job '{job_name}': {e}")
        raise

@mcp.tool()
def get_job_info(job_name: str) -> JobInfo:
    """
    Get detailed information about a Jenkins job including its parameters.
    """
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Received request for job info: '{job_name}'")
    
    try:
        endpoint = f"{job_name}/api/json"
        resp = jenkins_request("GET", endpoint, context)
        data = resp.json()
        
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
        
        logger.info(f"[{context['request_id']}] Successfully retrieved info for job '{job_name}'. Found {len(parameters)} parameters.")
        
        return JobInfo(
            name=job_name,
            description=data.get("description"),
            parameters=parameters,
            last_build_number=last_build_number,
            last_build_status=None  # Status requires a separate call, omitted for brevity
        )
        
    except Exception as e:
        logger.error(f"[{context.get('request_id', 'N/A')}] Failed to get job info for '{job_name}': {e}")
        raise

@mcp.tool()
def get_build_status(job_name: str, build_number: int) -> BuildStatusResponse:
    """Get the status of a specific build."""
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Received request for build status: Job '{job_name}', Build #{build_number}")
    
    try:
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
    except Exception as e:
        logger.error(f"[{context.get('request_id', 'N/A')}] Failed to get build status for '{job_name}' #{build_number}: {e}")
        raise

@mcp.tool()
def get_console_log(job_name: str, build_number: int, start: int = 0) -> ConsoleLogResponse:
    """
    Get console log for a specific build.
    """
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Received request for console log: Job '{job_name}', Build #{build_number}, Start: {start}")
    
    try:
        endpoint = f"{job_name}/{build_number}/logText/progressiveText"
        resp = jenkins_request("GET", endpoint, context, params={"start": start})
        
        has_more = resp.headers.get("X-More-Data", "false").lower() == "true"
        log_size = int(resp.headers.get("X-Text-Size", 0))
        
        logger.info(f"[{context['request_id']}] Fetched console log for '{job_name}' #{build_number}. Size: {len(resp.text)} bytes. More available: {has_more}")
        
        return ConsoleLogResponse(log=resp.text, has_more=has_more, log_size=log_size)
    except Exception as e:
        logger.error(f"[{context.get('request_id', 'N/A')}] Failed to fetch console log for '{job_name}' #{build_number}: {e}")
        raise

@mcp.tool()
def list_jobs() -> List[str]:
    """List all available Jenkins jobs."""
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Received request to list all jobs.")
    try:
        resp = jenkins_request("GET", "api/json", context, is_job_specific=False)
        jobs = resp.json().get("jobs", [])
        job_names = [job["name"] for job in jobs]
        logger.info(f"[{context['request_id']}] Found {len(job_names)} jobs.")
        return job_names
    except Exception as e:
        logger.error(f"[{context.get('request_id', 'N/A')}] Failed to list jobs: {e}")
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
        
        return {"result": response_data.dict()}

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
    logger.info(f"Starting Jenkins MCP server on port {args.port}")
    sys.argv = [sys.argv[0]] + unknown
    mcp.run(transport="streamable-http")
