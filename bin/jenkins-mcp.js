#!/usr/bin/env node

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

// Path to the Python server
const pythonServerPath = path.join(__dirname, '..', 'python', 'jenkins_mcp_server_enhanced.py');

// Check if python3 or python is available and get version
function findPython() {
  const pythonCommands = ['python3', 'python'];
  
  for (const cmd of pythonCommands) {
    try {
      const { execSync } = require('child_process');
      const version = execSync(`${cmd} --version 2>&1`, { encoding: 'utf8' }).trim();
      
      // Check if it's Python 3.12+
      const versionMatch = version.match(/Python (\d+)\.(\d+)/);
      if (versionMatch) {
        const major = parseInt(versionMatch[1]);
        const minor = parseInt(versionMatch[2]);
        
        if (major >= 3 && minor >= 12) {
          console.error(`[Jenkins MCP] Using ${cmd}: ${version}`);
          return cmd;
        } else {
          console.error(`[Jenkins MCP] ${cmd} version ${version} found, but Python 3.12+ required`);
        }
      }
    } catch (error) {
      continue;
    }
  }
  
  console.error('ERROR: Python 3.12+ not found. Please install Python 3.12 or higher.');
  console.error('Visit: https://www.python.org/downloads/');
  process.exit(1);
}

// Check if the Python server file exists
function checkPythonServer() {
  if (!fs.existsSync(pythonServerPath)) {
    console.error(`ERROR: Python server not found at: ${pythonServerPath}`);
    console.error('Please ensure the jenkins-mcp-server package is properly installed.');
    process.exit(1);
  }
}

// Install Python dependencies if needed
function checkPythonDependencies() {
  const requirementsPath = path.join(__dirname, '..', 'requirements.txt');
  
  if (fs.existsSync(requirementsPath)) {
    try {
      const { execSync } = require('child_process');
      console.error('[Jenkins MCP] Checking Python dependencies...');
      
      // Try to import required modules
      execSync(`${pythonCmd} -c "import fastmcp, pydantic, requests, dotenv"`, { stdio: 'ignore' });
      console.error('[Jenkins MCP] Python dependencies OK');
    } catch (error) {
      console.error('[Jenkins MCP] Installing Python dependencies...');
      try {
        execSync(`${pythonCmd} -m pip install fastmcp pydantic requests python-dotenv`, { stdio: 'inherit' });
        console.error('[Jenkins MCP] Dependencies installed successfully');
      } catch (installError) {
        console.error('ERROR: Failed to install Python dependencies');
        console.error('Please run: pip install fastmcp pydantic requests python-dotenv');
        process.exit(1);
      }
    }
  }
}

// Parse command line arguments
function parseArgs() {
  const args = process.argv.slice(2);
  const config = {
    transport: 'stdio', // Default to stdio for MCP
    port: process.env.MCP_PORT || 8010
  };
  
  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case '--transport':
        config.transport = args[++i];
        break;
      case '--port':
        config.port = parseInt(args[++i]);
        break;
      case '--help':
      case '-h':
        console.log(`
Jenkins MCP Server

Usage: jenkins-mcp [options]

Options:
  --transport <type>    Transport type (stdio|streamable-http) [default: stdio]
  --port <number>       Port for HTTP transport [default: 8010]
  --help, -h           Show this help message

Environment Variables:
  JENKINS_URL          Jenkins server URL (required)
  JENKINS_USER         Jenkins username (required)
  JENKINS_API_TOKEN    Jenkins API token (required)
  MCP_PORT             Default port for HTTP transport

Examples:
  jenkins-mcp                                    # STDIO mode (for Claude Desktop)
  jenkins-mcp --transport streamable-http       # HTTP mode (for MCP Gateway)
  jenkins-mcp --transport streamable-http --port 8080
        `);
        process.exit(0);
        break;
    }
  }
  
  return config;
}

// Validate environment variables
function validateEnvironment() {
  const required = ['JENKINS_URL', 'JENKINS_USER', 'JENKINS_API_TOKEN'];
  const missing = required.filter(env => !process.env[env]);
  
  if (missing.length > 0) {
    console.error('ERROR: Missing required environment variables:');
    missing.forEach(env => console.error(`  - ${env}`));
    console.error('\nPlease set these environment variables or create a .env file');
    console.error('\nExample:');
    console.error('  JENKINS_URL="http://your-jenkins:8080"');
    console.error('  JENKINS_USER="your-username"');
    console.error('  JENKINS_API_TOKEN="your-api-token"');
    process.exit(1);
  }
}

// Main execution
const pythonCmd = findPython();
checkPythonServer();
checkPythonDependencies();

const config = parseArgs();
validateEnvironment();

console.error(`[Jenkins MCP] Starting Jenkins MCP Server in ${config.transport} mode...`);
console.error(`[Jenkins MCP] Jenkins URL: ${process.env.JENKINS_URL}`);

// Build Python command arguments
const pythonArgs = [pythonServerPath];

if (config.transport !== 'stdio') {
  pythonArgs.push('--transport', config.transport);
}

if (config.transport === 'streamable-http') {
  pythonArgs.push('--port', config.port.toString());
}

// Spawn the Python process
const pythonProcess = spawn(pythonCmd, pythonArgs, {
  stdio: ['pipe', 'pipe', 'inherit'], // stdin, stdout, stderr
  env: {
    ...process.env,
    // Ensure all environment variables are passed through
  }
});

// Handle Python process errors
pythonProcess.on('error', (error) => {
  console.error(`[Jenkins MCP] Failed to start Python server: ${error.message}`);
  process.exit(1);
});

// Pipe stdin/stdout for MCP communication (stdio mode)
if (config.transport === 'stdio') {
  process.stdin.pipe(pythonProcess.stdin);
  pythonProcess.stdout.pipe(process.stdout);
}

// Handle process termination gracefully
pythonProcess.on('close', (code, signal) => {
  if (signal) {
    console.error(`[Jenkins MCP] Server terminated by signal: ${signal}`);
  } else if (code !== 0) {
    console.error(`[Jenkins MCP] Server exited with code: ${code}`);
  }
  process.exit(code || 0);
});

// Forward termination signals
process.on('SIGINT', () => {
  console.error('\n[Jenkins MCP] Received SIGINT, shutting down...');
  pythonProcess.kill('SIGINT');
});

process.on('SIGTERM', () => {
  console.error('[Jenkins MCP] Received SIGTERM, shutting down...');
  pythonProcess.kill('SIGTERM');
});

// Handle uncaught exceptions
process.on('uncaughtException', (error) => {
  console.error(`[Jenkins MCP] Uncaught exception: ${error.message}`);
  pythonProcess.kill('SIGTERM');
  process.exit(1);
});

process.on('unhandledRejection', (reason, promise) => {
  console.error(`[Jenkins MCP] Unhandled rejection at:`, promise, 'reason:', reason);
  pythonProcess.kill('SIGTERM');
  process.exit(1);
});

console.error('[Jenkins MCP] Server started successfully');