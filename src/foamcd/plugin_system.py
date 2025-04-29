#!/usr/bin/env python3

import os
import sys
import importlib.util
import inspect
from typing import Dict, List, Any, Type, Optional, Set
from pathlib import Path

from .feature_detectors import FeatureDetector
from .logs import setup_logging

logger = setup_logging()

class PluginManager:
    """Manages DSL feature detector plugins and custom entity field definitions"""
    
    def __init__(self, plugin_dirs: List[str] = None, config: Dict[str, Any] = None):
        """Initialize the plugin manager
        
        Args:
            plugin_dirs: List of directories to search for plugins
            config: Plugin configuration options with keys:
                   - enabled: Whether plugins are enabled at all
                   - disabled_plugins: List of plugin names to disable
                   - only_plugins: Whitelist of plugins to enable (if empty, all non-disabled are enabled)
        """
        self.plugin_dirs = plugin_dirs or []
        
        potential_plugin_dirs = [
            os.path.realpath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins")),
            os.path.realpath(os.path.join(os.path.dirname(__file__), "../plugins")),
            os.path.realpath(os.path.join(os.path.dirname(__file__), "../../plugins")),
            os.path.realpath(os.path.join(os.path.dirname(__file__), "plugins"))
        ]
        
        for plugin_dir in potential_plugin_dirs:
            if os.path.exists(plugin_dir) and os.path.isdir(plugin_dir) and plugin_dir not in self.plugin_dirs:
                self.plugin_dirs.append(plugin_dir)
                logger.debug(f"Found plugins directory: {plugin_dir}")
        self.detectors: Dict[str, FeatureDetector] = {}
        self.custom_entity_fields: Dict[str, Dict[str, Any]] = {}
        self.loaded_plugin_files: Set[str] = set()
        self.supported_field_types = ["TEXT", "INTEGER", "REAL", "BOOLEAN", "JSON"]
        self.config = config or {}
        self.plugins_enabled = self.config.get("enabled", True)
        self.disabled_plugins = set(self.config.get("disabled_plugins", []))
        self.only_plugins = set(self.config.get("only_plugins", []))
        
    def discover_plugins(self):
        """Discover and load all plugins from the plugin directories"""
        for plugin_dir in self.plugin_dirs:
            plugin_path = Path(plugin_dir)
            if not plugin_path.exists():
                logger.warning(f"Plugin directory does not exist: {plugin_dir}")
                continue
            logger.info(f"Searching for plugins in {plugin_dir}")
            python_files = list(plugin_path.glob("**/*.py"))
            for plugin_file in python_files:
                if plugin_file.name.startswith("_"):
                    continue
                try:
                    self.load_plugin(str(plugin_file))
                except Exception as e:
                    logger.error(f"Failed to load plugin {plugin_file}: {e}")
    
    def load_plugin(self, plugin_path: str) -> bool:
        """Load a plugin from the given path
        
        Args:
            plugin_path: Path to the plugin file
            
        Returns:
            True if plugin loaded successfully, False otherwise
        """
        if plugin_path in self.loaded_plugin_files:
            return True
        
        logger.debug(f"Attempting to load plugin: {plugin_path}")
            
        try:
            abs_plugin_path = os.path.abspath(plugin_path)
            module_name = Path(abs_plugin_path).stem
            spec = importlib.util.spec_from_file_location(module_name, abs_plugin_path)
            if spec is None:
                logger.error(f"Failed to create spec for plugin: {abs_plugin_path}")
                return False
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            
            try:
                spec.loader.exec_module(module)
            except Exception as e:
                return False
            detector_classes = []
            for _, item in inspect.getmembers(module, inspect.isclass):
                try:
                    if (issubclass(item, FeatureDetector) and 
                        item.__module__ == module.__name__ and
                        item is not FeatureDetector):
                        detector_classes.append(item)
                except TypeError as e:
                    pass
            
            if not detector_classes:
                logger.warning(f"No detector classes found in plugin: {plugin_path}")
                return False
            for detector_class in detector_classes:
                detector = detector_class()
                self.register_detector(detector)
                if hasattr(detector_class, "entity_fields") and isinstance(detector_class.entity_fields, dict):
                    logger.debug(f"Found entity_fields in {detector.name}: {detector_class.entity_fields.keys()}")
                    self.register_custom_entity_fields(detector.name, detector_class.entity_fields)
                else:
                    logger.debug(f"No entity_fields found in {detector.name}")
            return True
            
        except Exception as e:
            logger.error(f"Error loading plugin {plugin_path}: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def register_detector(self, detector: FeatureDetector) -> bool:
        """Register a feature detector with the plugin manager
        
        Args:
            detector: A FeatureDetector instance to register
            
        Returns:
            True if detector was registered, False otherwise
        """
        if not self.plugins_enabled:
            logger.debug(f"Skipping plugin {detector.name} because plugins are disabled globally")
            return False
        if detector.name in self.disabled_plugins:
            logger.debug(f"Skipping disabled plugin: {detector.name}")
            return False
        if self.only_plugins and detector.name not in self.only_plugins:
            return False
        if detector.name in self.detectors:
            logger.warning(f"Detector already registered with name: {detector.name}")
            return False
        self.detectors[detector.name] = detector
        logger.debug(f"Registered plugin: {detector.name} ({detector.description})")
        if hasattr(detector, 'entity_fields') and detector.entity_fields:
            for field_name, field_def in detector.entity_fields.items():
                self.register_custom_entity_field(
                    field_name, 
                    field_def.get('type', 'TEXT'),
                    field_def.get('description', ''),
                    detector.name
                )
                
        return True
    
    def register_custom_entity_field(self, field_name: str, field_type: str, description: str, plugin_name: str) -> None:
        """Register a single custom entity field defined by a plugin
        
        Args:
            field_name: Name of the field
            field_type: Field type (TEXT, INTEGER, REAL, BOOLEAN, JSON)
            description: Description of the field
            plugin_name: Name of the plugin registering the field
        """
        if field_type not in self.supported_field_types:
            logger.warning(
                f"Invalid field type '{field_type}' for field '{field_name}' "
                f"from plugin '{plugin_name}'. Defaulting to TEXT."
            )
            field_type = 'TEXT'
        if field_name in self.custom_entity_fields:
            existing_plugin = self.custom_entity_fields[field_name]['plugin']
            if existing_plugin == plugin_name:
                return
            else:
                logger.warning(f"Field '{field_name}' already defined by plugin '{existing_plugin}', "
                              f"cannot be redefined by plugin '{plugin_name}'")
                return
        self.custom_entity_fields[field_name] = {
            'type': field_type,
            'description': description,
            'plugin': plugin_name
        }
        logger.debug(f"Registered custom field: {field_name} ({field_type}) from plugin {plugin_name}")
        
    def register_custom_entity_fields(self, plugin_name: str, field_definitions: Dict[str, Dict[str, Any]]) -> None:
        """Register custom entity fields defined by a plugin
        
        Args:
            plugin_name: Name of the plugin registering the fields
            field_definitions: Dictionary mapping field_name -> field_definition
                              where field_definition is a dict with keys:
                              - type: Field type (TEXT, INTEGER, REAL, BOOLEAN, JSON)
                              - description: Description of the field
        """
        if not field_definitions:
            logger.debug(f"No field definitions provided by plugin {plugin_name}")
            return
            
        logger.debug(f"Registering {len(field_definitions)} custom fields from plugin {plugin_name}")
            
        for field_name, field_def in field_definitions.items():
            field_type = field_def.get('type', 'TEXT')
            description = field_def.get('description', '')
            self.register_custom_entity_field(field_name, field_type, description, plugin_name)
    
    def get_all_detectors(self) -> List[FeatureDetector]:
        """Get all registered plugin detectors
        
        Returns:
            List of detector instances
        """
        return list(self.detectors.values())
    
    def get_detector(self, name: str) -> Optional[FeatureDetector]:
        """Get a specific detector by name
        
        Args:
            name: Name of the detector
            
        Returns:
            Detector instance or None if not found
        """
        return self.detectors.get(name)
    
    def detect_features(self, cursor, token_spellings, token_str, available_cursor_kinds) -> Dict[str, Any]:
        """Run all DSL plugin detectors and return detected features and custom entity fields
        
        Args:
            cursor: Clang cursor
            token_spellings: List of token spellings
            token_str: Combined token string
            available_cursor_kinds: List of available cursor kinds
            
        Returns:
            Dictionary with 'features' (set of feature names) and 'custom_fields' (dict of field values)
        """
        features = set()
        custom_fields = {}
        
        for name, detector in self.detectors.items():
            try:
                result = detector.detect(cursor, token_spellings, token_str, available_cursor_kinds)
                logger.debug(f"Detector {name} returned result: {result}")
                if isinstance(result, bool):
                    if result:
                        features.add(name)
                        logger.debug(f"Added feature {name} from boolean result")
                elif isinstance(result, dict):
                    if result.get('detected', False):
                        features.add(name)
                        logger.debug(f"Added feature {name} from dict result with 'detected': {result.get('detected')}")
                    if 'fields' in result and isinstance(result['fields'], dict):
                        logger.debug(f"Fields from {name}: {result['fields']}")
                        logger.debug(f"Registered custom_entity_fields: {list(self.custom_entity_fields.keys())}")
                        for field_name, value in result['fields'].items():
                            if field_name in self.custom_entity_fields:
                                logger.debug(f"Adding field {field_name}={value} to custom_fields")
                                custom_fields[field_name] = value
                            else:
                                logger.warning(f"Plugin {name} returned unregistered field: {field_name}")
            except Exception as e:
                logger.warning(f"Error in DSL detector {name}: {e}")
                
        return {
            'features': features,
            'custom_fields': custom_fields
        }
