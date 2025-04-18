#!/usr/bin/env python3
"""
Configuration file for pytest.
Contains fixtures and utilities for testing the foamCD project.
"""

import os
import sys
from pathlib import Path

# Add the src directory to the Python path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.append(str(src_path))

# Useful constants
FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURES_COMPILE_COMMANDS = FIXTURES_DIR / "compile_commands.json"
