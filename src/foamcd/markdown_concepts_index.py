#!/usr/bin/env python3

import os
import frontmatter
from datetime import datetime
from typing import Optional

from .markdown_base import MarkdownGeneratorBase
from .config import Config
from .logs import setup_logging

logger = setup_logging()

class ConceptsIndexGenerator(MarkdownGeneratorBase):
    """Generator for concepts index documentation"""
    
    def __init__(self, db_path: str,
                 output_path: str,
                 project_dir: str = None,
                 config_path: str = None,
                 config_object: Optional[Config] = None):
        """Initialize the concepts index generator
        
        Args:
            db_path: Path to the SQLite database
            output_path: Path to output markdown files
            project_dir: Optional project directory to filter entities by
            config_path: Optional path to configuration file
            config_object: Optional Config object (to avoid loading multiple times)
        """
        super().__init__(db_path, output_path, project_dir, config_path, config_object)
    
    def generate_concepts_file(self):
        """Generate concepts markdown file with concept information"""
        filename = "concepts.md"
        if self.concepts_frontmatter and "filename" in self.concepts_frontmatter:
            filename = self.concepts_frontmatter.get("filename")
        if not self.output_path or self.output_path.strip() == '':
            self.output_path = 'output'
        if not os.path.isabs(self.output_path):
            self.output_path = os.path.abspath(self.output_path)
        if not os.path.exists(self.output_path):
            os.makedirs(self.output_path, exist_ok=True)
        concepts_path = os.path.join(self.output_path, filename)
        concepts_dir = os.path.dirname(concepts_path)
        if concepts_dir and not os.path.exists(concepts_dir):
            os.makedirs(concepts_dir, exist_ok=True)

        logger.info(f"Generating concepts file at {concepts_path}")
        standard_fields = ["title", "date", "description", "draft", "weight", "layout", "filename"]
        compile_commands_dir = self.project_dir
        if self.config and self.config.config.get('parser', {}).get('compile_commands_dir'):
            compile_commands_dir = self.config.config.get('parser', {}).get('compile_commands_dir')
        concept_stats = self.db.get_concept_stats(compile_commands_dir)
        processed_concept_stats = []
        for entity in concept_stats:
            processed_entity = self._transform_nested_entity(entity)
            processed_concept_stats.append(processed_entity)
            
        logger.debug(f"Found {len(processed_concept_stats)} concepts in project scope")
        
        if not processed_concept_stats:
            logger.info("No concepts found in project scope, skipping concepts.md file generation")
            return
        
        default_metadata = {
            "title": f"{self.project_name} Concepts",
            "description": f"C++ concept reference documentation for {self.project_name}",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "layout": "concepts",
            "weight": 10,
            "foamCD": {
                "concepts": processed_concept_stats if processed_concept_stats else []
            }
        }
        
        if not self.concepts_frontmatter:
            metadata = default_metadata
        else:
            config_data = self._to_dict(self.concepts_frontmatter)
            if not isinstance(config_data, dict):
                logger.warning(f"Unexpected metadata type: {type(config_data)}. Using defaults.")
                metadata = default_metadata
            else:
                metadata = default_metadata.copy()
                metadata.update({k: v for k, v in config_data.items() if k in standard_fields})
                foamcd_data = {"concepts": processed_concept_stats}
                if "foamCD" in config_data and isinstance(config_data["foamCD"], dict):
                    foamcd_data.update({k: v for k, v in config_data["foamCD"].items() 
                                      if k != "concepts"})
                    if "concepts" in config_data["foamCD"] and \
                       isinstance(config_data["foamCD"]["concepts"], bool):
                        pass
                    elif "concepts" in config_data["foamCD"] and \
                         isinstance(config_data["foamCD"]["concepts"], list) and \
                         config_data["foamCD"]["concepts"]:
                        foamcd_data["concepts"] = config_data["foamCD"]["concepts"]
                metadata["foamCD"] = foamcd_data
            
        content = ""
        if self.config.get('markdown.frontmatter.index.functions_and_function_templates'):
            content += '''{{% pageinfo %}}\nFree functions from this library can be found [here](../functions)\n{{% /pageinfo %}}'''
        
        if os.path.exists(concepts_path):
            try:
                post = frontmatter.load(concepts_path)
                content = post.content
                logger.debug("Preserving existing concepts content")
                for key, value in metadata.items():
                    post[key] = self._to_dict(value)
                with open(concepts_path, "w") as f:
                    f.write(frontmatter.dumps(post))
            except Exception as e:
                logger.warning(f"Error reading existing concepts file: {e}")
                post = frontmatter.Post(content, **metadata)
                with open(concepts_path, "w") as f:
                    f.write(frontmatter.dumps(post))
        else:
            logger.debug(f"Creating new concepts file with metadata: {metadata}")
            post = frontmatter.Post(content, **metadata)
            with open(concepts_path, "w") as f:
                f.write(frontmatter.dumps(post))
            
        logger.info(f"Generated concepts file at {concepts_path}")
    
    def generate_all(self):
        """Generate concepts index file"""
        if not os.path.exists(self.output_path):
            os.makedirs(self.output_path)
            
        self.generate_concepts_file()
