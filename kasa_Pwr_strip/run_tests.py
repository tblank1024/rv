#!/usr/bin/env python3
"""
Test runner script for Kasa Power Strip controller tests.

This script runs the test suite and provides options for different test configurations.
"""

import sys
import subprocess
import argparse
from pathlib import Path


def install_dependencies():
    """Install test dependencies."""
    print("Installing test dependencies...")
    try:
        subprocess.run([
            sys.executable, "-m", "pip", "install", "-r", "requirements-test.txt"
        ], check=True)
        print("Dependencies installed successfully.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to install dependencies: {e}")
        return False


def run_tests(verbose=False, coverage=False, specific_test=None):
    """Run the test suite."""
    cmd = [sys.executable, "-m", "pytest"]
    
    if verbose:
        cmd.append("-v")
    
    if coverage:
        try:
            # Install coverage if not available
            subprocess.run([sys.executable, "-m", "pip", "install", "pytest-cov"], check=True)
            cmd.extend(["--cov=kasa_ctrl", "--cov-report=html", "--cov-report=term"])
        except subprocess.CalledProcessError:
            print("Warning: Could not install coverage, running tests without coverage")
    
    if specific_test:
        cmd.append(f"test_kasa_ctrl.py::{specific_test}")
    else:
        cmd.append("test_kasa_ctrl.py")
    
    print(f"Running: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"Test execution failed: {e}")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run Kasa Power Strip tests")
    parser.add_argument("-v", "--verbose", action="store_true", 
                       help="Run tests in verbose mode")
    parser.add_argument("-c", "--coverage", action="store_true",
                       help="Run tests with coverage report")
    parser.add_argument("-i", "--install", action="store_true",
                       help="Install test dependencies before running tests")
    parser.add_argument("-t", "--test", type=str,
                       help="Run a specific test class or method")
    
    args = parser.parse_args()
    
    # Change to script directory
    script_dir = Path(__file__).parent
    if script_dir != Path.cwd():
        print(f"Changing directory to: {script_dir}")
        import os
        os.chdir(script_dir)
    
    # Install dependencies if requested
    if args.install:
        if not install_dependencies():
            sys.exit(1)
    
    # Run tests
    success = run_tests(
        verbose=args.verbose,
        coverage=args.coverage,
        specific_test=args.test
    )
    
    if not success:
        print("Tests failed!")
        sys.exit(1)
    
    print("All tests passed!")


if __name__ == "__main__":
    main()