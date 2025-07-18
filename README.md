# Jenkins MCP Server.

An MCP server for interacting with a Jenkins CI/CD server. Allows you to trigger jobs, check build statuses, and manage your Jenkins instance through MCP.

## Features

- **Job Management**: Trigger, list, and get detailed information about Jenkins jobs.
- **Build Status**: Check the status of specific builds and retrieve console logs.
- **Queue Management**: View items currently in the build queue.
- **Server Information**: Get basic information about the connected Jenkins server.
- **LLM Integration**: Includes prompts and configurations for summarizing build logs (demonstration).
- **Transport Support**: Supports both STDIO and Streamable HTTP transports.
- **Input Validation**: Uses Pydantic for robust input validation and error handling.
- **Compatibility**: Fully compatible with the MCP Gateway.

## Prerequisites

- Python 3.12+
- A running Jenkins instance
- `uv` for package management

## Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd jenkins_mcp
    ```

2.  **Create a virtual environment:**
    ```bash
    uv venv
    ```

3.  **Activate the virtual environment:**
    ```bash
    source .venv/bin/activate
    ```

4.  **Install dependencies:**
    ```bash
    uv pip install -e .
    ```

5.  **Create a `.env` file:**
    Create a `.env` file in the project root and add your Jenkins credentials and URL.
    ```
    JENKINS_URL="http://your-jenkins-instance:8080"
    JENKINS_USER="your-username"
    JENKINS_API_TOKEN="your-api-token"
    MCP_PORT=8010
    ```

## Usage

### Running the Server

You can run the server in two modes:

**1. STDIO Mode** (for direct interaction)
```bash
python jenkins_mcp_server_enhanced.py
```

**2. HTTP Mode** (for use with MCP Gateway)
```bash
python jenkins_mcp_server_enhanced.py --transport streamable-http --port 8010
```
The port can be configured via the `--port` argument or the `MCP_PORT` environment variable.

## Available Tools

Here is a list of the tools exposed by this MCP server:

### `trigger_job`
- **Description**: Triggers a Jenkins job with optional parameters.
- **Parameters**:
    - `job_name` (string): The name of the Jenkins job.
    - `params` (object, optional): Job parameters as a JSON object. For multiselect parameters, pass an array of strings.
- **Returns**: A confirmation message with the queue URL.

### `get_job_info`
- **Description**: Gets detailed information about a Jenkins job, including its parameters.
- **Parameters**:
    - `job_name` (string): The name of the Jenkins job.
- **Returns**: An object containing the job's description, parameters, and last build number.

### `get_build_status`
- **Description**: Gets the status of a specific build.
- **Parameters**:
    - `job_name` (string): The name of the Jenkins job.
    - `build_number` (integer): The build number.
- **Returns**: An object with the build status, timestamp, duration, and URL.

### `get_console_log`
- **Description**: Retrieves the console log for a specific build.
- **Parameters**:
    - `job_name` (string): The name of the Jenkins job.
    - `build_number` (integer): The build number.
    - `start` (integer, optional): The starting byte position for fetching the log.
- **Returns**: The console log text and information about whether more data is available.

### `list_jobs`
- **Description**: Lists all available jobs on the Jenkins server.
- **Parameters**: None
- **Returns**: A list of job names.

### `get_queue_info`
- **Description**: Gets information about builds currently in the queue.
- **Parameters**: None
- **Returns**: A list of items in the queue.

### `server_info`
- **Description**: Gets basic information about the Jenkins server.
- **Parameters**: None
- **Returns**: The Jenkins version and URL.

### `summarize_build_log`
- **Description**: (Demonstration) Summarizes a build log using a pre-configured LLM prompt.
- **Parameters**:
    - `job_name` (string): The name of the Jenkins job.
    - `build_number` (integer): The build number.
- **Returns**: A placeholder summary and the prompt that would be used.

## Example Usage with `mcp-cli`

First, ensure the server is running in HTTP mode and registered with your MCP Gateway.

```bash
# Example: Triggering a job
mcp-cli cmd --server gateway --tool jenkins_server.trigger_job --tool-args '{"job_name": "my-test-job", "params": {"branch": "develop", "deploy": true}}'

# Example: Listing all jobs
mcp-cli cmd --server gateway --tool jenkins_server.list_jobs
```

## Dependencies

- `fastmcp`
- `pydantic`
- `requests`
- `python-dotenv`

## License

This project is licensed under the Apache 2.0 License.
