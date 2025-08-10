#!/usr/bin/env node

const { execSync } = require('child_process');
const os = require('os');

console.log('🔍 Jenkins MCP Server - Post-install validation');
console.log('================================================');

// Check Node.js version
function checkNode() {
  const nodeVersion = process.version;
  const major = parseInt(nodeVersion.split('.')[0].slice(1));
  
  if (major < 14) {
    console.error('❌ Node.js version too old:', nodeVersion);
    console.error('   Required: Node.js 14.0.0 or higher');
    console.error('   Please upgrade Node.js: https://nodejs.org/');
    return false;
  } else {
    console.log('✅ Node.js version:', nodeVersion);
    return true;
  }
}

// Check Python installation
function checkPython() {
  const pythonCommands = ['python', 'python3'];
  let pythonFound = false;
  
  console.log('\n🐍 Checking Python installation...');
  
  for (const cmd of pythonCommands) {
    try {
      const version = execSync(`${cmd} --version 2>&1`, { encoding: 'utf8' }).trim();
      const versionMatch = version.match(/Python (\d+)\.(\d+)\.?(\d+)?/);
      
      if (versionMatch) {
        const major = parseInt(versionMatch[1]);
        const minor = parseInt(versionMatch[2]);
        const patch = parseInt(versionMatch[3] || '0');
        
        console.log(`   Found ${cmd}: Python ${major}.${minor}.${patch}`);
        
        if (major >= 3 && minor >= 12) {
          console.log(`✅ ${cmd} meets requirements (3.12+)`);
          pythonFound = true;
          break;
        } else {
          console.log(`⚠️  ${cmd} version too old (need 3.12+)`);
        }
      }
    } catch (error) {
      // Command not found or failed
      continue;
    }
  }
  
  if (!pythonFound) {
    console.error('\n❌ Python 3.12+ not found!');
    console.error('\n📋 Installation instructions:');
    
    const platform = os.platform();
    switch (platform) {
      case 'win32':
        console.error('   Windows:');
        console.error('   1. Download from: https://www.python.org/downloads/');
        console.error('   2. Or use chocolatey: choco install python');
        console.error('   3. Or use winget: winget install Python.Python.3.12');
        break;
      case 'darwin':
        console.error('   macOS:');
        console.error('   1. Download from: https://www.python.org/downloads/');
        console.error('   2. Or use Homebrew: brew install python@3.12');
        console.error('   3. Or use pyenv: pyenv install 3.12');
        break;
      case 'linux':
        console.error('   Linux:');
        console.error('   Ubuntu/Debian: sudo apt update && sudo apt install python3.12 python3.12-pip');
        console.error('   RHEL/CentOS: sudo yum install python312 python312-pip');
        console.error('   Arch: sudo pacman -S python');
        console.error('   Or use pyenv: pyenv install 3.12');
        break;
      default:
        console.error('   Please install Python 3.12+ from: https://www.python.org/downloads/');
    }
    
    console.error('\n   After installation, verify with: python --version or python3 --version');
    return false;
  }
  
  return true;
}

// Check pip availability
function checkPip() {
  const pipCommands = ['pip', 'pip3', 'python -m pip', 'python3 -m pip'];
  
  console.log('\n📦 Checking pip (Python package manager)...');
  
  for (const cmd of pipCommands) {
    try {
      const version = execSync(`${cmd} --version 2>&1`, { encoding: 'utf8', timeout: 5000 }).trim();
      if (version.includes('pip')) {
        console.log(`✅ Found pip: ${cmd}`);
        console.log(`   ${version}`);
        return true;
      }
    } catch (error) {
      continue;
    }
  }
  
  console.error('❌ pip not found!');
  console.error('   pip should be included with Python 3.12+');
  console.error('   If missing, install with: python -m ensurepip --upgrade');
  return false;
}

// Check for alternative package managers
function checkAlternatives() {
  console.log('\n🚀 Checking for alternative Python package managers...');
  
  // Check for uv
  try {
    const uvVersion = execSync('uv --version 2>&1', { encoding: 'utf8', timeout: 3000 }).trim();
    console.log(`✅ Found uv (recommended): ${uvVersion}`);
    console.log('   uv is faster than pip and handles dependencies better');
    console.log('   Install with: curl -LsSf https://astral.sh/uv/install.sh | sh');
    return true;
  } catch (error) {
    // uv not found
  }
  
  // Check for poetry
  try {
    const poetryVersion = execSync('poetry --version 2>&1', { encoding: 'utf8', timeout: 3000 }).trim();
    console.log(`✅ Found poetry: ${poetryVersion}`);
    return true;
  } catch (error) {
    // poetry not found
  }
  
  console.log('ℹ️  No alternative package managers found (optional)');
  console.log('   Consider installing uv for better performance: https://docs.astral.sh/uv/');
  return false;
}

// Test basic functionality
function testBasicFunctionality() {
  console.log('\n🧪 Testing basic Python functionality...');
  
  try {
    // Test if we can run Python and import basic modules
    execSync('python -c "import sys, json, os; print(f\\"Python {sys.version_info.major}.{sys.version_info.minor} ready\\")" 2>&1', 
             { encoding: 'utf8', timeout: 5000 });
    console.log('✅ Python basic functionality test passed');
    return true;
  } catch (error) {
    try {
      execSync('python3 -c "import sys, json, os; print(f\\"Python {sys.version_info.major}.{sys.version_info.minor} ready\\")" 2>&1', 
               { encoding: 'utf8', timeout: 5000 });
      console.log('✅ Python3 basic functionality test passed');
      return true;
    } catch (error2) {
      console.error('❌ Python basic functionality test failed');
      console.error('   This may indicate a Python installation issue');
      return false;
    }
  }
}

// Main validation function
function main() {
  console.log(`Platform: ${os.platform()} ${os.arch()}`);
  console.log(`Node.js: ${process.version}`);
  
  const checks = [
    { name: 'Node.js version', fn: checkNode },
    { name: 'Python installation', fn: checkPython },
    { name: 'pip availability', fn: checkPip },
    { name: 'Alternative managers', fn: checkAlternatives },
    { name: 'Basic functionality', fn: testBasicFunctionality }
  ];
  
  let allPassed = true;
  const results = [];
  
  for (const check of checks) {
    try {
      const passed = check.fn();
      results.push({ name: check.name, passed });
      if (!passed && !check.name.includes('Alternative')) {
        allPassed = false;
      }
    } catch (error) {
      console.error(`❌ Error during ${check.name} check:`, error.message);
      results.push({ name: check.name, passed: false });
      allPassed = false;
    }
  }
  
  // Summary
  console.log('\n📊 Validation Summary');
  console.log('====================');
  
  results.forEach(result => {
    const status = result.passed ? '✅' : '❌';
    console.log(`${status} ${result.name}`);
  });
  
  if (allPassed) {
    console.log('\n🎉 All validation checks passed!');
    console.log('\n🚀 Ready to use Jenkins MCP Server:');
    console.log('   jenkins-mcp --help');
    console.log('\n📖 Documentation:');
    console.log('   https://github.com/AshwiniGhuge3012/jenkins-mcp-server#readme');
  } else {
    console.log('\n⚠️  Some validation checks failed.');
    console.log('   Please address the issues above before using the server.');
    console.log('\n📞 Need help?');
    console.log('   GitHub Issues: https://github.com/AshwiniGhuge3012/jenkins-mcp-server/issues');
    
    // Don't exit with error code to allow npm install to complete
    // Users can still manually fix issues
  }
  
  console.log('\n================================================');
  console.log('Jenkins MCP Server installation validation complete');
}

// Run validation
main();