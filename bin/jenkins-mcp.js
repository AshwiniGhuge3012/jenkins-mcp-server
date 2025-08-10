#!/usr/bin/env node

const { spawn, execSync } = require('child_process');
const path = require('path');
const fs = require('fs');

// Path to the Python server
const pythonServerPath = path.join(__dirname, '..', 'python', 'jenkins_mcp_server_enhanced.py');

// Check if python3 or python is available and get version
function findPython() {
  const pythonCommands = ['python', 'python3'];
  
  for (const cmd of pythonCommands) {
    try {
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
function checkPythonDependencies(pythonCmd) {
  try {
    // Try to import required modules
    execSync(`${pythonCmd} -c "import mcp, pydantic, requests, dotenv, fastapi, cachetools"`, { stdio: 'ignore' });
    console.error('[Jenkins MCP] Python dependencies OK');
  } catch (error) {
    console.error('[Jenkins MCP] Missing Python dependencies. Installing...');
    
    const packages = ['mcp[cli]>=1.11.0', 'pydantic', 'requests>=2.32.4', 'python-dotenv', 'fastapi', 'cachetools>=5.5.0'];
    
    try {
      // Try to install using pip
      execSync(`${pythonCmd} -m pip install ${packages.join(' ')}`, { 
        stdio: 'inherit',
        env: { ...process.env, PIP_BREAK_SYSTEM_PACKAGES: '1' }
      });
      console.error('[Jenkins MCP] Dependencies installed successfully');
    } catch (installError) {
      // If pip fails, try with --user flag
      try {
        execSync(`${pythonCmd} -m pip install --user ${packages.join(' ')}`, { 
          stdio: 'inherit' 
        });
        console.error('[Jenkins MCP] Dependencies installed successfully (user mode)');
      } catch (userInstallError) {
        console.error('\nERROR: Failed to install Python dependencies automatically.');
        console.error('Please install them manually:');
        console.error(`  ${pythonCmd} -m pip install ${packages.join(' ')}`);
        console.error('\nOr if you get a system packages error:');
        console.error(`  ${pythonCmd} -m pip install --user ${packages.join(' ')}`);
        console.error('\nOr using uv (recommended):');
        console.error('  uv pip install mcp[cli] requests pydantic python-dotenv fastapi cachetools');
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
    port: process.env.MCP_PORT || 8010,
    host: process.env.MCP_HOST || '0.0.0.0'
  };
  
  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case '--transport':
        config.transport = args[++i];
        break;
      case '--port':
        config.port = parseInt(args[++i]);
        break;
      case '--host':
        config.host = args[++i];
        break;
      case '--help':
      case '-h':
        console.log(`
Jenkins MCP Server v1.0.0

An MCP server for interacting with Jenkins CI/CD systems. Provides comprehensive
job management, build status monitoring, pipeline execution tracking, artifact
handling, and batch operations through the Model Context Protocol.

Usage: jenkins-mcp [options]

Options:
  --transport <type>    Transport type (stdio|streamable-http) [default: stdio]
  --port <number>       Port for HTTP transport [default: 8010]
  --host <address>      Host address for HTTP transport [default: 0.0.0.0]
  --help, -h           Show this help message

Environment Variables:
  JENKINS_URL          Jenkins server URL (required)
  JENKINS_USER         Jenkins username (required)
  JENKINS_API_TOKEN    Jenkins API token (required)
  MCP_PORT             Default port for HTTP transport
  MCP_HOST             Default host for HTTP transport

Required Jenkins Configuration:
  - Jenkins 2.401+ recommended
  - API token authentication enabled
  - For 2FA environments: email OTP or similar supported
  - CSRF protection supported (automatic crumb handling)

Examples:
  jenkins-mcp                                    # STDIO mode (for Claude Desktop)
  jenkins-mcp --transport streamable-http       # HTTP mode (for MCP Gateway)
  jenkins-mcp --transport streamable-http --port 8080 --host localhost

Claude Desktop Configuration:
  Add to your claude_desktop_config.json:
  
  {
    "mcpServers": {
      "jenkins": {
        "command": "jenkins-mcp",
        "env": {
          "JENKINS_URL": "http://your-jenkins:8080",
          "JENKINS_USER": "your-username",
          "JENKINS_API_TOKEN": "your-api-token"
        }
      }
    }
  }

Features:
  • Job Management: Trigger, list, search, and monitor Jenkins jobs
  • Build Status: Real-time build status and console log access
  • Pipeline Support: Stage-by-stage pipeline execution tracking
  • Artifact Management: List, download, and search build artifacts
  • Batch Operations: Parallel job execution with priority queuing
  • Performance Caching: Multi-tier intelligent caching system
  • Advanced Filtering: Filter jobs by status, results, dates, and more
  • CSRF Protection: Automatic crumb token handling for secure operations
  • Nested Job Support: Full support for Jenkins folder structures

Python Requirements:
  - Python 3.12 or higher
  - Required packages: mcp[cli], pydantic, requests, python-dotenv, fastapi, cachetools
        `);
        process.exit(0);
        break;
    }
  }
  
  return config;
}

// Validate environment variables
function validateEnvironment() {
  // First, try to load from .env file if it exists
  const envPath = path.join(process.cwd(), '.env');
  if (fs.existsSync(envPath)) {
    try {
      // Try to use dotenv if available
      try {
        require('dotenv').config({ path: envPath });
        console.error('[Jenkins MCP] Loaded configuration from .env file');
      } catch (dotenvError) {
        // Manual parsing fallback
        const envContent = fs.readFileSync(envPath, 'utf8');
        envContent.split('\n').forEach(line => {
          const match = line.match(/^([^=]+)=(.*)$/);
          if (match) {
            const key = match[1].trim();
            const value = match[2].trim().replace(/^["']|["']$/g, '');
            if (!process.env[key]) {
              process.env[key] = value;
            }
          }
        });
        console.error('[Jenkins MCP] Loaded configuration from .env file (manual parse)');
      }
    } catch (error) {
      console.error(`[Jenkins MCP] Warning: Could not load .env file: ${error.message}`);
    }
  }
  
  const required = ['JENKINS_URL', 'JENKINS_USER', 'JENKINS_API_TOKEN'];
  const missing = required.filter(env => !process.env[env]);
  
  if (missing.length > 0) {
    console.error('ERROR: Missing required environment variables:');
    missing.forEach(env => console.error(`  - ${env}`));
    console.error('\nPlease set these environment variables or create a .env file in your working directory.');
    console.error('\nExample .env file:');
    console.error('  JENKINS_URL="http://your-jenkins-server:8080"');
    console.error('  JENKINS_USER="your-username"');
    console.error('  JENKINS_API_TOKEN="your-api-token"');
    console.error('\nTo get an API token:');
    console.error('  1. Log into Jenkins');
    console.error('  2. Go to User Settings > Configure');
    console.error('  3. Add API Token > Generate');
    console.error('  4. Copy the generated token');
    process.exit(1);
  }
  
  // Validate Jenkins URL format
  const jenkinsUrl = process.env.JENKINS_URL;
  if (!jenkinsUrl.startsWith('http://') && !jenkinsUrl.startsWith('https://')) {
    console.error('ERROR: JENKINS_URL must start with http:// or https://');
    console.error(`Current value: ${jenkinsUrl}`);
    process.exit(1);
  }
}

// Main execution
function main() {
  try {
    const pythonCmd = findPython();
    checkPythonServer();
    checkPythonDependencies(pythonCmd);

    const config = parseArgs();
    validateEnvironment();

    console.error(`[Jenkins MCP] Starting Jenkins MCP Server in ${config.transport} mode...`);
    console.error(`[Jenkins MCP] Jenkins URL: ${process.env.JENKINS_URL}`);
    console.error(`[Jenkins MCP] Server Version: 1.0.0`);

    // Build Python command arguments
    const pythonArgs = [pythonServerPath];

    if (config.transport !== 'stdio') {
      pythonArgs.push('--transport', config.transport);
    }

    if (config.transport === 'streamable-http') {
      pythonArgs.push('--port', config.port.toString());
      if (config.host !== '0.0.0.0') {
        pythonArgs.push('--host', config.host);
      }
    }

    // Spawn the Python process
    const pythonProcess = spawn(pythonCmd, pythonArgs, {
      stdio: ['pipe', 'pipe', 'inherit'], // stdin, stdout, stderr
      env: {
        ...process.env,
        // Ensure all environment variables are passed through
        PYTHONUNBUFFERED: '1', // Ensure real-time output
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
    } else {
      // For HTTP mode, show server startup messages
      pythonProcess.stdout.on('data', (data) => {
        console.error(`[Jenkins MCP] ${data.toString().trim()}`);
      });
    }

    // Handle process termination gracefully
    pythonProcess.on('close', (code, signal) => {
      if (signal) {
        console.error(`[Jenkins MCP] Server terminated by signal: ${signal}`);
      } else if (code !== 0) {
        console.error(`[Jenkins MCP] Server exited with code: ${code}`);
      } else {
        console.error('[Jenkins MCP] Server shut down gracefully');
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
    
    // Keep the process alive in HTTP mode
    if (config.transport !== 'stdio') {
      console.error(`[Jenkins MCP] Server running on ${config.host}:${config.port}`);
      console.error('[Jenkins MCP] Press Ctrl+C to stop');
    }
  } catch (error) {
    console.error(`[Jenkins MCP] Fatal error: ${error.message}`);
    process.exit(1);
  }
}

// Run main function
main();