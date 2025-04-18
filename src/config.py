#!/usr/bin/env python3

import os
from typing import Optional, Any
import yaml
from omegaconf import OmegaConf

from logs import setup_logging

logger = setup_logging()

# Default configuration schema
DEFAULT_CONFIG = {
    "parser": {
        "libclang_path": None,        # Path to libclang library if not in standard locations
        "compile_commands_dir": None, # Path to folder containing compile_commands.json
        "prefixes_to_skip": [         # Path prefixes to skip when parsing (but keep references for their entities)
            "/usr/include",
            "/usr/lib",
            "/usr/include/x86_64-linux-gnu"
        ],
        # The rest of parser parameters are deduced from compile_commands.json file if supplied
        "cpp_standard": "c++20",      # C++ standard version to use, optional
        "include_paths": [],          # Additional include paths for compilation, optional
        "compile_flags": [],          # Additional compilation flags
        "target_files": [],           # Files to parse
    },
    "database": {
        "path": "docs.db",      # SQLite database path
        "create_tables": True   # Whether to create tables if they don't exist
    },
    "logging": {
        "level": "INFO",        # Logging level (DEBUG, INFO, WARNING, ERROR)
        "colored": True,        # Whether to use colored logging
        "file": None            # Log file path (None = console only)
    },
    "features": {
        "detect_inheritance": True,      # Detect inheritance relationships
        "detect_virtuals": True,         # Detect virtual and pure virtual methods
        "parse_doc_comments": True,      # Parse documentation comments
        "access_level_grouping": True    # Group class members by access level
    }
}

class Config:
    """Configuration handler for FoamCD through OmegaConf"""
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize configuration
        
        Args:
            config_path: Path to YAML configuration file
        """
        # Load and merge with default configuration
        self.config = OmegaConf.create(DEFAULT_CONFIG)
        if config_path:
            try:
                if os.path.exists(config_path):
                    user_config = OmegaConf.load(config_path)
                    self.config = OmegaConf.merge(self.config, user_config)
                    logger.info(f"Loaded configuration from {config_path}")
                else:
                    logger.warning(f"Configuration file not found: {config_path}")
            except Exception as e:
                import traceback
                logger.error(f"Error loading configuration file: {e}\nTraceback: {traceback.format_exc()}")
                
        verbose = self.config.logging.level.upper() == "DEBUG"
        setup_logging(verbose=verbose)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by key path
        
        Args:
            key: Dot-separated path to configuration value
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        try:
            return OmegaConf.select(self.config, key)
        except Exception:
            return default
    
    def save(self, path: str) -> bool:
        """Save current configuration to a YAML file
        
        Args:
            path: Path to save configuration file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with open(path, 'w') as f:
                yaml.dump(OmegaConf.to_container(self.config), f, default_flow_style=False)
            logger.info(f"Saved configuration to {path}")
            return True
        except Exception as e:
            import traceback
            logger.error(f"Error saving configuration: {e}\nTraceback: {traceback.format_exc()}")
            return False
    
    @staticmethod
    def generate_default_config(path: str) -> bool:
        """Generate default configuration file
        
        Args:
            path: Path to save default configuration
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with open(path, 'w') as f:
                yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False)
            logger.info(f"Generated default configuration at {path}")
            return True
        except Exception as e:
            import traceback
            logger.error(f"Error generating default configuration: {e}\nTraceback: {traceback.format_exc()}")
            return False
