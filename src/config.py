#!/usr/bin/env python3

import os
from typing import Optional, Any
import yaml
from omegaconf import OmegaConf

from logs import setup_logging

logger = setup_logging()

# Default configuration schema
DEFAULT_CONFIG = {
    "markdown": {
        "project_name": "My lib",  # Official project name
        "git_repository": None,    # Root git folder, auto-sensed if None
        "git_reference": None,     # Active git reference, priority: tags -> branches -> commit
        "output_path": "markdown_docs", # Where to write the Markdown files, can have files already there
        "doc_uri": "/api/{{namespace}}_{{name}}", # URI for entities docs
        "dependencies": [ # List of external dependencies, NOT YET ACTIVE
            {
                "path": [ # Paths to consider as depencies
                    "/usr/include",
                    "/usr/include/x86_64-linux-gnu",
                ],
                "dependency_url": "https://devdocs.io/cpp", # the root URI for this dependency, to docs or to code
                "pattern": "{{dependency_url}}/{{name}}",   # Jinja2 template to refer to dependency
            },
        ],
        "frontmatter": {                                # Control over what to put in the frontmatters
            "index": {                                  # Index level
                "filename": "_index.md",                
                "date": "xxx-xx-xx",
                "description": "My library's tagline",
                "draft": False,
                "weight": 2,
                "layout": "library",                      # Important for Hugo to figure things out
                "entry_points": True,                     # Enable Entry points listing to project
                "rts_entry_points": True,                 # Enable RTS-powered entry points
                "manual_entry_points": [],                # List of classes, by name, as extra entry points
                "namespaces": True,                       # List namespaces in index
                "classes_and_class_templates": True,      # List classes in index
                "functions_and_function_templates": True, # List functions in index
                "concepts": True,                         # List concepts
                "cpp_modules": False,                     # List c++ modules, NOT YET ACTIVE
            },
            "entities": {                                 # Settings for documenting entities
                "complain_about": [                       # Overview of entity readiness/quality, NOT YET ACTIVE
                    "level_of_extensibility",
                    "level_of_configurability",
                    "level_of_testability",
                    "rule_of_5_compliance",
                    "sfinae_usage",
                    "crtp_usag",
                ],
                "unit_tests": True,                       # Refer to potential unit tests in class descriptions
                "unit_tests_compile_commands_dir": None,  # Path to compile_commands folder for the unit testing code
                "unit_test_linkage_pattern": "{{git_repository}}/blob/{{git_reference}}/{{file_path}}#L{{start_line}}-L{{end_line}}",
                "knowledge_requirements": True,           # Overview of C++ features an entity leverage
                "contributors_from_git": True,            # Contributers list from Git
            },
        },
    },
    "logging": {
        "level": "INFO",        # Logging level (DEBUG, INFO, WARNING, ERROR)
        "colored": True,        # Whether to use colored logging
        "file": None,           # Log file path (None = console only)
    },
    "database": {
        "path": "docs.db",      # SQLite database path
        "create_tables": True   # Whether to create tables if they don't exist
    },
    "parser": {
        "libclang_path": None,        # Path to libclang library if not in standard locations
        "compile_commands_dir": None, # Path to folder containing compile_commands.json
        "prefixes_to_skip": [         # Path prefixes to skip when parsing (but keep references for their entities)
            "/usr/include",
            "/usr/lib",
            "/usr/include/x86_64-linux-gnu"
        ],
        "plugins": {
            "enabled": True,          # Whether to enable the plugin system
            "disabled_plugins": [],    # List of plugin names to disable
            "only_plugins": []         # Whitelist of plugin names to enable (if empty, all non-disabled plugins are enabled)
        },
        # The rest of parser parameters are deduced from compile_commands.json file if supplied
        "cpp_standard": "c++20",      # C++ standard version to use, optional
        "include_paths": [],          # Additional include paths for compilation, optional
        "compile_flags": [],          # Additional compilation flags
        "target_files": [],           # Files to parse
        "plugin_dirs": [],            # Additional plugin directories to search
    },
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
