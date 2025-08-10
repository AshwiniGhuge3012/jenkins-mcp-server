# Jenkins MCP Server

[![npm version](https://badge.fury.io/js/@ashwinighuge%2Fjenkins-mcp-server.svg)](https://badge.fury.io/js/@ashwinighuge%2Fjenkins-mcp-server)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

An enterprise-grade MCP (Model Context Protocol) server for seamless Jenkins CI/CD integration. Enables AI assistants like Claude to interact with Jenkins through a comprehensive, production-ready API.

## 🚀 Quick Start

### npm Installation (Recommended)

```bash
# Global installation
npm install -g @ashwinighuge/jenkins-mcp-server

# Or use directly with npx
npx @ashwinighuge/jenkins-mcp-server --help
```

### Claude Desktop Integration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "jenkins": {
      "command": "jenkins-mcp",
      "env": {
        "JENKINS_URL": "http://your-jenkins-server:8080",
        "JENKINS_USER": "your-username",
        "JENKINS_API_TOKEN": "your-api-token"
      }
    }
  }
}
```

## ✨ Features

- **🔧 Job Management**: Trigger, list, search, and monitor Jenkins jobs with full folder support
- **📊 Build Status**: Real-time build status tracking and console log streaming
- **🔄 Pipeline Support**: Stage-by-stage pipeline execution monitoring with detailed logs
- **📦 Artifact Management**: List, download, and search build artifacts across multiple builds
- **⚡ Batch Operations**: Parallel job execution with intelligent priority queuing
- **🚀 Performance Caching**: Multi-tier intelligent caching system with automatic invalidation
- **🔍 Advanced Filtering**: Filter jobs by status, results, dates, and more with regex support
- **📋 Queue Management**: Real-time build queue monitoring and management
- **🔒 Enterprise Security**: CSRF protection, 2FA support, and secure authentication
- **🌐 Cross-Platform**: Works on Windows, macOS, and Linux
- **🔄 Retry Logic**: Built-in exponential backoff for improved reliability
- **📡 Transport Flexibility**: Supports both STDIO and HTTP transports
- **✅ Input Validation**: Robust Pydantic-based validation and error handling

## 📋 Prerequisites

- **Node.js**: 14.0.0 or higher
- **Python**: 3.12 or higher
- **Jenkins**: 2.401+ (recommended)
- **Jenkins API Token**: For authentication

## 🛠 Installation Methods

### Method 1: npm (Recommended)

```bash
# Install globally for system-wide access
npm install -g @ashwinighuge/jenkins-mcp-server

# Verify installation
jenkins-mcp --help
```

### Method 2: Development Setup

```bash
# Clone the repository
git clone https://github.com/AshwiniGhuge3012/jenkins-mcp-server
cd jenkins-mcp-server

# Install Node.js dependencies
npm install

# Install Python dependencies
pip install -r requirements.txt  # or use uv pip install

# Run locally
node bin/jenkins-mcp.js --help
```

## 🔐 Configuration

### Environment Variables

Create a `.env` file in your working directory:

```bash
# Required Jenkins Configuration
JENKINS_URL="http://your-jenkins-server:8080"
JENKINS_USER="your-username"
JENKINS_API_TOKEN="your-api-token"

# Optional: Server Configuration
MCP_PORT=8010
MCP_HOST=0.0.0.0

# Optional: Retry Configuration
JENKINS_MAX_RETRIES=3
JENKINS_RETRY_BASE_DELAY=1.0
JENKINS_RETRY_MAX_DELAY=60.0
JENKINS_RETRY_BACKOFF_MULTIPLIER=2.0

# Optional: Performance Cache Configuration
JENKINS_CACHE_STATIC_TTL=3600        # 1 hour
JENKINS_CACHE_SEMI_STATIC_TTL=300    # 5 minutes
JENKINS_CACHE_DYNAMIC_TTL=30         # 30 seconds
JENKINS_CACHE_SHORT_TTL=10           # 10 seconds
JENKINS_CACHE_STATIC_SIZE=1000       # Max cached items
JENKINS_CACHE_SEMI_STATIC_SIZE=500
JENKINS_CACHE_DYNAMIC_SIZE=200
JENKINS_CACHE_PERMANENT_SIZE=2000
JENKINS_CACHE_SHORT_SIZE=100
```

### Getting Jenkins API Token

1. Log into your Jenkins instance
2. Click your username → **Configure**
3. Scroll to **API Token** section
4. Click **Add new Token**
5. Give it a name and click **Generate**
6. Copy the generated token (save it securely!)

## 🚀 Usage

### Command Line Interface

```bash
# STDIO mode (default, for Claude Desktop)
jenkins-mcp

# HTTP mode (for MCP Gateway)
jenkins-mcp --transport streamable-http --port 8010

# Custom host and port
jenkins-mcp --transport streamable-http --host localhost --port 9000

# Show help
jenkins-mcp --help
```

### Transport Modes

| Mode | Use Case | Command |
|------|----------|---------|
| **STDIO** | Claude Desktop, direct MCP clients | `jenkins-mcp` |
| **HTTP** | MCP Gateway, web integrations | `jenkins-mcp --transport streamable-http` |

### Advanced Usage Examples

```bash
# Using with npx (no global installation)
npx @ashwinighuge/jenkins-mcp-server

# Using environment variables
JENKINS_URL=http://localhost:8080 JENKINS_USER=admin JENKINS_API_TOKEN=abc123 jenkins-mcp

# HTTP mode with custom configuration
jenkins-mcp --transport streamable-http --host 0.0.0.0 --port 8080
```

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
- **Description**: Lists all available jobs on the Jenkins server with advanced filtering capabilities.
- **Parameters**:
    - `recursive` (boolean, optional): If True, recursively traverse folders (default: True)
    - `max_depth` (integer, optional): Maximum depth to recurse (default: 10)
    - `include_folders` (boolean, optional): Whether to include folder items (default: False)
    - `status_filter` (string, optional): Filter by job status: "building", "queued", "idle", "disabled"
    - `last_build_result` (string, optional): Filter by last build result: "SUCCESS", "FAILURE", "UNSTABLE", "ABORTED", "NOT_BUILT"
    - `days_since_last_build` (integer, optional): Only jobs built within the last N days
    - `enabled_only` (boolean, optional): If True, only enabled jobs; if False, only disabled jobs
- **Returns**: A list of jobs with enhanced metadata including build status and timestamps.

### `search_jobs`
- **Description**: Search for Jenkins jobs using pattern matching with advanced filtering.
- **Parameters**:
    - `pattern` (string): Pattern to match job names (supports wildcards like 'build*', '*test*', etc.)
    - `job_type` (string, optional): Filter by type - "job", "folder", or "all" (default: "job")
    - `max_depth` (integer, optional): Maximum depth to search (default: 10)
    - `use_regex` (boolean, optional): If True, treat pattern as regex instead of wildcard (default: False)
    - `status_filter` (string, optional): Filter by job status: "building", "queued", "idle", "disabled"
    - `last_build_result` (string, optional): Filter by last build result: "SUCCESS", "FAILURE", "UNSTABLE", "ABORTED", "NOT_BUILT"
    - `days_since_last_build` (integer, optional): Only jobs built within the last N days
    - `enabled_only` (boolean, optional): If True, only enabled jobs; if False, only disabled jobs
- **Returns**: A list of matching jobs with enhanced metadata and full paths.

### `get_queue_info`
- **Description**: Gets information about builds currently in the queue.
- **Parameters**: None
- **Returns**: A list of items in the queue.

### `server_info`
- **Description**: Gets basic information about the Jenkins server.
- **Parameters**: None
- **Returns**: The Jenkins version and URL.

### `get_pipeline_status`
- **Description**: Gets detailed pipeline stage status for Jenkins Pipeline job builds.
- **Parameters**:
    - `job_name` (string): The name of the Jenkins Pipeline job.
    - `build_number` (integer): The build number.
- **Returns**: Pipeline execution details including stage-by-stage status, timing, duration, and logs.

### `list_build_artifacts`
- **Description**: List all artifacts for a specific Jenkins build.
- **Parameters**:
    - `job_name` (string): Name of the Jenkins job.
    - `build_number` (integer): Build number to list artifacts for.
- **Returns**: Information about all artifacts including filenames, sizes, and download URLs.

### `download_build_artifact`
- **Description**: Download a specific build artifact content (text-based artifacts only for safety).
- **Parameters**:
    - `job_name` (string): Name of the Jenkins job.
    - `build_number` (integer): Build number containing the artifact.
    - `artifact_path` (string): Relative path to the artifact (from list_build_artifacts).
    - `max_size_mb` (integer, optional): Maximum file size to download in MB (default: 50MB).
- **Returns**: Artifact content (for text files) or download information.

### `search_build_artifacts`
- **Description**: Search for artifacts across recent builds of a job using pattern matching.
- **Parameters**:
    - `job_name` (string): Name of the Jenkins job to search.
    - `pattern` (string): Pattern to match artifact names (wildcards or regex).
    - `max_builds` (integer, optional): Maximum number of recent builds to search (default: 10).
    - `use_regex` (boolean, optional): If True, treat pattern as regex instead of wildcard (default: False).
- **Returns**: List of matching artifacts across builds with their metadata.

### `batch_trigger_jobs`
- **Description**: Trigger multiple Jenkins jobs in batch with parallel execution and priority queuing.
- **Parameters**:
    - `operations` (array): List of job operations, each containing:
        - `job_name` (string): Name of the Jenkins job
        - `params` (object, optional): Job parameters
        - `priority` (integer, optional): Priority 1-10 (1=highest, default: 1)
    - `max_concurrent` (integer, optional): Maximum concurrent job triggers (default: 5)
    - `fail_fast` (boolean, optional): Stop processing on first failure (default: false)
    - `wait_for_completion` (boolean, optional): Wait for all jobs to complete (default: false)
- **Returns**: Batch operation response with operation ID, results, and execution statistics.

### `batch_monitor_jobs`
- **Description**: Monitor the status of a batch operation and its individual jobs.
- **Parameters**:
    - `operation_id` (string): The operation ID returned from batch_trigger_jobs.
- **Returns**: Current status of the batch operation including progress and individual job statuses.

### `batch_cancel_jobs`
- **Description**: Cancel a batch operation and optionally cancel running builds.
- **Parameters**:
    - `operation_id` (string): The operation ID to cancel.
    - `cancel_running_builds` (boolean, optional): Attempt to cancel running builds (default: false).
- **Returns**: Cancellation status and results.

### `get_cache_statistics`
- **Description**: Get comprehensive cache performance metrics and utilization statistics.
- **Parameters**: None
- **Returns**: Cache hit rates, utilization percentages, and detailed statistics for all cache types.

### `clear_cache`
- **Description**: Clear caches with fine-grained control for performance management.
- **Parameters**:
    - `cache_type` (string, optional): Type of cache to clear ('all', 'static', 'semi_static', 'dynamic', 'permanent', 'short')
    - `job_name` (string, optional): Clear caches for a specific job only
- **Returns**: Confirmation of cache clearing operation.

### `warm_cache`
- **Description**: Pre-load frequently accessed data into caches for improved performance.
- **Parameters**:
    - `operations` (array, optional): Operations to warm ('server_info', 'job_list', 'queue_info')
- **Returns**: Results of cache warming operations with success/failure status.

### `summarize_build_log`
- **Description**: (Demonstration) Summarizes a build log using a pre-configured LLM prompt.
- **Parameters**:
    - `job_name` (string): The name of the Jenkins job.
    - `build_number` (integer): The build number.
- **Returns**: A placeholder summary and the prompt that would be used.

## 💡 Usage Examples

### With Claude Desktop

Once configured in `claude_desktop_config.json`, you can ask Claude:

> "List all Jenkins jobs"
> 
> "Trigger the deploy-prod job with version parameter 1.2.3"
> 
> "Show me the console log for build #45 of the api-tests job"
> 
> "What's the status of all jobs that failed in the last 24 hours?"

### With MCP Gateway

```bash
# Start server in HTTP mode
jenkins-mcp --transport streamable-http --port 8010

# Example API calls (using curl)
curl -X POST http://localhost:8010/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "list_jobs", "arguments": {}}}'
```

### Batch Operations Example

```bash
# Trigger multiple jobs with different priorities
jenkins-mcp # Then use batch_trigger_jobs tool with:
{
  "operations": [
    {"job_name": "unit-tests", "priority": 1},
    {"job_name": "integration-tests", "priority": 2},
    {"job_name": "deploy-staging", "priority": 3}
  ],
  "max_concurrent": 3,
  "wait_for_completion": true
}
```

## 🔧 Troubleshooting

### Common Issues

**Python Dependencies**
```bash
# If Python packages fail to install automatically
pip install mcp[cli] pydantic requests python-dotenv fastapi cachetools

# Or using uv (recommended)
uv pip install mcp[cli] pydantic requests python-dotenv fastapi cachetools
```

**Permission Issues (Linux/macOS)**
```bash
# If permission denied
sudo npm install -g @ashwinighuge/jenkins-mcp-server

# Or use user-level installation
npm install -g @ashwinighuge/jenkins-mcp-server --prefix ~/.local
```

**Jenkins Connection Issues**
- Verify `JENKINS_URL` is accessible
- Ensure API token is valid and not expired
- Check firewall/proxy settings
- For HTTPS, verify SSL certificates

**2FA/CSRF Issues**
- The server handles CSRF tokens automatically
- For 2FA environments, use API tokens (not passwords)
- Email OTP and similar 2FA methods are supported

### Debug Mode

```bash
# Enable verbose logging
DEBUG=jenkins-mcp jenkins-mcp

# Check Python dependencies
jenkins-mcp --help  # Will validate dependencies
```

## 📊 Performance Features

- **Multi-tier Caching**: Intelligent caching with automatic invalidation
- **Batch Processing**: Parallel job execution with priority queuing
- **Retry Logic**: Exponential backoff for network reliability
- **Connection Pooling**: Efficient HTTP connection management
- **Memory Optimization**: Configurable cache sizes and TTL values

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'Add amazing feature'`
4. Push to branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

## 📄 License

This project is licensed under the Apache 2.0 License - see the [LICENSE](LICENSE) file for details.

## 🙋‍♂️ Support

- **Documentation**: [GitHub README](https://github.com/AshwiniGhuge3012/jenkins-mcp-server#readme)
- **Issues**: [GitHub Issues](https://github.com/AshwiniGhuge3012/jenkins-mcp-server/issues)
- **npm Package**: [@ashwinighuge/jenkins-mcp-server](https://www.npmjs.com/package/@ashwinighuge/jenkins-mcp-server)

## 🏗️ Architecture

Built with:
- **Python 3.12+** - Core server implementation
- **FastMCP** - MCP protocol handling
- **Node.js** - Cross-platform wrapper and process management
- **Pydantic** - Data validation and serialization
- **Requests** - HTTP client with retry logic
- **CacheTools** - Multi-tier performance caching

---


