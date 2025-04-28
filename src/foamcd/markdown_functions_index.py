#!/usr/bin/env python3

import os
import frontmatter
from datetime import datetime
from typing import Optional

from .markdown_base import MarkdownGeneratorBase
from .config import Config
from .logs import setup_logging

class FunctionHierarchyFlattener:
    """Helper class for flattening function hierarchies with separators"""
    
    @staticmethod
    def flatten_function_stats(nested_function_stats):
        """Convert nested function hierarchy into a flat list with separators
        
        Args:
            nested_function_stats: List of function information dictionaries with nested overloads
            
        Returns:
            Flat list with functions and separators
        """
        result = []
        def process_function_and_overloads(function_node, is_new_group=False):
            if is_new_group and result and result[-1].get("name") != "<<separator>>":
                result.append({"name": "<<separator>>"})
            function_info = function_node.copy()
            overloads = function_info.pop("overloads", [])
            result.append(function_info)
            for overload in overloads:
                result.append(overload)
        for i, function_node in enumerate(nested_function_stats):
            process_function_and_overloads(function_node, is_new_group=(i > 0))
        return result

logger = setup_logging()

class FunctionsIndexGenerator(MarkdownGeneratorBase):
    """Generator for functions index documentation"""
    
    def __init__(self, db_path: str,
                 output_path: str,
                 project_dir: str = None,
                 config_path: str = None,
                 config_object: Optional[Config] = None):
        """Initialize the functions index generator
        
        Args:
            db_path: Path to the SQLite database
            output_path: Path to output markdown files
            project_dir: Optional project directory to filter entities by
            config_path: Optional path to configuration file
            config_object: Optional Config object (to avoid loading multiple times)
        """
        super().__init__(db_path, output_path, project_dir, config_path, config_object)
    
    def generate_functions_file(self):
        """Generate functions markdown file with function information"""
        filename = "functions.md"
        if self.functions_frontmatter and "filename" in self.functions_frontmatter:
            filename = self.functions_frontmatter.get("filename")
        
        if not self.output_path or self.output_path.strip() == '':
            self.output_path = 'output'
        if not os.path.isabs(self.output_path):
            self.output_path = os.path.abspath(self.output_path)
        if not os.path.exists(self.output_path):
            os.makedirs(self.output_path, exist_ok=True)
        functions_path = os.path.join(self.output_path, filename)
        functions_dir = os.path.dirname(functions_path)
        if functions_dir and not os.path.exists(functions_dir):
            os.makedirs(functions_dir, exist_ok=True)
            
        logger.info(f"Generating functions file at {functions_path}")
        standard_fields = ["title", "date", "description", "draft", "weight", "layout", "filename"]
        compile_commands_dir = self.project_dir
        if self.config and self.config.config.get('parser', {}).get('compile_commands_dir'):
            compile_commands_dir = self.config.config.get('parser', {}).get('compile_commands_dir')
        function_stats = self.db.get_function_stats(compile_commands_dir)
        processed_function_stats = []
        for entity in function_stats:
            processed_entity = self._transform_nested_entity(entity)
            processed_function_stats.append(processed_entity)
        flattened_function_stats = FunctionHierarchyFlattener.flatten_function_stats(processed_function_stats)
        
        if not processed_function_stats:
            logger.info("No free functions found in project scope, skipping functions.md file generation")
            return

        logger.debug(f"Found {len(processed_function_stats)} function groups in project scope with {len(flattened_function_stats)} total functions")
        
        default_metadata = {
            "title": f"{self.project_name} Functions",
            "description": f"C++ function reference documentation for {self.project_name}",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "layout": "functions",
            "weight": 10,
            "foamCD": {
                "functions_and_function_templates": flattened_function_stats if flattened_function_stats else []
            }
        }
        
        if not self.functions_frontmatter:
            metadata = default_metadata
        else:
            config_data = self._to_dict(self.functions_frontmatter)
            if not isinstance(config_data, dict):
                logger.warning(f"Unexpected metadata type: {type(config_data)}. Using defaults.")
                metadata = default_metadata
            else:
                metadata = default_metadata.copy()
                metadata.update({k: v for k, v in config_data.items() if k in standard_fields})
                foamcd_data = {"functions_and_function_templates": flattened_function_stats}
                if "foamCD" in config_data and isinstance(config_data["foamCD"], dict):
                    foamcd_data.update({k: v for k, v in config_data["foamCD"].items() 
                                      if k != "functions_and_function_templates"})
                    if "functions_and_function_templates" in config_data["foamCD"] and \
                       isinstance(config_data["foamCD"]["functions_and_function_templates"], bool):
                        pass
                    elif "functions_and_function_templates" in config_data["foamCD"] and \
                         isinstance(config_data["foamCD"]["functions_and_function_templates"], list) and \
                         config_data["foamCD"]["functions_and_function_templates"]:
                        foamcd_data["functions_and_function_templates"] = config_data["foamCD"]["functions_and_function_templates"]
                metadata["foamCD"] = foamcd_data
            
        content = ""
        if self.config.get('markdown.frontmatter.index.concepts'):
            content += '''{{% pageinfo %}}\n(C++) Concepts from this library can be found [here](../concepts)\n{{% /pageinfo %}}'''
        if os.path.exists(functions_path):
            try:
                post = frontmatter.load(functions_path)
                content = post.content
                logger.debug("Preserving existing functions content")
                for key, value in metadata.items():
                    post[key] = self._to_dict(value)
                with open(functions_path, "w") as f:
                    f.write(frontmatter.dumps(post))
            except Exception as e:
                logger.warning(f"Error reading existing functions file: {e}")
                post = frontmatter.Post(content, **metadata)
                with open(functions_path, "w") as f:
                    f.write(frontmatter.dumps(post))
        else:
            logger.debug(f"Creating new functions file with metadata: {metadata}")
            post = frontmatter.Post(content, **metadata)
            with open(functions_path, "w") as f:
                f.write(frontmatter.dumps(post))
            
        logger.info(f"Generated functions file at {functions_path}")
    
    def generate_all(self):
        """Generate functions index file"""
        if not os.path.exists(self.output_path):
            os.makedirs(self.output_path)
            
        self.generate_functions_file()
