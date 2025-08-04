# Jenkins MCP Server

An MCP (Model Context Protocol) server for interacting with a Jenkins CI/CD server. This server allows you to trigger jobs, check build statuses, and manage your Jenkins instance through Claude Desktop or other MCP clients.

## Features

- **Job Management**: Trigger, list, and get detailed information about Jenkins jobs
- **Build Status**: Check the status of specific builds and retrieve console logs
- **Queue Management**: View items currently in the build queue
- **Server Information**: Get basic information about the connected Jenkins server
- **LLM Integration**: Includes prompts and configurations for summarizing build logs
- **Transport Support**: Supports both STDIO and HTTP transports
- **Input Validation**: Uses Pydantic for robust input validation and error handling
- **Easy Installation**: Install via npm/npx for seamless integration with Claude Desktop

## Requirements

- **Node.js**: 14.0.0 or higher
- **Python**: 3.12 or higher
- A running Jenkins instance with API access

## Quick Start

### Using with Claude Desktop (Recommended)

1. **Configure Claude Desktop**: Add this to your Claude Desktop configuration:

```json
{
  "mcpServers": {
    "jenkins": {
      "command": "npx",
      "args": ["-y", "@ashwini/jenkins-mcp-server"],
      "env": {
        "JENKINS_URL": "http://your-jenkins-instance:8080",
        "JENKINS_USER": "your-username",
        "JENKINS_API_TOKEN": "your-api-token"
      }
    }
  }
}
```

2. **Restart Claude Desktop**: The server will be automatically installed and started

### Manual Installation

```bash
# Install globally
npm install -g @ashwini/jenkins-mcp-server

# Or run directly with npx
npx @ashwini/jenkins-mcp-server --help
```

## Configuration

### Environment Variables

Create a `.env` file in your project root or set these environment variables:

```bash
JENKINS_URL="http://your-jenkins-instance:8080"
JENKINS_USER="your-username"
JENKINS_API_TOKEN="your-api-token"
MCP_PORT=8010  # Optional: for HTTP mode
```

### Jenkins API Token

1. Log into your Jenkins instance
2. Go to **Manage Jenkins** → **Manage Users** → Click on your username
3. Click **Configure** → **Add new Token**
4. Generate and copy the API token

## Usage

### STDIO Mode (Default - for Claude Desktop)

```bash
jenkins-mcp
```

### HTTP Mode (for MCP Gateway)

```bash
jenkins-mcp --transport streamable-http --port 8010
```

### Command Line Options

```bash
jenkins-mcp [options]

Options:
  --transport <type>    Transport type (stdio|streamable-http) [default: stdio]
  --port <number>       Port for HTTP transport [default: 8010]
  --help, -h           Show this help message
```

## Available Tools

### 1. `jenkins_server.trigger_job`
Trigger a Jenkins job with optional parameters.

**Parameters:**
- `job_name` (string): The name of the Jenkins job
- `params` (object, optional): Job parameters as a JSON object

**Example:**
```json
{
  "job_name": "my-deployment-job",
  "params": {
    "branch": "main",
    "environment": "staging",
    "deploy": true
  }
}
```

### 2. `jenkins_server.get_job_info`
Get detailed information about a Jenkins job.

**Parameters:**
- `job_name` (string): The name of the Jenkins job

### 3. `jenkins_server.get_build_status`
Get the status of a specific build.

**Parameters:**
- `job_name` (string): The name of the Jenkins job
- `build_number` (integer): The build number

### 4. `jenkins_server.get_console_log`
Retrieve the console log for a specific build.

**Parameters:**
- `job_name` (string): The name of the Jenkins job
- `build_number` (integer): The build number
- `start` (integer, optional): Starting byte position for log fetching

### 5. `jenkins_server.list_jobs`
List all available jobs on the Jenkins server.

**Parameters:** None

### 6. `jenkins_server.get_queue`
Get information about builds currently in the queue.

**Parameters:** None

### 7. `jenkins_server.get_server_info`
Get basic information about the Jenkins server.

**Parameters:** None

### 8. `jenkins_server.summarize_build_log`
Summarize a build log using LLM integration (demonstration feature).

**Parameters:**
- `job_name` (string): The name of the Jenkins job
- `build_number` (integer): The build number

## Examples with Claude Desktop

Once configured, you can ask Claude to help with Jenkins tasks:

- *"Can you list all the Jenkins jobs?"*
- *"Trigger the deployment job for the main branch"*
- *"What's the status of build #123 for the test-suite job?"*
- *"Show me the console log for the last failed build"*
- *"What's currently in the Jenkins build queue?"*

## Troubleshooting

### Python Dependencies

The server automatically installs required Python dependencies:
- `fastmcp`
- `pydantic`
- `requests`
- `python-dotenv`

If automatic installation fails, install manually:
```bash
pip install fastmcp pydantic requests python-dotenv
```

### Common Issues

1. **Python Version**: Ensure you have Python 3.12 or higher
2. **Jenkins Connectivity**: Verify your Jenkins URL and credentials
3. **API Token**: Make sure you're using an API token, not a password
4. **Firewall**: Ensure Claude Desktop can access your Jenkins instance

### Debug Mode

Set environment variable for verbose logging:
```bash
DEBUG=1 jenkins-mcp
```

## Development

### Local Development

1. Clone the repository:
```bash
git clone https://github.com/AshwiniGhuge3012/jenkins-mcp-server.git
cd jenkins-mcp-server
```

2. Create the npm package structure:
```bash
mkdir -p bin python
```

3. Copy your Python server to `python/jenkins_mcp_server_enhanced.py`

4. Install and test locally:
```bash
npm link
jenkins-mcp --help
```

### Publishing

```bash
npm login
npm publish --access public
```

## License

This project is licensed under the Apache 2.0 License - see the [LICENSE](LICENSE) file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## Support

- **Issues**: [GitHub Issues](https://github.com/AshwiniGhuge3012/jenkins-mcp-server/issues)
- **Documentation**: [MCP Documentation](https://modelcontextprotocol.io/docs)
- **Claude Desktop**: [Claude Desktop MCP Guide](https://docs.anthropic.com/claude/docs/mcp)

## Changelog

### v1.0.0
- Initial release with npm/npx support
- STDIO and HTTP transport support
- Automatic Python dependency management
- Full Jenkins API integration
- Claude Desktop compatibility