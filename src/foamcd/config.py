#!/usr/bin/env python3

import os
from typing import Optional, Any
import yaml
from omegaconf import OmegaConf

from .logs import setup_logging

logger = setup_logging()

# Default configuration schema
DEFAULT_CONFIG = {
    "markdown": {
        "project_name": "My lib",  # Official project name
        "project_base_url": None,  # Leading URL section for project files, leave empty to let Hugo figure things out on its own
        "git_repository": None,    # Root git folder, auto-sensed if None
        "git_reference": None,     # Active git reference, priority: tags -> branches -> commit
        "output_path": "markdown_docs", # Where to write the Markdown files, can have files already there
        # Possible context for doc_uri: name, namespace, start_line, end_line, base_url, file_path, full_path,
        # git_reference, git_repository, project_name, project_dir
        "doc_uri": "/api/{{namespace}}_{{name}}", # URI for entities docs
        "filename_uri": "{{git_repository}}/blob/{{git_reference}}/{{file_path}}#L{{start_line}}-L{{end_line}}", # URI for files
        "method_doc_uri": "/api/{{namespace}}_{{parent_name}}", # URI for entities docs
        "unit_test_uri": "{{git_repository}}/blob/{{git_reference}}/{{file_path}}#L{{start_line}}-L{{end_line}}", # URI for unit tests
        "url_mappings_ignore": [ # List of paths to skip mapping, eg. those which are already mapped
            "/api"
        ],
        "url_mappings": [ # List of external dependencies,
            {
                "path": [ # Paths to consider as depencies
                    "/usr/include",
                    "/usr/include/x86_64-linux-gnu",
                ],
                "base_url": "https://devdocs.io/cpp", # the root URI for this dependency, to docs or to code
                # Possible context for pattern: name, namespace, start_line, end_line, base_url, file_path, full_path,
                # git_reference, git_repository, project_name, project_dir
                # These are all specific to each dependency project.
                "pattern": "{{base_url}}/{{name}}",   # Jinja2 template to refer to dependency
                "project_name": "System Libs",        # Optional dependency project name
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
        "entities_to_skip": [         # Regexps for entity names to skip recording to DB, can be dangerous
            "add.*ToDebug",
            "add.*ToTable",
            ".*ConstructorCompatTable",
            ".*ConstructorTable",
            "member",
            "__.*",
            ".*__",
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
                    logger.error(f"Configuration file not found: {config_path}")
                    exit(1)
            except Exception as e:
                logger.error(f"Error loading configuration file: {e}")
                raise
                
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
            if OmegaConf.select(self.config, key):
                return OmegaConf.select(self.config, key)
            return default
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
    def generate_default_config(path: str, overrides: dict = None) -> bool:
        """Generate default configuration file with optional overrides
        
        Args:
            path: Path to save default configuration
            overrides: Dictionary of dot-notation paths to override (e.g., {'database.path': '/tmp/db.sqlite'})
            
        Returns:
            True if successful, False otherwise
        """
        try:
            config = OmegaConf.create(DEFAULT_CONFIG)
            if overrides:
                for key, value in overrides.items():
                    try:
                        import json
                        if (isinstance(value, str) and 
                            ((value.startswith('[') and value.endswith(']')) or
                             (value.startswith('{') and value.endswith('}')))):
                            try:
                                value = json.loads(value.replace("'", "\""))
                            except json.JSONDecodeError:
                                pass
                        elif isinstance(value, str):
                            if value.lower() == 'true':
                                value = True
                            elif value.lower() == 'false':
                                value = False
                            elif value.isdigit():
                                value = int(value)
                            elif value.replace('.', '', 1).isdigit() and value.count('.') == 1:
                                value = float(value)
                            elif ',' in value and not (value.startswith('/') or value.startswith('./')):
                                value = [item.strip() for item in value.split(',')]
                        OmegaConf.update(config, key, value)
                    except Exception as e:
                        logger.warning(f"Failed to override {key} = {value}: {e}")
                        
            with open(path, 'w') as f:
                yaml.dump(OmegaConf.to_container(config), f, default_flow_style=False)
                
            logger.info(f"Generated configuration at {path}")
            if overrides:
                logger.info(f"Applied {len(overrides)} custom overrides")
            return True
        except Exception as e:
            import traceback
            logger.error(f"Error generating configuration: {e}\nTraceback: {traceback.format_exc()}")
            return False
