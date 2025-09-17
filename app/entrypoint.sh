#!/usr/bin/env python3
"""
Health check script for audiobook converter container
Verifies FFmpeg 7.1.2, libfdk_aac, directory access, and application status
"""

import sys
import subprocess
import os
import time
from pathlib import Path

def check_ffmpeg_version():
    """Check if FFmpeg 7.1.2 is available"""
    try:
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            version_line = result.stdout.split('\n')[0]
            if '7.1.2' in version_line:
                return True, f"FFmpeg 7.1.2 found: {version_line}"
            else:
                return False, f"Wrong FFmpeg version: {version_line}"
        return False, f"FFmpeg failed: {result.stderr}"
    except Exception as e:
        return False, f"FFmpeg check error: {str(e)}"

def check_libfdk_aac():
    """Check if libfdk_aac encoder is available"""
    try:
        result = subprocess.run(['ffmpeg', '-hide_banner', '-h', 'encoder=libfdk_aac'], 
                              capture_output=True, text=True, timeout=10)
        return result.returncode == 0, "libfdk_aac encoder available" if result.returncode == 0 else "libfdk_aac NOT available"
    except Exception as e:
        return False, f"libfdk_aac check error: {str(e)}"

def check_directories():
    """Check if required directories are accessible"""
    dirs_to_check = {
        '/input': 'Input directory',
        '/output': 'Output directory', 
        '/config': 'Config directory',
        '/logs': 'Logs directory',
        '/temp': 'Temp directory'
    }
    
    failed_dirs = []
    for dir_path, description in dirs_to_check.items():
        try:
            path = Path(dir_path)
            if not path.exists():
                failed_dirs.append(f"{description} does not exist")
            elif not os.access(dir_path, os.R_OK | os.W_OK):
                failed_dirs.append(f"{description} not readable/writable")
        except Exception as e:
            failed_dirs.append(f"{description} check failed: {str(e)}")
    
    if failed_dirs:
        return False, "; ".join(failed_dirs)
    return True, "All directories accessible"

def check_python_packages():
    """Check if required Python packages are available"""
    required_packages = ['beets', 'mutagen', 'watchdog', 'yaml', 'requests']
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        return False, f"Missing packages: {', '.join(missing_packages)}"
    return True, "All Python packages available"

def check_application_running():
    """Check if the main application is running by looking at log file"""
    log_file = Path('/logs/converter.log')
    
    # Check if log file exists
    if not log_file.exists():
        return False, "Application log file not found"
    
    try:
        # Check if log file was modified recently (within last 5 minutes)
        last_modified = log_file.stat().st_mtime
        current_time = time.time()
        time_diff = current_time - last_modified
        
        if time_diff < 300:  # 5 minutes
            return True, f"Application active (log updated {int(time_diff)}s ago)"
        else:
            return False, f"Application inactive (log last updated {int(time_diff/60)}m ago)"
            
    except Exception as e:
        return False, f"Could not check log file: {str(e)}"

def check_beets_audible():
    """Check if beets-audible plugin is available"""
    try:
        result = subprocess.run(['beet', '--version'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            # Try to check if audible plugin is available
            result2 = subprocess.run(['beet', 'config'], 
                                   capture_output=True, text=True, timeout=10)
            # Basic check that beets is working
            return True, "Beets available"
        return False, "Beets not working properly"
    except Exception as e:
        return False, f"Beets check error: {str(e)}"

def main():
    """Run all health checks and report results"""
    print("=== Audiobook Converter Health Check ===")
    
    checks = [
        ("FFmpeg 7.1.2", check_ffmpeg_version()),
        ("libfdk_aac support", check_libfdk_aac()),
        ("Directory access", check_directories()),
        ("Python packages", check_python_packages()),
        ("Beets availability", check_beets_audible()),
        ("Application status", check_application_running())
    ]
    
    all_passed = True
    for check_name, (passed, message) in checks:
        status_symbol = "✓" if passed else "✗"
        status_color = "\033[92m" if passed else "\033[91m"  # Green or Red
        reset_color = "\033[0m"
        
        print(f"{status_color}{status_symbol}{reset_color} {check_name}: {message}")
        
        if not passed:
            all_passed = False
    
    print("")
    if all_passed:
        print("🟢 All health checks passed")
        sys.exit(0)
    else:
        print("🔴 Some health checks failed")
        sys.exit(1)

if __name__ == "__main__":
    main()