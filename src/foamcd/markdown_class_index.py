#!/usr/bin/env python3

import os
import frontmatter
from datetime import datetime
from typing import Optional

from .markdown_base import MarkdownGeneratorBase
from .config import Config
from .logs import setup_logging

class ClassHierarchyFlattener:
    """Helper class for flattening class hierarchies with separators"""
    
    @staticmethod
    def flatten_class_stats(nested_class_stats):
        """Convert nested class hierarchy into a flat list with separators
        
        Args:
            nested_class_stats: List of class information dictionaries with nested children
            
        Returns:
            Flat list with classes and separators
        """
        result = []

        def process_node_and_children(node, is_new_hierarchy=False):
            if is_new_hierarchy and result and result[-1].get("name") != "<<separator>>":
                result.append({"name": "<<separator>>"})
            node_info = node.copy()
            children = node_info.pop("children", [])
            result.append(node_info)
            for child in children:
                child_info = child.copy()
                nested_children = child_info.pop("children", [])
                result.append(child_info)
                for nested_child in nested_children:
                    process_node_and_children(nested_child)
        for i, root_node in enumerate(nested_class_stats):
            process_node_and_children(root_node, is_new_hierarchy=(i > 0))
        
        return result

logger = setup_logging()

class ClassIndexGenerator(MarkdownGeneratorBase):
    """Generator for class index, entry points, and namespace information"""
    
    def __init__(self, db_path: str,
                 output_path: str,
                 project_dir: str = None,
                 config_path: str = None,
                 config_object: Optional[Config] = None):
        """Initialize the class index generator
        
        Args:
            db_path: Path to the SQLite database
            output_path: Path to output markdown files
            project_dir: Optional project directory to filter entities by
            config_path: Optional path to configuration file
            config_object: Optional Config object (to avoid loading multiple times)
        """
        super().__init__(db_path, output_path, project_dir, config_path, config_object)
        self.index_frontmatter = {}
            
    def generate_index_file(self):
        """Generate index markdown file with class and namespace information"""
        filename = "_index.md"
        if self.index_frontmatter and "filename" in self.index_frontmatter:
            filename = self.index_frontmatter.get("filename")
            
        # Not sure if this is strickly necessary, but here to allow
        # for (atomic) standalone index creation
        if not self.output_path or self.output_path.strip() == '':
            self.output_path = 'output'
        if not os.path.isabs(self.output_path):
            self.output_path = os.path.abspath(self.output_path)
        if not os.path.exists(self.output_path):
            os.makedirs(self.output_path, exist_ok=True)
        index_path = os.path.join(self.output_path, filename)
        index_dir = os.path.dirname(index_path)
        if index_dir and not os.path.exists(index_dir):
            os.makedirs(index_dir, exist_ok=True)
            
        logger.info(f"Generating index file at {index_path}")
        standard_fields = ["title", "date", "description", "draft", "weight", "layout", "filename"]
        effective_project_dir = self.project_dir
        if not effective_project_dir and self.config:
            compile_commands_dir = self.config.get("parser.compile_commands_dir")
            if compile_commands_dir:
                effective_project_dir = compile_commands_dir
                logger.info(f"Using compile_commands_dir as project directory: {effective_project_dir}")
        namespace_stats = self.db.get_namespace_stats(effective_project_dir)
        processed_namespace_stats = []
        for namespace in namespace_stats:
            processed_namespace = self._transform_nested_entity(namespace)
            processed_namespace_stats.append(processed_namespace)
            
        logger.debug(f"Found {len(processed_namespace_stats)} namespaces in project scope")
        
        nested_class_stats = self.db.get_class_stats(
            project_dir=effective_project_dir
        )
        processed_class_stats = []
        for entity in nested_class_stats:
            processed_entity = self._transform_nested_entity(entity)
            processed_class_stats.append(processed_entity)
        class_stats = ClassHierarchyFlattener.flatten_class_stats(processed_class_stats)
        logger.debug(f"Found {len(nested_class_stats)} class hierarchies in project scope with {len(class_stats)} total classes")

        # RTS processing
        rts_classes = []
        entry_points_enabled = self.config.get("markdown.frontmatter.index.entry_points", True) if self.config else True
        rts_entry_points_enabled = self.config.get("markdown.frontmatter.index.rts_entry_points", True) if self.config else True
        if entry_points_enabled:
            logger.info("Including entry points section in _index.md")
            if rts_entry_points_enabled:
                logger.info("Auto-detecting RTS entry points (enabled in config)")
                rts_classes = self.db.get_rts_base_classes(effective_project_dir)
            else:
                logger.info("Skipping RTS auto-detection (disabled in config)")
                rts_classes = []
        else:
            logger.info("Entry points section disabled in config")
            rts_classes = []
        processed_rts_classes = []
        for entity in rts_classes:
            if entity.get('class_role') == 'base' and entity.get('rts_status') in ['partial', 'complete']:
                filtered_entity = {
                    "name": entity.get("name"),
                    "namespace": entity.get("namespace"),
                    "class_role": entity.get("class_role"),
                    "rts_status": entity.get("rts_status"),
                    "rts_names": entity.get("rts_names", [])
                }
                declaration_file = entity.get("declaration_file")
                line = entity.get("line")
                end_line = entity.get("end_line")
                if declaration_file and line and end_line:
                    filtered_entity["declaration_file"] = f"{declaration_file}#L{line}-L{end_line}"
                if "definition_files" in entity and entity["definition_files"]:
                    filtered_entity["definition_files"] = entity["definition_files"]
                processed_entity = self._transform_nested_entity(filtered_entity)
                if 'namespace' in processed_entity:
                    processed_entity['uri'] = self._transform_file_path(declaration_file, filtered_entity["name"], namespace=filtered_entity["namespace"], template_pattern="doc_uri")
                else:
                    processed_entity['uri'] = self._transform_file_path(declaration_file, filtered_entity["name"], namespace="", template_pattern="doc_uri")
                processed_rts_classes.append(processed_entity)
        
        manual_entry_points = []
        if entry_points_enabled:
            config_manual_entry_points = self.config.get("markdown.frontmatter.index.manual_entry_points", []) if self.config else []
            if config_manual_entry_points:
                logger.info(f"Processing {len(config_manual_entry_points)} manual entry points from config")
        else:
            config_manual_entry_points = []
        
        if config_manual_entry_points:
            logger.info(f"Adding {len(config_manual_entry_points)} manual entry points from config")
            for class_name in config_manual_entry_points:
                matching_classes = [cls for cls in class_stats if cls.get('name') == class_name]
                if matching_classes:
                    for cls in matching_classes:
                        manual_entry = {
                            "name": cls.get("name"),
                            "namespace": cls.get("namespace", ""),
                            "declaration_file": cls.get("declaration_file", ""),
                            "definition_files": cls.get("definition_files", []),
                            "manual_entry_point": True  # Mark as manually added
                        }
                        manual_entry = self._transform_nested_entity(manual_entry)
                        if 'namespace' in manual_entry:
                            manual_entry['uri'] = self._transform_file_path(manual_entry["declaration_file"], namespace=manual_entry["namespace"])
                        else:
                            manual_entry['uri'] = self._transform_file_path(manual_entry["declaration_file"], namespace='')
                        processed_rts_classes.append(manual_entry)
                        logger.debug(f"Added manual entry point: {cls.get('name')}")
                else:
                    manual_entry = {
                        "name": class_name,
                        "manual_entry_point": True
                    }
                    # TODO: Fix URI of manual entries
                    processed_rts_classes.append(manual_entry)
                    logger.debug(f"Added placeholder for manual entry point: {class_name}")
        
        logger.debug(f"Found {len(processed_rts_classes)} RTS base classes in project scope")

        default_metadata = {
            "title": self.project_name,
            "description": f"C++ API reference documentation for {self.project_name}",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "layout": "library",
            "weight": 10,
            "foamCD": {
                "entry_points": processed_rts_classes if entry_points_enabled and processed_rts_classes else []
            }
        }
        
        # Check which sections are enabled
        classes_enabled = self.config.get("markdown.frontmatter.index.classes_and_class_templates", True) if self.config else True
        namespaces_enabled = self.config.get("markdown.frontmatter.index.namespaces", True) if self.config else True
        
        if classes_enabled:
            logger.info("Including classes section in _index.md")
            default_metadata["foamCD"]["classes_and_class_templates"] = class_stats if class_stats else []
        else:
            logger.info("Classes and class templates section disabled in config")
            default_metadata["foamCD"]["classes_and_class_templates"] = []
            
        if namespaces_enabled:
            logger.info("Including namespaces section in _index.md")
            default_metadata["foamCD"]["namespaces"] = namespace_stats if namespace_stats else []
        else:
            logger.info("Namespaces section disabled in config")
            default_metadata["foamCD"]["namespaces"] = []
        
        if not self.index_frontmatter:
            metadata = default_metadata
        else:
            config_data = self._to_dict(self.index_frontmatter)
            if not isinstance(config_data, dict):
                logger.warning(f"Unexpected metadata type: {type(config_data)}. Using defaults.")
                metadata = default_metadata
            else:
                metadata = default_metadata.copy()
                metadata.update({k: v for k, v in config_data.items() if k in standard_fields})
                foamcd_data = {
                    "namespaces": namespace_stats if namespace_stats else [],
                    "classes_and_class_templates": class_stats if class_stats else [],
                    "entry_points": processed_rts_classes if processed_rts_classes else []
                }
                if "foamCD" in config_data and isinstance(config_data["foamCD"], dict):
                    config_foamcd = config_data["foamCD"]
                    for key, value in config_foamcd.items():
                        if key in ["namespaces", "classes_and_class_templates", "entry_points"] and \
                           (not isinstance(value, list) or not value):
                            continue
                        foamcd_data[key] = value
                metadata["foamCD"] = foamcd_data
            
        content = ""
        if  (self.config.get('markdown.frontmatter.index.functions_and_function_templates')
             or self.config.get('markdown.frontmatter.index.concepts')):
            content += "{{% pageinfo %}}\n"
            if  self.config.get('markdown.frontmatter.index.functions_and_function_templates'):
                content += '''Free functions from this library can be found [here](functions)\n'''
            if self.config.get('markdown.frontmatter.index.concepts'):
                content += '''(C++) Concepts from this library can be found [here](concepts)'''
            content += "\n{{% /pageinfo %}}"
        "# API Reference\n\nThis documentation was automatically generated by foamCD."
        if os.path.exists(index_path):
            try:
                post = frontmatter.load(index_path)
                content = post.content
                logger.debug("Preserving existing index content")
                if "foamCD" in metadata and isinstance(metadata["foamCD"], dict):
                    if "foamCD" not in post or not isinstance(post["foamCD"], dict):
                        post["foamCD"] = {}
                    for foamcd_key in ["namespaces", "classes_and_class_templates", "entry_points"]:
                        if foamcd_key in metadata["foamCD"] and isinstance(metadata["foamCD"][foamcd_key], list):
                            if not metadata["foamCD"][foamcd_key]:
                                continue
                            post["foamCD"][foamcd_key] = metadata["foamCD"][foamcd_key]
                    for foamcd_key, foamcd_value in metadata["foamCD"].items():
                        if foamcd_key not in ["namespaces", "classes_and_class_templates", "entry_points"]:
                            post["foamCD"][foamcd_key] = foamcd_value
                else:
                    for key, value in metadata.items():
                        if key != "foamCD":
                            post[key] = self._to_dict(value)
                with open(index_path, "w") as f:
                    f.write(frontmatter.dumps(post))
            except Exception as e:
                logger.warning(f"Error reading existing index file: {e}")
                post = frontmatter.Post(content, **metadata)
                with open(index_path, "w") as f:
                    f.write(frontmatter.dumps(post))
        else:
            if not isinstance(metadata, dict):
                logger.error(f"Metadata must be a dictionary, got {type(metadata)}")
                metadata = {"title": self.project_name}
            logger.debug(f"Creating new index file with metadata: {metadata}")
            post = frontmatter.Post(content, **metadata)
            with open(index_path, "w") as f:
                f.write(frontmatter.dumps(post))
            
        logger.info(f"Generated index file at {index_path}")
        
    def generate_all(self):
        """Generate class index file"""
        if not os.path.exists(self.output_path):
            os.makedirs(self.output_path)
        self.generate_index_file()
