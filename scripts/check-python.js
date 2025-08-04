#!/usr/bin/env node

const { execSync } = require('child_process');

function checkPython() {
  const pythonCommands = ['python', 'python3'];
  let foundPython = false;
  
  console.log('Checking for Python 3.12+ installation...');
  
  for (const cmd of pythonCommands) {
    try {
      const version = execSync(`${cmd} --version 2>&1`, { encoding: 'utf8' }).trim();
      const versionMatch = version.match(/Python (\d+)\.(\d+)/);
      
      if (versionMatch) {
        const major = parseInt(versionMatch[1]);
        const minor = parseInt(versionMatch[2]);
        
        if (major >= 3 && minor >= 12) {
          console.log(`✓ Found ${version}`);
          foundPython = true;
          break;
        } else {
          console.log(`✗ Found ${version}, but Python 3.12+ is required`);
        }
      }
    } catch (error) {
      // Command not found, continue
    }
  }
  
  if (!foundPython) {
    console.warn('\n⚠️  WARNING: Python 3.12+ is required but not found.');
    console.warn('   Please install Python 3.12 or higher to use this package.');
    console.warn('   Download from: https://www.python.org/downloads/\n');
    console.warn('   After installing Python, you may need to install the required packages:');
    console.warn('   pip install fastmcp pydantic requests python-dotenv fastapi\n');
  } else {
    console.log('\nPython dependency check completed successfully.\n');
  }
}

// Only run the check during npm install, not during development
if (process.env.npm_lifecycle_event === 'postinstall') {
  checkPython();
}