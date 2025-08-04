# jenkins_mcp_server.py

import os
import sys
import argparse
import logging
from typing import Optional, Dict, List, Union, Any, Tuple, Set
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
import time
import random
import re
from functools import wraps
from cachetools import TTLCache, LRUCache, cached
from cachetools.keys import hashkey

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

# --- Configuration Constants ---
class JenkinsConfig:
    """
    Centralized configuration for Jenkins MCP Server.
    
    This class provides a single location for all configurable parameters,
    with environment variable support and sensible defaults.
    
    Environment Variables:
        JENKINS_URL: Jenkins server URL (default: http://localhost:8080)
        JENKINS_USER: Jenkins username for authentication
        JENKINS_API_TOKEN: Jenkins API token for authentication
        JENKINS_MAX_RETRIES: Maximum retry attempts (default: 3)
        JENKINS_RETRY_BASE_DELAY: Base delay between retries in seconds (default: 1.0)
        JENKINS_RETRY_MAX_DELAY: Maximum delay between retries in seconds (default: 60.0)
        JENKINS_RETRY_BACKOFF_MULTIPLIER: Backoff multiplier for exponential backoff (default: 2.0)
        JENKINS_DEFAULT_TIMEOUT: Default request timeout in seconds (default: 10)
        JENKINS_HEALTH_TIMEOUT: Health check timeout in seconds (default: 5)
        JENKINS_CRUMB_CACHE_MINUTES: CSRF crumb cache duration in minutes (default: 30)
        JENKINS_MAX_LOG_SIZE: Maximum log content size in characters (default: 1000)
        JENKINS_MAX_CONTENT_SIZE: Maximum content size in characters (default: 10000)
        JENKINS_MAX_ARTIFACT_SIZE_MB: Maximum artifact download size in MB (default: 50)
        JENKINS_DEFAULT_MAX_DEPTH: Default maximum folder traversal depth (default: 10)
        JENKINS_DEFAULT_MAX_BUILDS: Default maximum builds to search (default: 10)
        MCP_PORT: MCP server port (default: 8010)
        MCP_HOST: MCP server host (default: 0.0.0.0)
    """
    
    # Jenkins Connection
    URL = os.getenv("JENKINS_URL", "http://localhost:8080")
    USER = os.getenv("JENKINS_USER")
    API_TOKEN = os.getenv("JENKINS_API_TOKEN")
    
    # Retry Configuration
    MAX_RETRIES = int(os.getenv("JENKINS_MAX_RETRIES", "3"))
    BASE_DELAY = float(os.getenv("JENKINS_RETRY_BASE_DELAY", "1.0"))
    MAX_DELAY = float(os.getenv("JENKINS_RETRY_MAX_DELAY", "60.0"))
    BACKOFF_MULTIPLIER = float(os.getenv("JENKINS_RETRY_BACKOFF_MULTIPLIER", "2.0"))
    
    # Request Timeouts
    DEFAULT_TIMEOUT = int(os.getenv("JENKINS_DEFAULT_TIMEOUT", "10"))
    HEALTH_CHECK_TIMEOUT = int(os.getenv("JENKINS_HEALTH_TIMEOUT", "5"))
    
    # Cache Configuration
    CRUMB_CACHE_MINUTES = int(os.getenv("JENKINS_CRUMB_CACHE_MINUTES", "30"))
    
    # Performance Cache Settings
    CACHE_STATIC_TTL = int(os.getenv("JENKINS_CACHE_STATIC_TTL", "3600"))        # 1 hour for static data
    CACHE_SEMI_STATIC_TTL = int(os.getenv("JENKINS_CACHE_SEMI_STATIC_TTL", "300"))  # 5 minutes for semi-static
    CACHE_DYNAMIC_TTL = int(os.getenv("JENKINS_CACHE_DYNAMIC_TTL", "30"))        # 30 seconds for dynamic data
    CACHE_SHORT_TTL = int(os.getenv("JENKINS_CACHE_SHORT_TTL", "10"))            # 10 seconds for short-lived
    
    # Cache Size Limits
    CACHE_STATIC_SIZE = int(os.getenv("JENKINS_CACHE_STATIC_SIZE", "1000"))      # Static cache max items
    CACHE_SEMI_STATIC_SIZE = int(os.getenv("JENKINS_CACHE_SEMI_STATIC_SIZE", "500"))  # Semi-static cache max items
    CACHE_DYNAMIC_SIZE = int(os.getenv("JENKINS_CACHE_DYNAMIC_SIZE", "200"))     # Dynamic cache max items
    CACHE_PERMANENT_SIZE = int(os.getenv("JENKINS_CACHE_PERMANENT_SIZE", "2000")) # Permanent cache max items
    CACHE_SHORT_SIZE = int(os.getenv("JENKINS_CACHE_SHORT_SIZE", "100"))         # Short-lived cache max items
    
    # Content Limits
    MAX_LOG_SIZE = int(os.getenv("JENKINS_MAX_LOG_SIZE", "1000"))
    MAX_CONTENT_SIZE = int(os.getenv("JENKINS_MAX_CONTENT_SIZE", "10000"))
    DEFAULT_MAX_ARTIFACT_SIZE_MB = int(os.getenv("JENKINS_MAX_ARTIFACT_SIZE_MB", "50"))
    
    # Search and Pagination Defaults
    DEFAULT_MAX_DEPTH = int(os.getenv("JENKINS_DEFAULT_MAX_DEPTH", "10"))
    DEFAULT_MAX_BUILDS = int(os.getenv("JENKINS_DEFAULT_MAX_BUILDS", "10"))
    
    # Server Configuration
    DEFAULT_PORT = os.getenv("MCP_PORT", "8010")
    DEFAULT_HOST = os.getenv("MCP_HOST", "0.0.0.0")

# Retryable HTTP status codes and exceptions
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout, 
    requests.exceptions.ConnectTimeout,
    requests.exceptions.ReadTimeout
)

# Legacy constants for backward compatibility
DEFAULT_MAX_RETRIES = JenkinsConfig.MAX_RETRIES
DEFAULT_BASE_DELAY = JenkinsConfig.BASE_DELAY
DEFAULT_MAX_DELAY = JenkinsConfig.MAX_DELAY
DEFAULT_BACKOFF_MULTIPLIER = JenkinsConfig.BACKOFF_MULTIPLIER

# --- Standardized Error Handling ---
class JenkinsError(Exception):
    """Base exception for Jenkins MCP operations."""
    
    def __init__(self, message: str, suggestion: str = None, details: Any = None):
        super().__init__(message)
        self.message = message
        self.suggestion = suggestion
        self.details = details

class JenkinsConnectionError(JenkinsError):
    """Raised when Jenkins server connection fails."""
    pass

class JenkinsNotFoundError(JenkinsError):
    """Raised when Jenkins resource is not found."""
    pass

class JenkinsAuthenticationError(JenkinsError):
    """Raised when Jenkins authentication fails."""
    pass

class JenkinsValidationError(JenkinsError):
    """Raised when request validation fails."""
    pass

def create_error_response(error: Union[Exception, JenkinsError], 
                         context: Dict[str, Any] = None,
                         operation: str = "operation") -> Dict[str, Any]:
    """
    Create standardized error response format.
    
    Args:
        error: The exception that occurred
        context: Request context for logging
        operation: Description of the operation that failed
    
    Returns:
        Standardized error response dictionary
    """
    request_id = context.get('request_id', 'N/A') if context else 'N/A'
    
    if isinstance(error, JenkinsError):
        response = {
            "error": error.message,
            "operation": operation
        }
        if error.suggestion:
            response["suggestion"] = error.suggestion
        if error.details:
            response["details"] = error.details
    elif isinstance(error, requests.exceptions.HTTPError):
        status_code = error.response.status_code if error.response else "Unknown"
        
        if status_code == 404:
            response = {
                "error": f"Resource not found during {operation}",
                "suggestion": "Verify the resource name and ensure it exists in Jenkins",
                "http_status": status_code
            }
        elif status_code == 401:
            response = {
                "error": f"Authentication failed during {operation}",
                "suggestion": "Check Jenkins credentials (JENKINS_USER and JENKINS_API_TOKEN)",
                "http_status": status_code
            }
        elif status_code == 403:
            response = {
                "error": f"Permission denied during {operation}",
                "suggestion": "Ensure your Jenkins user has the required permissions",
                "http_status": status_code
            }
        elif status_code in RETRYABLE_STATUS_CODES:
            response = {
                "error": f"Server error during {operation} (HTTP {status_code})",
                "suggestion": "The request failed due to server issues. It will be retried automatically.",
                "http_status": status_code
            }
        else:
            response = {
                "error": f"HTTP error during {operation} (HTTP {status_code})",
                "suggestion": "Check Jenkins server connectivity and request parameters",
                "http_status": status_code
            }
    elif isinstance(error, requests.exceptions.ConnectionError):
        response = {
            "error": f"Connection failed during {operation}",
            "suggestion": f"Check Jenkins server URL ({JenkinsConfig.URL}) and network connectivity"
        }
    elif isinstance(error, requests.exceptions.Timeout):
        response = {
            "error": f"Request timeout during {operation}",
            "suggestion": f"Jenkins server is slow to respond. Consider increasing timeout values."
        }
    else:
        response = {
            "error": f"Unexpected error during {operation}: {str(error)}",
            "suggestion": "Check server logs for more details"
        }
    
    # Log the error
    logger.error(f"[{request_id}] {operation} failed: {response['error']}")
    if 'suggestion' in response:
        logger.info(f"[{request_id}] Suggestion: {response['suggestion']}")
    
    return response

def handle_jenkins_request_error(error: Exception, 
                                context: Dict[str, Any],
                                operation: str,
                                resource_name: str = None) -> Dict[str, Any]:
    """
    Handle common Jenkins request errors with context-specific suggestions.
    
    Args:
        error: The exception that occurred
        context: Request context
        operation: Description of the operation
        resource_name: Name of the resource being accessed (job, build, etc.)
    
    Returns:
        Standardized error response
    """
    if isinstance(error, requests.exceptions.HTTPError) and error.response.status_code == 404:
        if resource_name:
            if "build" in operation.lower():
                suggestion = f"Verify the job name and build number. Use get_job_info('{resource_name}') to see available builds."
            elif "job" in operation.lower():
                suggestion = f"Job '{resource_name}' not found. Use list_jobs() or search_jobs('{resource_name}') to find available jobs."
            else:
                suggestion = f"Resource '{resource_name}' not found. Verify the name and check if it exists in Jenkins."
        else:
            suggestion = "Verify the resource name and ensure it exists in Jenkins."
        
        return create_error_response(
            JenkinsNotFoundError(f"Resource not found during {operation}", suggestion),
            context, 
            operation
        )
    
    return create_error_response(error, context, operation)

def with_retry(max_retries: int = DEFAULT_MAX_RETRIES, 
               base_delay: float = DEFAULT_BASE_DELAY,
               max_delay: float = DEFAULT_MAX_DELAY,
               backoff_multiplier: float = DEFAULT_BACKOFF_MULTIPLIER,
               retryable_status_codes: set = None,
               retryable_exceptions: tuple = None):
    """
    Decorator that adds exponential backoff retry logic to HTTP requests.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds for first retry
        max_delay: Maximum delay in seconds between retries
        backoff_multiplier: Multiplier for exponential backoff
        retryable_status_codes: HTTP status codes that should trigger retries
        retryable_exceptions: Exception types that should trigger retries
    """
    if retryable_status_codes is None:
        retryable_status_codes = RETRYABLE_STATUS_CODES
    if retryable_exceptions is None:
        retryable_exceptions = RETRYABLE_EXCEPTIONS
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            context = args[2] if len(args) >= 3 and isinstance(args[2], dict) else {'request_id': 'N/A'}
            request_id = context.get('request_id', 'N/A')
            
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    response = func(*args, **kwargs)
                    
                    # If we get here, the request succeeded (no exception)
                    if attempt > 0:
                        logger.info(f"[{request_id}] Request succeeded on attempt {attempt + 1}")
                    return response
                    
                except requests.exceptions.HTTPError as e:
                    # Check if this HTTP error is retryable
                    if (hasattr(e, 'response') and 
                        e.response is not None and 
                        e.response.status_code in retryable_status_codes):
                        
                        last_exception = e
                        if attempt < max_retries:
                            delay = min(base_delay * (backoff_multiplier ** attempt), max_delay)
                            # Add jitter to prevent thundering herd
                            jitter = random.uniform(0.1, 0.9) * delay
                            total_delay = delay + jitter
                            
                            logger.warning(f"[{request_id}] HTTP {e.response.status_code} error on attempt {attempt + 1}, "
                                         f"retrying in {total_delay:.2f}s...")
                            time.sleep(total_delay)
                            continue
                    
                    # Non-retryable HTTP error, re-raise immediately
                    raise
                    
                except retryable_exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = min(base_delay * (backoff_multiplier ** attempt), max_delay)
                        jitter = random.uniform(0.1, 0.9) * delay
                        total_delay = delay + jitter
                        
                        logger.warning(f"[{request_id}] Network error on attempt {attempt + 1}: {str(e)}, "
                                     f"retrying in {total_delay:.2f}s...")
                        time.sleep(total_delay)
                        continue
                    
                except Exception as e:
                    # Non-retryable exception, re-raise immediately
                    raise
            
            # If we get here, all retries have been exhausted
            logger.error(f"[{request_id}] All {max_retries} retry attempts failed")
            raise last_exception
        
        return wrapper
    return decorator

# Validate Jenkins configuration
if not JenkinsConfig.USER or not JenkinsConfig.API_TOKEN:
    logger.error("Missing Jenkins credentials. Please set JENKINS_USER and JENKINS_API_TOKEN.")
    sys.exit(1)

# --- Common Utilities ---
def get_jenkins_auth() -> Tuple[str, str]:
    """
    Get Jenkins authentication tuple for requests.
    
    Returns:
        Tuple of (username, api_token)
    """
    return (JenkinsConfig.USER, JenkinsConfig.API_TOKEN)

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

# --- Comprehensive Caching System ---

class JenkinsCacheManager:
    """
    Comprehensive caching system for Jenkins MCP Server.
    
    Provides multiple cache types with different TTL strategies:
    - Static Cache (1 hour): Server info, job configurations, job parameters
    - Semi-Static Cache (5 minutes): Job lists, queue info
    - Dynamic Cache (30 seconds): Build statuses for running builds
    - Permanent Cache (No TTL): Completed build results, artifacts lists
    - Short-lived Cache (10 seconds): Console logs, pipeline stages for active builds
    
    Thread-safe implementation with configurable sizes and TTLs.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern for cache manager."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(JenkinsCacheManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize cache manager with thread-safe caches."""
        if self._initialized:
            return
            
        # Static data cache (1 hour TTL)
        self.static_cache = TTLCache(
            maxsize=JenkinsConfig.CACHE_STATIC_SIZE,
            ttl=JenkinsConfig.CACHE_STATIC_TTL
        )
        
        # Semi-static data cache (5 minutes TTL)
        self.semi_static_cache = TTLCache(
            maxsize=JenkinsConfig.CACHE_SEMI_STATIC_SIZE,
            ttl=JenkinsConfig.CACHE_SEMI_STATIC_TTL
        )
        
        # Dynamic data cache (30 seconds TTL)
        self.dynamic_cache = TTLCache(
            maxsize=JenkinsConfig.CACHE_DYNAMIC_SIZE,
            ttl=JenkinsConfig.CACHE_DYNAMIC_TTL
        )
        
        # Permanent cache for completed builds (LRU, no TTL)
        self.permanent_cache = LRUCache(
            maxsize=JenkinsConfig.CACHE_PERMANENT_SIZE
        )
        
        # Short-lived cache (10 seconds TTL)
        self.short_cache = TTLCache(
            maxsize=JenkinsConfig.CACHE_SHORT_SIZE,
            ttl=JenkinsConfig.CACHE_SHORT_TTL
        )
        
        # Cache statistics
        self.stats = {
            'hits': 0,
            'misses': 0,
            'invalidations': 0
        }
        
        self._initialized = True
        logger.info("Jenkins Cache Manager initialized with multi-tier caching strategy")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get comprehensive cache statistics."""
        return {
            'stats': self.stats.copy(),
            'cache_info': {
                'static': {
                    'size': len(self.static_cache),
                    'maxsize': self.static_cache.maxsize,
                    'ttl': JenkinsConfig.CACHE_STATIC_TTL
                },
                'semi_static': {
                    'size': len(self.semi_static_cache),
                    'maxsize': self.semi_static_cache.maxsize,
                    'ttl': JenkinsConfig.CACHE_SEMI_STATIC_TTL
                },
                'dynamic': {
                    'size': len(self.dynamic_cache),
                    'maxsize': self.dynamic_cache.maxsize,
                    'ttl': JenkinsConfig.CACHE_DYNAMIC_TTL
                },
                'permanent': {
                    'size': len(self.permanent_cache),
                    'maxsize': self.permanent_cache.maxsize,
                    'ttl': 'Never'
                },
                'short': {
                    'size': len(self.short_cache),
                    'maxsize': self.short_cache.maxsize,
                    'ttl': JenkinsConfig.CACHE_SHORT_TTL
                }
            }
        }
    
    def clear_all_caches(self):
        """Clear all caches."""
        with self._lock:
            self.static_cache.clear()
            self.semi_static_cache.clear()
            self.dynamic_cache.clear()
            self.permanent_cache.clear()
            self.short_cache.clear()
            self.stats['invalidations'] += 1
            logger.info("All caches cleared")
    
    def invalidate_job_caches(self, job_name: str):
        """Invalidate caches related to a specific job."""
        with self._lock:
            # Remove job-specific entries from caches
            keys_to_remove = []
            
            for cache in [self.static_cache, self.semi_static_cache, self.dynamic_cache, self.short_cache]:
                for key in list(cache.keys()):
                    if isinstance(key, tuple) and len(key) > 0 and str(key[0]) == job_name:
                        keys_to_remove.append((cache, key))
            
            for cache, key in keys_to_remove:
                try:
                    del cache[key]
                except KeyError:
                    pass
            
            self.stats['invalidations'] += 1
            logger.info(f"Invalidated caches for job: {job_name}")
    
    def get_cache_for_type(self, cache_type: str):
        """Get the appropriate cache based on data type."""
        cache_map = {
            'static': self.static_cache,
            'semi_static': self.semi_static_cache,
            'dynamic': self.dynamic_cache,
            'permanent': self.permanent_cache,
            'short': self.short_cache
        }
        return cache_map.get(cache_type)

# Global cache manager instance
cache_manager = JenkinsCacheManager()

def cached_request(cache_type: str = 'dynamic', key_func=None):
    """
    Decorator for caching API requests with different cache strategies.
    
    Args:
        cache_type: Type of cache to use ('static', 'semi_static', 'dynamic', 'permanent', 'short')
        key_func: Custom function to generate cache key (defaults to function name + args)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            if key_func:
                key = key_func(*args, **kwargs)
            else:
                key = hashkey(func.__name__, *args, **tuple(sorted(kwargs.items())))
            
            # Get appropriate cache
            cache = cache_manager.get_cache_for_type(cache_type)
            if cache is None:
                # No caching, execute function directly
                return func(*args, **kwargs)
            
            # Try to get from cache
            try:
                result = cache[key]
                cache_manager.stats['hits'] += 1
                logger.debug(f"Cache hit for {func.__name__} with key {key}")
                return result
            except KeyError:
                # Cache miss, execute function and cache result
                result = func(*args, **kwargs)
                cache[key] = result
                cache_manager.stats['misses'] += 1
                logger.debug(f"Cache miss for {func.__name__} with key {key}, result cached")
                return result
        
        return wrapper
    return decorator

def smart_build_cache(func):
    """
    Smart caching decorator for build status that uses different cache strategies
    based on whether the build is completed or still running.
    """
    @wraps(func)
    def wrapper(job_name: str, build_number: int):
        # Generate cache key
        key = f"build_status_{job_name}_{build_number}"
        
        # First check permanent cache for completed builds
        try:
            result = cache_manager.permanent_cache[key]
            # If it's in permanent cache, it's a completed build
            if result.status not in ['BUILDING', 'PENDING', 'UNKNOWN']:
                cache_manager.stats['hits'] += 1
                logger.debug(f"Permanent cache hit for {func.__name__} with key {key}")
                return result
        except KeyError:
            pass
        
        # Check dynamic cache for running builds
        try:
            result = cache_manager.dynamic_cache[key]
            cache_manager.stats['hits'] += 1
            logger.debug(f"Dynamic cache hit for {func.__name__} with key {key}")
            
            # If build completed, move to permanent cache
            if result.status not in ['BUILDING', 'PENDING', 'UNKNOWN']:
                cache_manager.permanent_cache[key] = result
                # Remove from dynamic cache
                try:
                    del cache_manager.dynamic_cache[key]
                except KeyError:
                    pass
            
            return result
        except KeyError:
            pass
        
        # Cache miss, execute function
        result = func(job_name, build_number)
        cache_manager.stats['misses'] += 1
        
        # Cache based on build status
        if result.status in ['BUILDING', 'PENDING', 'UNKNOWN']:
            # Running build - use dynamic cache
            cache_manager.dynamic_cache[key] = result
            logger.debug(f"Cached running build in dynamic cache: {key}")
        else:
            # Completed build - use permanent cache
            cache_manager.permanent_cache[key] = result
            logger.debug(f"Cached completed build in permanent cache: {key}")
        
        return result
    
    return wrapper

def smart_pipeline_cache(func):
    """
    Smart caching decorator for pipeline status that caches based on pipeline completion status.
    """
    @wraps(func)
    def wrapper(job_name: str, build_number: int):
        # Generate cache key
        key = f"pipeline_status_{job_name}_{build_number}"
        
        # First check permanent cache for completed pipelines
        try:
            result = cache_manager.permanent_cache[key]
            # Check if all stages are completed
            if result.get('status') in ['SUCCESS', 'FAILED', 'ABORTED', 'UNSTABLE']:
                cache_manager.stats['hits'] += 1
                logger.debug(f"Permanent cache hit for pipeline {key}")
                return result
        except KeyError:
            pass
        
        # Check dynamic cache for running pipelines
        try:
            result = cache_manager.dynamic_cache[key]
            cache_manager.stats['hits'] += 1
            logger.debug(f"Dynamic cache hit for pipeline {key}")
            
            # If pipeline completed, move to permanent cache
            if result.get('status') in ['SUCCESS', 'FAILED', 'ABORTED', 'UNSTABLE']:
                cache_manager.permanent_cache[key] = result
                try:
                    del cache_manager.dynamic_cache[key]
                except KeyError:
                    pass
            
            return result
        except KeyError:
            pass
        
        # Cache miss, execute function
        result = func(job_name, build_number)
        cache_manager.stats['misses'] += 1
        
        # Cache based on pipeline status
        if result.get('status') in ['SUCCESS', 'FAILED', 'ABORTED', 'UNSTABLE']:
            # Completed pipeline - use permanent cache
            cache_manager.permanent_cache[key] = result
            logger.debug(f"Cached completed pipeline in permanent cache: {key}")
        else:
            # Running pipeline - use dynamic cache
            cache_manager.dynamic_cache[key] = result
            logger.debug(f"Cached running pipeline in dynamic cache: {key}")
        
        return result
    
    return wrapper


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

class PipelineStage(BaseModel):
    id: str
    name: str
    status: str  # SUCCESS, FAILED, IN_PROGRESS, ABORTED, UNSTABLE
    start_time: Optional[int] = None  # Unix timestamp in milliseconds
    duration: Optional[int] = None   # Duration in milliseconds
    logs: Optional[str] = None       # Stage logs if available

class PipelineStageStatus(BaseModel):
    job_name: str
    build_number: int
    pipeline_status: str  # Overall pipeline status
    stages: List[PipelineStage] = []
    total_duration: Optional[int] = None
    estimated_duration: Optional[int] = None

class BuildArtifact(BaseModel):
    filename: str
    display_path: str
    relative_path: str
    size: Optional[int] = None  # Size in bytes
    timestamp: Optional[int] = None  # Unix timestamp in milliseconds
    download_url: str

class ArtifactListResponse(BaseModel):
    job_name: str
    build_number: int
    artifacts: List[BuildArtifact] = []
    total_artifacts: int
    total_size: Optional[int] = None  # Total size in bytes

class BatchJobOperation(BaseModel):
    job_name: str
    params: Optional[Dict[str, Any]] = None
    priority: int = 1  # 1 = highest, 10 = lowest
    
class BatchJobResult(BaseModel):
    job_name: str
    success: bool
    queue_url: Optional[str] = None
    build_number: Optional[int] = None
    error: Optional[str] = None
    execution_time: Optional[float] = None  # Time taken in seconds
    timestamp: Optional[int] = None  # Unix timestamp

class BatchOperationResponse(BaseModel):
    operation_id: str
    total_jobs: int
    successful: int
    failed: int
    skipped: int
    results: List[BatchJobResult] = []
    total_execution_time: Optional[float] = None
    started_at: Optional[int] = None
    completed_at: Optional[int] = None

class BatchMonitoringResponse(BaseModel):
    operation_id: str
    jobs_status: List[Dict[str, Any]] = []
    overall_status: str  # "running", "completed", "failed", "partial"
    progress_percentage: float
    estimated_completion: Optional[int] = None

# CSRF Crumb token management
@with_retry(max_retries=2)  # Fewer retries for crumb requests since they're less critical
def _fetch_crumb_token(context: Dict[str, Any]):
    """Fetch a new CSRF crumb token from Jenkins."""
    request_id = context.get('request_id', 'N/A')
    logger.info(f"[{request_id}] Fetching new CSRF crumb token")
    
    url = f"{JenkinsConfig.URL}/crumbIssuer/api/json"
    auth = get_jenkins_auth()
    response = requests.get(url, auth=auth, timeout=JenkinsConfig.DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response

def get_jenkins_crumb(context: Dict[str, Any]) -> Optional[str]:
    """Get Jenkins CSRF crumb token for POST operations."""
    request_id = context.get('request_id', 'N/A')
    
    with _crumb_cache["lock"]:
        # Check if we have a valid cached crumb
        if (_crumb_cache["token"] and _crumb_cache["expires"] and 
            datetime.now() < _crumb_cache["expires"]):
            logger.info(f"[{request_id}] Using cached crumb token")
            return _crumb_cache["token"]
        
        # Fetch new crumb with retry logic
        try:
            response = _fetch_crumb_token(context)
            crumb_data = response.json()
            crumb_token = crumb_data.get("crumb")
            
            if crumb_token:
                # Cache crumb for configured minutes
                _crumb_cache["token"] = crumb_token
                _crumb_cache["expires"] = datetime.now() + timedelta(minutes=JenkinsConfig.CRUMB_CACHE_MINUTES)
                logger.info(f"[{request_id}] Successfully fetched and cached new crumb token")
                return crumb_token
            else:
                logger.warning(f"[{request_id}] No crumb token in response")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.warning(f"[{request_id}] Failed to fetch crumb token: {e}")
            return None

# Helper to make Jenkins requests for nested job paths
@with_retry()
def jenkins_request_nested(method, job_path, endpoint_suffix, context: Dict[str, Any], **kwargs):
    """Make Jenkins request handling nested job paths like 'folder1/subfolder/jobname'."""
    request_id = context.get('request_id', 'N/A')
    
    # URL encode each path segment
    path_parts = job_path.split('/')
    encoded_parts = [quote(part, safe='') for part in path_parts]
    encoded_path = '/job/'.join(encoded_parts)
    
    url = f"{JenkinsConfig.URL}/job/{encoded_path}/{endpoint_suffix}"
    
    auth = get_jenkins_auth()
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
@with_retry()
def jenkins_request(method, endpoint, context: Dict[str, Any], is_job_specific: bool = True, **kwargs):
    request_id = context.get('request_id', 'N/A')
    if is_job_specific:
        url = f"{JenkinsConfig.URL}/job/{endpoint}"
    else:
        url = f"{JenkinsConfig.URL}/{endpoint}"
    
    auth = get_jenkins_auth()
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
parser.add_argument("--port", type=str, default=JenkinsConfig.DEFAULT_PORT,
                    help=f"Port for the MCP server (default: {JenkinsConfig.DEFAULT_PORT} or from MCP_PORT env var)")
parser.add_argument("--host", type=str, default=JenkinsConfig.DEFAULT_HOST,
                    help=f"Host for the MCP server (default: {JenkinsConfig.DEFAULT_HOST} or from MCP_HOST env var)")
args, unknown = parser.parse_known_args()

mcp = FastMCP("jenkins_server", port=args.port, host=args.host)

# --- Context Generation ---
def get_request_context() -> Dict[str, str]:
    """
    Creates a context dictionary for a single request.
    
    Returns:
        Dict containing a unique request ID for logging and tracing
    """
    return {"request_id": str(uuid.uuid4())}

def create_job_not_found_error(job_name: str, operation: str) -> str:
    """
    Create helpful error message when job is not found.
    
    Args:
        job_name: Name of the job that was not found
        operation: Description of the operation that failed
        
    Returns:
        Formatted error message with helpful suggestions
    """
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
        
        # Invalidate relevant caches since job state has changed
        cache_manager.invalidate_job_caches(job_name)
        logger.debug(f"[{context['request_id']}] Invalidated caches for triggered job: {job_name}")
        
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
@cached_request(cache_type='static', key_func=lambda job_name, auto_search=True: f"job_info_{job_name}_{auto_search}")
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
@smart_build_cache
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

def _get_enhanced_job_info(job_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Get enhanced job information for filtering purposes."""
    try:
        resp = jenkins_request_nested("GET", job_name, "api/json", context)
        job_data = resp.json()
        
        # Extract key information for filtering
        enhanced_info = {
            "buildable": job_data.get("buildable", True),
            "disabled": not job_data.get("buildable", True),
            "in_queue": job_data.get("inQueue", False),
            "building": len(job_data.get("builds", [])) > 0 and any(
                build.get("building", False) for build in job_data.get("builds", [])[:5]
            ),
            "last_build": job_data.get("lastBuild"),
            "last_successful_build": job_data.get("lastSuccessfulBuild"),
            "last_failed_build": job_data.get("lastFailedBuild"),
            "last_unstable_build": job_data.get("lastUnstableBuild"),
        }
        
        # Get last build result if available
        if enhanced_info["last_build"]:
            try:
                last_build_resp = jenkins_request_nested("GET", job_name, f"{enhanced_info['last_build']['number']}/api/json", context)
                last_build_data = last_build_resp.json()
                enhanced_info["last_build_result"] = last_build_data.get("result", "UNKNOWN")
                enhanced_info["last_build_timestamp"] = last_build_data.get("timestamp", 0)
                enhanced_info["last_build_duration"] = last_build_data.get("duration", 0)
            except Exception:
                enhanced_info["last_build_result"] = "UNKNOWN"
                enhanced_info["last_build_timestamp"] = 0
        else:
            enhanced_info["last_build_result"] = "NOT_BUILT"
            enhanced_info["last_build_timestamp"] = 0
        
        return enhanced_info
        
    except Exception as e:
        # Return minimal info if we can't get enhanced details
        return {
            "buildable": True,
            "disabled": False,
            "in_queue": False,
            "building": False,
            "last_build_result": "UNKNOWN",
            "last_build_timestamp": 0
        }

def _job_matches_filters(job_dict: Dict[str, Any], 
                        status_filter: Optional[str],
                        last_build_result: Optional[str],
                        days_since_last_build: Optional[int],
                        enabled_only: Optional[bool]) -> bool:
    """Check if a job matches the specified filters."""
    
    # Status filter
    if status_filter:
        current_status = "idle"  # default
        
        if job_dict.get("disabled", False):
            current_status = "disabled"
        elif job_dict.get("building", False):
            current_status = "building"
        elif job_dict.get("in_queue", False):
            current_status = "queued"
        else:
            current_status = "idle"
        
        if status_filter.lower() != current_status:
            return False
    
    # Last build result filter
    if last_build_result:
        job_result = job_dict.get("last_build_result", "UNKNOWN")
        if last_build_result.upper() != job_result.upper():
            return False
    
    # Days since last build filter
    if days_since_last_build is not None:
        last_build_timestamp = job_dict.get("last_build_timestamp", 0)
        if last_build_timestamp == 0:
            return False  # No build found
        
        # Convert timestamp from milliseconds to seconds
        last_build_time = datetime.fromtimestamp(last_build_timestamp / 1000)
        days_ago = (datetime.now() - last_build_time).days
        
        if days_ago > days_since_last_build:
            return False
    
    # Enabled/disabled filter
    if enabled_only is not None:
        is_disabled = job_dict.get("disabled", False)
        if enabled_only and is_disabled:
            return False
        if not enabled_only and not is_disabled:
            return False
    
    return True

@mcp.tool()
@cached_request(cache_type='semi_static', key_func=lambda recursive=True, max_depth=JenkinsConfig.DEFAULT_MAX_DEPTH, include_folders=False, status_filter=None, last_build_result=None, days_since_last_build=None, enabled_only=None: f"list_jobs_{recursive}_{max_depth}_{include_folders}_{status_filter}_{last_build_result}_{days_since_last_build}_{enabled_only}")
def list_jobs(recursive: bool = True, 
              max_depth: int = JenkinsConfig.DEFAULT_MAX_DEPTH, 
              include_folders: bool = False,
              status_filter: Optional[str] = None,
              last_build_result: Optional[str] = None,
              days_since_last_build: Optional[int] = None,
              enabled_only: Optional[bool] = None) -> List[Dict[str, Any]]:
    """
    List Jenkins jobs with optional recursive traversal and advanced filtering.
    
    Args:
        recursive: If True, recursively traverse folders (default: True)
        max_depth: Maximum depth to recurse when recursive=True (default: 10)
        include_folders: Whether to include folder items in results (default: False)
        status_filter: Filter by job status: "building", "queued", "idle", "disabled" (optional)
        last_build_result: Filter by last build result: "SUCCESS", "FAILURE", "UNSTABLE", "ABORTED", "NOT_BUILT" (optional)
        days_since_last_build: Only include jobs built within the last N days (optional)
        enabled_only: If True, only include enabled jobs; if False, only disabled jobs (optional)
    
    Returns:
        List of jobs with metadata including build status and timestamps
    """
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Received request to list jobs with filters: recursive={recursive}, status_filter={status_filter}, last_build_result={last_build_result}")
    
    try:
        if recursive:
            # Use existing recursive collection function
            all_items = _collect_jobs_recursive("", context, max_depth)
            
            # Filter based on include_folders setting
            if include_folders:
                result_items = all_items
            else:
                result_items = [item for item in all_items if item.type == "job"]
            
            # Convert to dict format for JSON serialization and apply advanced filtering
            result = []
            for item in result_items:
                job_dict = item.model_dump()
                
                # For jobs, fetch additional details if filters are specified
                if item.type == "job" and (status_filter or last_build_result or days_since_last_build is not None or enabled_only is not None):
                    try:
                        enhanced_job = _get_enhanced_job_info(item.full_name, context)
                        job_dict.update(enhanced_job)
                        
                        # Apply filters
                        if not _job_matches_filters(job_dict, status_filter, last_build_result, days_since_last_build, enabled_only):
                            continue
                    except Exception as e:
                        logger.debug(f"[{context['request_id']}] Could not get enhanced info for job {item.full_name}: {e}")
                        # If we can't get enhanced info and filters are applied, skip the job
                        if status_filter or last_build_result or days_since_last_build is not None or enabled_only is not None:
                            continue
                
                result.append(job_dict)
            
            logger.info(f"[{context['request_id']}] Found {len(result)} items after filtering (total before filtering: {len(result_items)})")
            
        else:
            # Top-level only with advanced filtering
            resp = jenkins_request("GET", "api/json", context, is_job_specific=False)
            jobs = resp.json().get("jobs", [])
            
            result = []
            for job in jobs:
                job_name = job.get("name", "")
                job_class = job.get("_class", "")
                item_type = "folder" if "folder" in job_class.lower() else "job"
                
                # Include based on type and include_folders setting
                if item_type == "job" or (item_type == "folder" and include_folders):
                    job_dict = {
                        "name": job_name,
                        "full_name": job_name,
                        "type": item_type,
                        "url": job.get("url", ""),
                        "description": job.get("description", "")
                    }
                    
                    # For jobs, apply advanced filtering
                    if item_type == "job" and (status_filter or last_build_result or days_since_last_build is not None or enabled_only is not None):
                        try:
                            enhanced_job = _get_enhanced_job_info(job_name, context)
                            job_dict.update(enhanced_job)
                            
                            # Apply filters
                            if not _job_matches_filters(job_dict, status_filter, last_build_result, days_since_last_build, enabled_only):
                                continue
                        except Exception as e:
                            logger.debug(f"[{context['request_id']}] Could not get enhanced info for job {job_name}: {e}")
                            # If we can't get enhanced info and filters are applied, skip the job
                            if status_filter or last_build_result or days_since_last_build is not None or enabled_only is not None:
                                continue
                    
                    result.append(job_dict)
            
            logger.info(f"[{context['request_id']}] Found {len(result)} top-level items after filtering")
        
        return result
        
    except Exception as e:
        logger.error(f"[{context.get('request_id', 'N/A')}] Failed to list jobs: {e}")
        raise

def _collect_jobs_recursive(path: str, context: Dict[str, Any], max_depth: int = JenkinsConfig.DEFAULT_MAX_DEPTH, current_depth: int = 0) -> List[JobTreeItem]:
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
def search_jobs(pattern: str, 
               job_type: str = "job", 
               max_depth: int = JenkinsConfig.DEFAULT_MAX_DEPTH,
               use_regex: bool = False,
               status_filter: Optional[str] = None,
               last_build_result: Optional[str] = None,
               days_since_last_build: Optional[int] = None,
               enabled_only: Optional[bool] = None) -> List[Dict[str, Any]]:
    """
    Search for Jenkins jobs using pattern matching with advanced filtering.
    
    Args:
        pattern: Pattern to match job names (supports wildcards like 'build*', '*test*', etc. or regex if use_regex=True)
        job_type: Filter by type - "job", "folder", or "all" (default: "job")
        max_depth: Maximum depth to search (default: 10)
        use_regex: If True, treat pattern as regular expression instead of wildcard (default: False)
        status_filter: Filter by job status: "building", "queued", "idle", "disabled" (optional)
        last_build_result: Filter by last build result: "SUCCESS", "FAILURE", "UNSTABLE", "ABORTED", "NOT_BUILT" (optional)
        days_since_last_build: Only include jobs built within the last N days (optional)
        enabled_only: If True, only include enabled jobs; if False, only disabled jobs (optional)
    
    Returns:
        List of matching items with their full paths and enhanced metadata
    """
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Searching for items with pattern: '{pattern}' (type: {job_type}, regex: {use_regex})")
    
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
            pattern_matches = False
            
            if use_regex:
                try:
                    # Use regex pattern matching
                    regex_pattern = re.compile(pattern, re.IGNORECASE)
                    pattern_matches = (regex_pattern.search(item.name) is not None or 
                                     regex_pattern.search(item.full_name) is not None)
                except re.error as regex_error:
                    logger.warning(f"[{context['request_id']}] Invalid regex pattern '{pattern}': {regex_error}")
                    # Fall back to fnmatch
                    pattern_matches = (fnmatch.fnmatch(item.name.lower(), pattern.lower()) or 
                                     fnmatch.fnmatch(item.full_name.lower(), pattern.lower()))
            else:
                # Use wildcard pattern matching
                pattern_matches = (fnmatch.fnmatch(item.name.lower(), pattern.lower()) or 
                                 fnmatch.fnmatch(item.full_name.lower(), pattern.lower()))
            
            if pattern_matches:
                matching_items.append(item)
        
        # Apply advanced filtering to jobs and convert to dict format
        result = []
        for item in matching_items:
            job_dict = item.model_dump()
            
            # For jobs, apply advanced filtering if specified
            if item.type == "job" and (status_filter or last_build_result or days_since_last_build is not None or enabled_only is not None):
                try:
                    enhanced_job = _get_enhanced_job_info(item.full_name, context)
                    job_dict.update(enhanced_job)
                    
                    # Apply filters
                    if not _job_matches_filters(job_dict, status_filter, last_build_result, days_since_last_build, enabled_only):
                        continue
                except Exception as e:
                    logger.debug(f"[{context['request_id']}] Could not get enhanced info for job {item.full_name}: {e}")
                    # If we can't get enhanced info and filters are applied, skip the job
                    if status_filter or last_build_result or days_since_last_build is not None or enabled_only is not None:
                        continue
            
            result.append(job_dict)
        
        logger.info(f"[{context['request_id']}] Found {len(result)} items matching pattern '{pattern}' after filtering")
        return result
        
    except Exception as e:
        logger.error(f"[{context.get('request_id', 'N/A')}] Failed to search for items with pattern '{pattern}': {e}")
        raise

@mcp.tool()
def search_and_trigger(pattern: str, params: Optional[Dict[str, Any]] = None, max_depth: int = JenkinsConfig.DEFAULT_MAX_DEPTH) -> Dict[str, Any]:
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
@cached_request(cache_type='short')
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
@cached_request(cache_type='static')
def server_info() -> Dict[str, Any]:
    """Get Jenkins server information."""
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Received request for server info.")
    try:
        resp = jenkins_request("GET", "api/json", context, is_job_specific=False)
        data = resp.json()
        info = {
            "version": data.get("jenkinsVersion"),
            "url": JenkinsConfig.URL
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

@mcp.tool()
@smart_pipeline_cache
def get_pipeline_status(job_name: str, build_number: int) -> Dict[str, Any]:
    """
    Gets detailed pipeline stage status for a Jenkins Pipeline job build.
    
    Uses Jenkins wfapi to get stage-by-stage execution details including:
    - Individual stage status, timing, and duration
    - Overall pipeline execution status
    - Stage logs and error information where available
    
    Supports both Declarative and Scripted Pipelines.
    """
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Received request for pipeline status: '{job_name}' #{build_number}")
    
    try:
        # First, verify the build exists and is a pipeline job
        build_info_resp = jenkins_request_nested("GET", job_name, f"{build_number}/api/json", context)
        build_info = build_info_resp.json()
        
        # Check if this is a pipeline job
        if build_info.get("_class") not in [
            "org.jenkinsci.plugins.workflow.job.WorkflowRun",
            "org.jenkinsci.plugins.pipeline.StageView$StageViewAction"
        ]:
            logger.warning(f"[{context['request_id']}] Job '{job_name}' build #{build_number} is not a pipeline job")
            return {
                "error": f"Job '{job_name}' build #{build_number} is not a pipeline job",
                "suggestion": "Pipeline status is only available for Jenkins Pipeline jobs (Declarative/Scripted pipelines)"
            }
        
        # Get pipeline stages using wfapi
        stages_resp = jenkins_request_nested("GET", job_name, f"{build_number}/wfapi/describe", context)
        stages_data = stages_resp.json()
        
        # Parse stage information
        stages = []
        for stage_data in stages_data.get("stages", []):
            stage = PipelineStage(
                id=stage_data.get("id", ""),
                name=stage_data.get("name", "Unknown Stage"),
                status=stage_data.get("status", "UNKNOWN"),
                start_time=stage_data.get("startTimeMillis"),
                duration=stage_data.get("durationMillis")
            )
            
            # Try to get stage logs if available
            try:
                if stage.id:
                    log_resp = jenkins_request_nested("GET", job_name, f"{build_number}/execution/node/{stage.id}/wfapi/log", context)
                    if log_resp.status_code == 200:
                        stage.logs = log_resp.text[:JenkinsConfig.MAX_LOG_SIZE]  # Limit log size
            except Exception as log_e:
                logger.debug(f"[{context['request_id']}] Could not fetch logs for stage {stage.name}: {log_e}")
                # Continue without logs - this is optional
            
            stages.append(stage)
        
        # Create pipeline status response
        pipeline_status = PipelineStageStatus(
            job_name=job_name,
            build_number=build_number,
            pipeline_status=build_info.get("result", "IN_PROGRESS") or "IN_PROGRESS",
            stages=stages,
            total_duration=build_info.get("duration"),
            estimated_duration=build_info.get("estimatedDuration")
        )
        
        logger.info(f"[{context['request_id']}] Successfully retrieved pipeline status for '{job_name}' #{build_number} with {len(stages)} stages")
        return {"result": pipeline_status.model_dump()}
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            error_msg = f"Build '{job_name}' #{build_number} not found"
            suggestion = f"Verify the job name and build number. Use list_jobs() to see available jobs and get_job_info('{job_name}') to see recent builds."
        else:
            error_msg = f"HTTP error accessing pipeline status: {e.response.status_code}"
            suggestion = "Check Jenkins server connectivity and permissions. Pipeline API requires appropriate Jenkins permissions."
        
        logger.error(f"[{context['request_id']}] {error_msg}")
        return {
            "error": error_msg,
            "suggestion": suggestion,
            "jenkins_response": e.response.text if hasattr(e.response, 'text') else str(e)
        }
    
    except Exception as e:
        logger.error(f"[{context['request_id']}] Failed to get pipeline status for '{job_name}' #{build_number}: {e}")
        return {
            "error": f"Failed to retrieve pipeline status: {str(e)}",
            "suggestion": "Ensure the job is a Jenkins Pipeline job and the build exists. Check server connectivity and authentication."
        }

@mcp.tool()
@cached_request(cache_type='permanent', key_func=lambda job_name, build_number: f"artifacts_{job_name}_{build_number}")
def list_build_artifacts(job_name: str, build_number: int) -> Dict[str, Any]:
    """
    List all artifacts for a specific Jenkins build.
    
    Args:
        job_name: Name of the Jenkins job
        build_number: Build number to list artifacts for
    
    Returns:
        Information about all artifacts including filenames, sizes, and download URLs
    """
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Received request to list artifacts for '{job_name}' #{build_number}")
    
    try:
        # Get build information including artifacts
        build_resp = jenkins_request_nested("GET", job_name, f"{build_number}/api/json", context)
        build_data = build_resp.json()
        
        # Extract artifact information
        jenkins_artifacts = build_data.get("artifacts", [])
        
        if not jenkins_artifacts:
            logger.info(f"[{context['request_id']}] No artifacts found for '{job_name}' #{build_number}")
            return {
                "result": ArtifactListResponse(
                    job_name=job_name,
                    build_number=build_number,
                    artifacts=[],
                    total_artifacts=0,
                    total_size=0
                ).model_dump()
            }
        
        # Process artifacts
        artifacts = []
        total_size = 0
        
        for artifact_data in jenkins_artifacts:
            filename = artifact_data.get("fileName", "unknown")
            display_path = artifact_data.get("displayPath", filename)
            relative_path = artifact_data.get("relativePath", filename)
            
            # Build download URL
            download_url = f"{JenkinsConfig.URL}/job/{quote(job_name, safe='')}/{build_number}/artifact/{quote(relative_path, safe='')}"
            
            # Try to get file size from Jenkins (if available)
            file_size = None
            try:
                # Some Jenkins versions provide size information
                if "size" in artifact_data:
                    file_size = artifact_data["size"]
                else:
                    # Try to get size via HEAD request
                    head_resp = jenkins_request_nested("HEAD", job_name, f"{build_number}/artifact/{relative_path}", context)
                    if "content-length" in head_resp.headers:
                        file_size = int(head_resp.headers["content-length"])
            except Exception:
                # Size information not available, continue without it
                pass
            
            if file_size:
                total_size += file_size
            
            artifact = BuildArtifact(
                filename=filename,
                display_path=display_path,
                relative_path=relative_path,
                size=file_size,
                timestamp=build_data.get("timestamp"),  # Build timestamp as proxy
                download_url=download_url
            )
            
            artifacts.append(artifact)
        
        artifact_response = ArtifactListResponse(
            job_name=job_name,
            build_number=build_number,
            artifacts=artifacts,
            total_artifacts=len(artifacts),
            total_size=total_size if total_size > 0 else None
        )
        
        logger.info(f"[{context['request_id']}] Found {len(artifacts)} artifacts for '{job_name}' #{build_number}")
        return {"result": artifact_response.model_dump()}
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            error_msg = f"Build '{job_name}' #{build_number} not found"
            suggestion = f"Verify the job name and build number. Use get_job_info('{job_name}') to see available builds."
        else:
            error_msg = f"HTTP error accessing build artifacts: {e.response.status_code}"
            suggestion = "Check Jenkins server connectivity and permissions."
        
        logger.error(f"[{context['request_id']}] {error_msg}")
        return {
            "error": error_msg,
            "suggestion": suggestion
        }
    
    except Exception as e:
        logger.error(f"[{context['request_id']}] Failed to list artifacts for '{job_name}' #{build_number}: {e}")
        return {
            "error": f"Failed to list build artifacts: {str(e)}",
            "suggestion": "Ensure the build exists and has completed. Check server connectivity and authentication."
        }

@mcp.tool()
def download_build_artifact(job_name: str, build_number: int, artifact_path: str, max_size_mb: int = JenkinsConfig.DEFAULT_MAX_ARTIFACT_SIZE_MB) -> Dict[str, Any]:
    """
    Download a specific build artifact content (text-based artifacts only for safety).
    
    Args:
        job_name: Name of the Jenkins job
        build_number: Build number containing the artifact
        artifact_path: Relative path to the artifact (from list_build_artifacts)
        max_size_mb: Maximum file size to download in MB (default: 50MB)
    
    Returns:
        Artifact content (for text files) or download information
    """
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Received request to download artifact '{artifact_path}' from '{job_name}' #{build_number}")
    
    max_size_bytes = max_size_mb * 1024 * 1024
    
    try:
        # First check if artifact exists by getting artifact list
        artifacts_resp = list_build_artifacts(job_name, build_number)
        if "error" in artifacts_resp:
            return artifacts_resp
        
        # Find the specific artifact
        artifacts_data = artifacts_resp["result"]["artifacts"]
        target_artifact = None
        
        for artifact in artifacts_data:
            if artifact["relative_path"] == artifact_path or artifact["filename"] == artifact_path:
                target_artifact = artifact
                break
        
        if not target_artifact:
            return {
                "error": f"Artifact '{artifact_path}' not found in build '{job_name}' #{build_number}",
                "suggestion": f"Use list_build_artifacts('{job_name}', {build_number}) to see available artifacts."
            }
        
        # Check file size
        if target_artifact.get("size") and target_artifact["size"] > max_size_bytes:
            return {
                "error": f"Artifact too large: {target_artifact['size']} bytes (max: {max_size_bytes} bytes)",
                "suggestion": f"Use a larger max_size_mb parameter or download via URL: {target_artifact['download_url']}",
                "download_url": target_artifact['download_url']
            }
        
        # Download the artifact
        artifact_resp = jenkins_request_nested("GET", job_name, f"{build_number}/artifact/{target_artifact['relative_path']}", context)
        
        # Check response size
        content_length = artifact_resp.headers.get('content-length')
        if content_length and int(content_length) > max_size_bytes:
            return {
                "error": f"Artifact too large: {content_length} bytes (max: {max_size_bytes} bytes)",
                "suggestion": f"Use a larger max_size_mb parameter or download via URL: {target_artifact['download_url']}",
                "download_url": target_artifact['download_url']
            }
        
        # Check if content is text-based (safe to return)
        content_type = artifact_resp.headers.get('content-type', '')
        is_text = (content_type.startswith('text/') or 
                  'json' in content_type or 
                  'xml' in content_type or
                  'yaml' in content_type or
                  artifact_path.endswith(('.txt', '.log', '.json', '.xml', '.yaml', '.yml', '.md', '.csv')))
        
        if is_text:
            try:
                content = artifact_resp.text
                return {
                    "result": {
                        "artifact_info": target_artifact,
                        "content": content[:JenkinsConfig.MAX_CONTENT_SIZE],  # Limit content for safety
                        "content_truncated": len(content) > JenkinsConfig.MAX_CONTENT_SIZE,
                        "content_length": len(content),
                        "content_type": content_type
                    }
                }
            except UnicodeDecodeError:
                # Not actually text, treat as binary
                is_text = False
        
        if not is_text:
            return {
                "result": {
                    "artifact_info": target_artifact,
                    "message": "Binary artifact cannot be displayed as text",
                    "download_url": target_artifact['download_url'],
                    "content_type": content_type,
                    "suggestion": "Use the download_url to download the file directly"
                }
            }
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            error_msg = f"Artifact '{artifact_path}' not found in build '{job_name}' #{build_number}"
            suggestion = f"Verify the artifact path. Use list_build_artifacts('{job_name}', {build_number}) to see available artifacts."
        else:
            error_msg = f"HTTP error downloading artifact: {e.response.status_code}"
            suggestion = "Check Jenkins server connectivity and permissions."
        
        logger.error(f"[{context['request_id']}] {error_msg}")
        return {
            "error": error_msg,
            "suggestion": suggestion
        }
    
    except Exception as e:
        logger.error(f"[{context['request_id']}] Failed to download artifact '{artifact_path}' from '{job_name}' #{build_number}: {e}")
        return {
            "error": f"Failed to download artifact: {str(e)}",
            "suggestion": "Ensure the build and artifact exist. Check server connectivity and authentication."
        }

@mcp.tool()
def search_build_artifacts(job_name: str, pattern: str, max_builds: int = JenkinsConfig.DEFAULT_MAX_BUILDS, use_regex: bool = False) -> Dict[str, Any]:
    """
    Search for artifacts across recent builds of a job using pattern matching.
    
    Args:
        job_name: Name of the Jenkins job to search
        pattern: Pattern to match artifact names (wildcards or regex)
        max_builds: Maximum number of recent builds to search (default: 10)
        use_regex: If True, treat pattern as regex instead of wildcard (default: False)
    
    Returns:
        List of matching artifacts across builds with their metadata
    """
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Searching for artifacts matching pattern '{pattern}' in job '{job_name}'")
    
    try:
        # Get job information to find recent builds
        job_info_resp = get_job_info(job_name, auto_search=False)
        if "error" in job_info_resp:
            return job_info_resp
        
        job_data = job_info_resp["result"]
        builds = job_data.get("builds", [])[:max_builds]
        
        if not builds:
            return {
                "result": {
                    "job_name": job_name,
                    "pattern": pattern,
                    "matching_artifacts": [],
                    "builds_searched": 0,
                    "total_matches": 0
                }
            }
        
        matching_artifacts = []
        builds_searched = 0
        
        for build in builds:
            build_number = build.get("number")
            if not build_number:
                continue
                
            builds_searched += 1
            
            try:
                # Get artifacts for this build
                artifacts_resp = list_build_artifacts(job_name, build_number)
                if "error" in artifacts_resp:
                    logger.debug(f"[{context['request_id']}] Could not get artifacts for build #{build_number}: {artifacts_resp['error']}")
                    continue
                
                build_artifacts = artifacts_resp["result"]["artifacts"]
                
                # Apply pattern matching
                for artifact in build_artifacts:
                    artifact_matches = False
                    
                    if use_regex:
                        try:
                            regex_pattern = re.compile(pattern, re.IGNORECASE)
                            artifact_matches = (regex_pattern.search(artifact["filename"]) is not None or 
                                              regex_pattern.search(artifact["relative_path"]) is not None)
                        except re.error:
                            # Fall back to wildcard matching
                            artifact_matches = (fnmatch.fnmatch(artifact["filename"].lower(), pattern.lower()) or 
                                              fnmatch.fnmatch(artifact["relative_path"].lower(), pattern.lower()))
                    else:
                        artifact_matches = (fnmatch.fnmatch(artifact["filename"].lower(), pattern.lower()) or 
                                          fnmatch.fnmatch(artifact["relative_path"].lower(), pattern.lower()))
                    
                    if artifact_matches:
                        # Add build information to artifact
                        enhanced_artifact = artifact.copy()
                        enhanced_artifact["build_number"] = build_number
                        enhanced_artifact["build_result"] = build.get("result", "UNKNOWN")
                        enhanced_artifact["build_timestamp"] = build.get("timestamp")
                        matching_artifacts.append(enhanced_artifact)
                        
            except Exception as e:
                logger.debug(f"[{context['request_id']}] Error searching build #{build_number}: {e}")
                continue
        
        result = {
            "job_name": job_name,
            "pattern": pattern,
            "use_regex": use_regex,
            "matching_artifacts": matching_artifacts,
            "builds_searched": builds_searched,
            "total_matches": len(matching_artifacts)
        }
        
        logger.info(f"[{context['request_id']}] Found {len(matching_artifacts)} matching artifacts across {builds_searched} builds")
        return {"result": result}
        
    except Exception as e:
        logger.error(f"[{context['request_id']}] Failed to search artifacts in '{job_name}' with pattern '{pattern}': {e}")
        return {
            "error": f"Failed to search build artifacts: {str(e)}",
            "suggestion": "Ensure the job exists and has builds with artifacts. Check server connectivity and authentication."
        }

# --- Batch Processing Operations ---

# Global batch operation storage (in production, use Redis or database)
_batch_operations: Dict[str, Dict[str, Any]] = {}
_batch_lock = threading.Lock()

@mcp.tool()
def batch_trigger_jobs(operations: List[Dict[str, Any]], 
                      max_concurrent: int = 5, 
                      fail_fast: bool = False,
                      wait_for_completion: bool = False) -> Dict[str, Any]:
    """
    Trigger multiple Jenkins jobs in batch with parallel execution.
    
    Args:
        operations: List of job operations, each containing:
            - job_name (str): Name of the Jenkins job
            - params (dict, optional): Job parameters
            - priority (int, optional): Priority 1-10 (1=highest)
        max_concurrent: Maximum number of concurrent job triggers (default: 5)
        fail_fast: If True, stop processing on first failure (default: False)
        wait_for_completion: If True, wait for all jobs to complete (default: False)
    
    Returns:
        Batch operation response with results and operation ID for monitoring
    """
    context = get_request_context()
    operation_id = str(uuid.uuid4())[:8]  # Short ID for monitoring
    start_time = time.time()
    
    logger.info(f"[{context['request_id']}] Starting batch operation {operation_id} with {len(operations)} jobs")
    
    try:
        # Validate and parse operations
        batch_ops = []
        for i, op in enumerate(operations):
            try:
                if isinstance(op, dict):
                    batch_op = BatchJobOperation(**op)
                else:
                    batch_op = op
                batch_ops.append(batch_op)
            except Exception as e:
                return create_error_response(
                    JenkinsValidationError(f"Invalid operation at index {i}: {str(e)}"),
                    context,
                    "batch job validation"
                )
        
        # Sort by priority (1 = highest priority)
        batch_ops.sort(key=lambda x: x.priority)
        
        # Execute batch operations
        results = []
        successful = failed = skipped = 0
        
        # Use threading for parallel execution
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import concurrent.futures
        
        def trigger_single_job(batch_op: BatchJobOperation) -> BatchJobResult:
            """Trigger a single job and return result."""
            job_start_time = time.time()
            try:
                # Use existing trigger_job function
                trigger_context = get_request_context()
                response = trigger_job(batch_op.job_name, batch_op.params)
                
                execution_time = time.time() - job_start_time
                
                if "error" in response:
                    return BatchJobResult(
                        job_name=batch_op.job_name,
                        success=False,
                        error=response["error"],
                        execution_time=execution_time,
                        timestamp=int(time.time() * 1000)
                    )
                else:
                    return BatchJobResult(
                        job_name=batch_op.job_name,
                        success=True,
                        queue_url=response.get("queue_url"),
                        build_number=response.get("build_number"),
                        execution_time=execution_time,
                        timestamp=int(time.time() * 1000)
                    )
                    
            except Exception as e:
                execution_time = time.time() - job_start_time
                return BatchJobResult(
                    job_name=batch_op.job_name,
                    success=False,
                    error=str(e),
                    execution_time=execution_time,
                    timestamp=int(time.time() * 1000)
                )
        
        # Execute jobs with controlled concurrency
        with ThreadPoolExecutor(max_workers=min(max_concurrent, len(batch_ops))) as executor:
            # Submit all jobs
            future_to_op = {executor.submit(trigger_single_job, op): op for op in batch_ops}
            
            # Collect results as they complete
            for future in as_completed(future_to_op):
                batch_op = future_to_op[future]
                try:
                    result = future.result()
                    results.append(result)
                    
                    if result.success:
                        successful += 1
                        logger.debug(f"[{context['request_id']}] Job '{result.job_name}' triggered successfully")
                    else:
                        failed += 1
                        logger.warning(f"[{context['request_id']}] Job '{result.job_name}' failed: {result.error}")
                        
                        if fail_fast:
                            logger.info(f"[{context['request_id']}] Stopping batch operation due to fail_fast=True")
                            # Cancel remaining futures
                            for remaining_future in future_to_op:
                                if not remaining_future.done():
                                    remaining_future.cancel()
                                    skipped += 1
                            break
                            
                except Exception as e:
                    failed += 1
                    logger.error(f"[{context['request_id']}] Unexpected error processing job '{batch_op.job_name}': {e}")
                    results.append(BatchJobResult(
                        job_name=batch_op.job_name,
                        success=False,
                        error=f"Execution error: {str(e)}",
                        timestamp=int(time.time() * 1000)
                    ))
        
        total_execution_time = time.time() - start_time
        completed_at = int(time.time() * 1000)
        
        # Create response
        batch_response = BatchOperationResponse(
            operation_id=operation_id,
            total_jobs=len(batch_ops),
            successful=successful,
            failed=failed,
            skipped=skipped,
            results=results,
            total_execution_time=total_execution_time,
            started_at=int(start_time * 1000),
            completed_at=completed_at
        )
        
        # Store operation for monitoring (optional)
        with _batch_lock:
            _batch_operations[operation_id] = {
                "response": batch_response.model_dump(),
                "status": "completed",
                "created_at": completed_at
            }
        
        logger.info(f"[{context['request_id']}] Batch operation {operation_id} completed: "
                   f"{successful} successful, {failed} failed, {skipped} skipped in {total_execution_time:.2f}s")
        
        return {"result": batch_response.model_dump()}
        
    except Exception as e:
        return create_error_response(e, context, "batch job triggering")

@mcp.tool()
def batch_monitor_jobs(operation_id: str) -> Dict[str, Any]:
    """
    Monitor the status of a batch operation and its individual jobs.
    
    Args:
        operation_id: The operation ID returned from batch_trigger_jobs
    
    Returns:
        Current status of the batch operation and individual job statuses
    """
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Monitoring batch operation {operation_id}")
    
    try:
        # Check if operation exists
        with _batch_lock:
            if operation_id not in _batch_operations:
                return create_error_response(
                    JenkinsNotFoundError(f"Batch operation '{operation_id}' not found"),
                    context,
                    "batch operation monitoring"
                )
            
            operation_data = _batch_operations[operation_id]
        
        batch_response = operation_data["response"]
        jobs_status = []
        
        # Get current status of each job from the original batch
        for result in batch_response.get("results", []):
            job_name = result["job_name"]
            
            if result["success"] and result.get("build_number"):
                try:
                    # Get current build status
                    build_status = get_build_status(job_name, result["build_number"])
                    if "error" not in build_status:
                        status_info = {
                            "job_name": job_name,
                            "build_number": result["build_number"],
                            "status": build_status["result"],
                            "building": build_status.get("building", False),
                            "duration": build_status.get("duration"),
                            "url": build_status.get("url")
                        }
                    else:
                        status_info = {
                            "job_name": job_name,
                            "status": "UNKNOWN",
                            "error": "Could not fetch current status"
                        }
                except Exception:
                    status_info = {
                        "job_name": job_name,
                        "status": "UNKNOWN",
                        "error": "Status check failed"
                    }
            else:
                status_info = {
                    "job_name": job_name,
                    "status": "FAILED" if not result["success"] else "NOT_STARTED",
                    "error": result.get("error")
                }
            
            jobs_status.append(status_info)
        
        # Calculate overall progress
        total_jobs = len(jobs_status)
        completed_jobs = sum(1 for job in jobs_status 
                           if job.get("status") in ["SUCCESS", "FAILURE", "UNSTABLE", "ABORTED", "FAILED"])
        running_jobs = sum(1 for job in jobs_status if job.get("building", False))
        
        if completed_jobs == total_jobs:
            overall_status = "completed"
            progress_percentage = 100.0
        elif running_jobs > 0:
            overall_status = "running"
            progress_percentage = (completed_jobs / total_jobs) * 100
        else:
            overall_status = "partial"
            progress_percentage = (completed_jobs / total_jobs) * 100
        
        monitoring_response = BatchMonitoringResponse(
            operation_id=operation_id,
            jobs_status=jobs_status,
            overall_status=overall_status,
            progress_percentage=progress_percentage,
            estimated_completion=None  # Could implement ETA calculation
        )
        
        logger.info(f"[{context['request_id']}] Batch operation {operation_id} status: "
                   f"{overall_status} ({progress_percentage:.1f}% complete)")
        
        return {"result": monitoring_response.model_dump()}
        
    except Exception as e:
        return create_error_response(e, context, "batch operation monitoring")

@mcp.tool()
def batch_cancel_jobs(operation_id: str, cancel_running_builds: bool = False) -> Dict[str, Any]:
    """
    Cancel a batch operation and optionally cancel running builds.
    
    Args:
        operation_id: The operation ID to cancel
        cancel_running_builds: If True, attempt to cancel running builds
    
    Returns:
        Cancellation status and results
    """
    context = get_request_context()
    logger.info(f"[{context['request_id']}] Cancelling batch operation {operation_id}")
    
    try:
        # Check if operation exists
        with _batch_lock:
            if operation_id not in _batch_operations:
                return create_error_response(
                    JenkinsNotFoundError(f"Batch operation '{operation_id}' not found"),
                    context,
                    "batch operation cancellation"
                )
            
            operation_data = _batch_operations[operation_id]
            # Mark as cancelled
            operation_data["status"] = "cancelled"
        
        cancelled_jobs = []
        
        if cancel_running_builds:
            batch_response = operation_data["response"]
            
            for result in batch_response.get("results", []):
                if result["success"] and result.get("build_number"):
                    job_name = result["job_name"]
                    build_number = result["build_number"]
                    
                    try:
                        # Check if build is still running
                        build_status = get_build_status(job_name, build_number)
                        if "error" not in build_status and build_status.get("building", False):
                            # TODO: Implement build cancellation API call
                            # For now, just log the attempt
                            logger.info(f"[{context['request_id']}] Would cancel running build {job_name}#{build_number}")
                            cancelled_jobs.append({
                                "job_name": job_name,
                                "build_number": build_number,
                                "status": "cancellation_requested"
                            })
                    except Exception as e:
                        logger.warning(f"[{context['request_id']}] Could not check/cancel build {job_name}#{build_number}: {e}")
        
        return {
            "result": {
                "operation_id": operation_id,
                "status": "cancelled",
                "cancelled_builds": cancelled_jobs,
                "message": f"Batch operation {operation_id} has been cancelled"
            }
        }
        
    except Exception as e:
        return create_error_response(e, context, "batch operation cancellation")

@with_retry(max_retries=2, base_delay=0.5)  # Quick retries for health checks
def _health_check_request():
    """Make the actual health check request to Jenkins."""
    auth = get_jenkins_auth()
    response = requests.get(f"{JenkinsConfig.URL}/api/json", auth=auth, timeout=JenkinsConfig.HEALTH_CHECK_TIMEOUT)
    response.raise_for_status()
    return response

# --- Cache Management Tools ---

@mcp.tool()
def get_cache_statistics() -> Dict[str, Any]:
    """
    Get comprehensive cache statistics and performance metrics.
    
    Returns detailed information about cache hits, misses, sizes, and efficiency.
    """
    try:
        stats = cache_manager.get_cache_stats()
        
        # Calculate hit rate
        total_requests = stats['stats']['hits'] + stats['stats']['misses']
        hit_rate = (stats['stats']['hits'] / total_requests * 100) if total_requests > 0 else 0
        
        return {
            "performance": {
                "hit_rate_percentage": round(hit_rate, 2),
                "total_hits": stats['stats']['hits'],
                "total_misses": stats['stats']['misses'],
                "total_requests": total_requests,
                "cache_invalidations": stats['stats']['invalidations']
            },
            "cache_details": stats['cache_info'],
            "cache_efficiency": {
                "static_utilization": round(stats['cache_info']['static']['size'] / stats['cache_info']['static']['maxsize'] * 100, 2),
                "semi_static_utilization": round(stats['cache_info']['semi_static']['size'] / stats['cache_info']['semi_static']['maxsize'] * 100, 2),
                "dynamic_utilization": round(stats['cache_info']['dynamic']['size'] / stats['cache_info']['dynamic']['maxsize'] * 100, 2),
                "permanent_utilization": round(stats['cache_info']['permanent']['size'] / stats['cache_info']['permanent']['maxsize'] * 100, 2),
                "short_utilization": round(stats['cache_info']['short']['size'] / stats['cache_info']['short']['maxsize'] * 100, 2)
            }
        }
    except Exception as e:
        logger.error(f"Failed to get cache statistics: {e}")
        return {"error": "Failed to retrieve cache statistics", "details": str(e)}

@mcp.tool() 
def clear_cache(cache_type: Optional[str] = None, job_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Clear caches with fine-grained control.
    
    Args:
        cache_type: Type of cache to clear ('all', 'static', 'semi_static', 'dynamic', 'permanent', 'short')
        job_name: Clear caches for a specific job only
    
    Returns:
        Confirmation of cache clearing operation
    """
    try:
        if job_name:
            # Clear caches for specific job
            cache_manager.invalidate_job_caches(job_name)
            return {
                "status": "success",
                "message": f"Cleared all caches for job: {job_name}",
                "action": "job_specific_clear"
            }
        elif cache_type == "all" or cache_type is None:
            # Clear all caches
            cache_manager.clear_all_caches()
            return {
                "status": "success", 
                "message": "All caches cleared successfully",
                "action": "full_clear"
            }
        else:
            # Clear specific cache type
            cache = cache_manager.get_cache_for_type(cache_type)
            if cache is not None:
                cache.clear()
                cache_manager.stats['invalidations'] += 1
                return {
                    "status": "success",
                    "message": f"Cleared {cache_type} cache successfully",
                    "action": "selective_clear"
                }
            else:
                return {
                    "status": "error",
                    "message": f"Invalid cache type: {cache_type}",
                    "valid_types": ["all", "static", "semi_static", "dynamic", "permanent", "short"]
                }
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        return {"status": "error", "message": "Failed to clear cache", "details": str(e)}

@mcp.tool()
def warm_cache(operations: List[str] = None) -> Dict[str, Any]:
    """
    Warm up caches by pre-loading frequently accessed data.
    
    Args:
        operations: List of operations to warm ('server_info', 'job_list', 'queue_info')
    
    Returns:
        Results of cache warming operations
    """
    try:
        if operations is None:
            operations = ['server_info', 'job_list', 'queue_info']
        
        results = []
        
        for operation in operations:
            try:
                if operation == 'server_info':
                    server_info()
                    results.append({"operation": "server_info", "status": "success"})
                elif operation == 'job_list':
                    list_jobs()
                    results.append({"operation": "job_list", "status": "success"})
                elif operation == 'queue_info':
                    get_queue_info()
                    results.append({"operation": "queue_info", "status": "success"})
                else:
                    results.append({"operation": operation, "status": "skipped", "reason": "unknown operation"})
            except Exception as e:
                results.append({"operation": operation, "status": "failed", "error": str(e)})
        
        return {
            "status": "completed",
            "message": "Cache warming completed",
            "results": results,
            "warmed_operations": len([r for r in results if r["status"] == "success"])
        }
    except Exception as e:
        logger.error(f"Failed to warm cache: {e}")
        return {"status": "error", "message": "Failed to warm cache", "details": str(e)}

@mcp.resource("status://health")
def get_health() -> HealthCheckResponse:
    """
    Performs a health check on the server and its connection to Jenkins.
    """
    try:
        # Verify connection to Jenkins with retry logic
        response = _health_check_request()

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

