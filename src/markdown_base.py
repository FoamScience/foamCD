#!/usr/bin/env python3

from abc import abstractmethod
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from omegaconf import OmegaConf
from jinja2 import Template

from logs import setup_logging
from config import Config
from db import EntityDatabase
from git import get_git_repo_url, get_git_reference, get_relative_path_from_git_root, is_git_repository

logger = setup_logging()

class MarkdownGeneratorBase:
    """Base class for generating Hugo-compatible markdown files from foamCD database"""
    
    def __init__(self, db_path: str,
                 output_path: str,
                 project_dir: str = None,
                 config_path: str = None,
                 config_object: Optional[Config] = None):
        """Initialize the markdown generator
        
        Args:
            db_path: Path to the SQLite database
            output_path: Path to output markdown files
            project_dir: Optional project directory to filter entities by
            config_path: Optional path to configuration file
            config_object: Optional Config object (to avoid loading multiple times)
        """
        self.db_path = db_path
        self.output_path = output_path
        self.project_dir = project_dir
        self.config_path = config_path
        self.config = config_object if config_object is not None else (Config(config_path) if config_path else None)
        self.db = EntityDatabase(db_path)
        self.project_name = os.path.basename(project_dir) if project_dir else "C++ Project"
        if self.config and hasattr(self.config, 'config'):
            markdown_config = self.config.config.get('markdown', {})
            if 'project_name' in markdown_config:
                self.project_name = markdown_config.get('project_name')
                
        self.index_frontmatter = None
        self.functions_frontmatter = None
        self.concepts_frontmatter = None
        self.entity_frontmatter = {}
        if self.config and self.config.config.get('markdown', {}).get('frontmatter'):
            frontmatter_config = self.config.config.get('markdown', {}).get('frontmatter', {})
            if 'index' in frontmatter_config:
                self.index_frontmatter = frontmatter_config.get('index')
            if 'functions' in frontmatter_config:
                self.functions_frontmatter = frontmatter_config.get('functions')
            if 'concepts' in frontmatter_config:
                self.concepts_frontmatter = frontmatter_config.get('concepts')
            if 'classes' in frontmatter_config:
                self.entity_frontmatter = frontmatter_config.get('classes')
    
    def _transform_file_path(self, file_path: str, name: str = None) -> str:
        """Transform file paths to URLs based on dependency configuration
        
        Args:
            file_path: The original file path
            name: Optional name of the entity for template variables
            
        Returns:
            Transformed file path or original path if no transformation applied
        """
        if file_path and (file_path.startswith('http://') or file_path.startswith('https://')):
            logger.debug(f"Skipping transformation for already-transformed URL: {file_path}")
            return file_path
        if not file_path:
            return file_path
        markdown_config = self.config.config.get('markdown', {})
        if not markdown_config:
            return file_path
        dependencies = markdown_config.get('dependencies', [])
        if not dependencies:
            return file_path
        for dependency in dependencies:
            if not 'path' in dependency or not 'dependency_url' in dependency:
                continue
            path_matches = False
            for path_pattern in dependency.get('path', []):
                if file_path.startswith(path_pattern):
                    path_matches = True
                    break
            if path_matches:
                pattern = dependency.get('pattern', "{{dependency_url}}/{{name}}")
                context = {
                    'dependency_url': dependency.get('dependency_url', ''),
                    'name': name or Path(file_path).stem,
                    'file_path': file_path,
                    'project_name': markdown_config.get('project_name', ''),
                    'git_repository': markdown_config.get('git_repository', ''),
                    'git_reference': markdown_config.get('git_reference', 'main'),
                }
                try:
                    template = Template(pattern)
                    return template.render(**context)
                except Exception as e:
                    logger.error(f"Error applying template to file path: {e}")
                    return file_path
        
        git_repo = markdown_config.get('git_repository', None)
        if not git_repo and file_path:
            try:
                file_dir = os.path.dirname(file_path.split('#')[0])
                if is_git_repository(file_dir):
                    git_repo = get_git_repo_url(file_dir)
                    logger.debug(f"Auto-detected Git repository: {git_repo}")
            except Exception as e:
                logger.debug(f"Error auto-detecting Git repository: {e}")
                
        if git_repo:
            start_line = '1'  # Default to line 1 if not specified
            end_line = '1'    # Default to line 1 if not specified
            if '#' in file_path:
                fragment = file_path.split('#')[1]
                line_match = re.match(r'L(\d+)-L(\d+)', fragment)
                if line_match:
                    start_line = line_match.group(1)
                    end_line = line_match.group(2)
                elif 'L-L' in fragment:
                    logger.debug(f"Found empty line numbers in {file_path}, defaulting to #L1-L1")
            repo_url = git_repo
            if repo_url.endswith('.git'):
                repo_url = repo_url[:-4]
            
            rel_path = get_relative_path_from_git_root(file_path.split('#')[0])
            if not rel_path and file_path:
                project_dir = Path(self.db.db_path).parent
                rel_path = os.path.relpath(file_path.split('#')[0], project_dir)
            git_ref = markdown_config.get('git_reference', None)
            if not git_ref and file_path:
                try:
                    file_dir = os.path.dirname(file_path.split('#')[0])
                    if is_git_repository(file_dir):
                        git_ref = get_git_reference(file_dir)
                        logger.debug(f"Auto-detected Git reference: {git_ref}")
                except Exception as e:
                    logger.debug(f"Error auto-detecting Git reference: {e}")
            
            if not git_ref:
                git_ref = 'main' ## Dangerous? Too arbitrary?

            internal_pattern = markdown_config.get('internal_linkage_pattern', None)
            if internal_pattern:
                context = {
                    'git_repository': repo_url,
                    'git_reference': git_ref,
                    'file_path': rel_path,
                    'start_line': start_line,
                    'end_line': end_line,
                    'name': name or Path(file_path).stem,
                    'project_name': markdown_config.get('project_name', '')
                }
                
                try:
                    template = Template(internal_pattern)
                    return template.render(**context)
                except Exception as e:
                    logger.error(f"Error applying internal linkage pattern: {e}")
            line_fragment = f"#L{start_line}-L{end_line}"
            return f"{repo_url}/blob/{git_ref}/{rel_path}{line_fragment}"
            
        return file_path
    
    def _transform_uri(self, entity: Dict[str, Any]) -> str:
        """Transform entity URI based on configuration template
        
        Args:
            entity: Entity dictionary with name and namespace
            
        Returns:
            Transformed URI based on template pattern or default URI if no template
        """
        if 'uri' in entity:
            return entity['uri']
        markdown_config = self.config.config.get('markdown', {})
        entity_kind = entity.get('kind', '')
        uri_template = None
        
        if entity_kind == 'CONCEPT_DECL':
            uri_template = markdown_config.get('concepts_doc_uri')
            if not uri_template and 'classes_doc_uri' not in markdown_config:
                name = entity.get('name', '')
                namespace = entity.get('namespace', '')
                return f"/api/concepts/{namespace.replace('::', '_')}_{name}"
        else:
            uri_template = markdown_config.get('classes_doc_uri')
            if not uri_template:
                name = entity.get('name', '')
                namespace = entity.get('namespace', '')
                return f"/api/classes/{namespace.replace('::', '_')}_{name}"
        
        try:
            context = {
                'name': entity.get('name', ''),
                'namespace': entity.get('namespace', '').replace('::', '_'),
                'kind': entity_kind,
                'file_path': entity.get('file', ''),
                'project_name': markdown_config.get('project_name', '')
            }
            
            template = Template(uri_template)
            return template.render(**context)
        except Exception as e:
            logger.error(f"Error applying URI template: {e}")
            name = entity.get('name', '')
            namespace = entity.get('namespace', '')
            return f"/api/classes/{namespace.replace('::', '_')}_{name}"
    
    def _transform_nested_entity(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        """Transform all file paths in a nested entity structure
        
        Args:
            entity: Entity dictionary with potentially nested structures
            
        Returns:
            Entity with transformed file paths
        """
        result = entity.copy()
        name = result.get('name', '')
        if 'file' in result:
            result['file'] = self._transform_file_path(result['file'], name)
        if 'declaration_file' in result:
            result['declaration_file'] = self._transform_file_path(result['declaration_file'], name)
        if 'definition_files' in result:
            transformed_def_files = []
            for def_file in result['definition_files']:
                transformed_def_files.append(self._transform_file_path(def_file, name))
            result['definition_files'] = transformed_def_files
        if 'children' in result and isinstance(result['children'], list):
            transformed_children = []
            for child in result['children']:
                transformed_child = self._transform_nested_entity(child)
                transformed_children.append(transformed_child)
            result['children'] = transformed_children
        if 'overloads' in result and isinstance(result['overloads'], list):
            transformed_overloads = []
            for overload in result['overloads']:
                transformed_overload = self._transform_nested_entity(overload)
                transformed_overloads.append(transformed_overload)
            result['overloads'] = transformed_overloads
        return result
    
    def _transform_entity_file_paths(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        """Transform all file paths in an entity
        
        Args:
            entity: Entity dictionary with file paths
            
        Returns:
            Entity with transformed file paths
        """
        entity_copy = entity.copy()
        name = entity_copy.get('name', '')
        if 'declaration_file' in entity_copy:
            entity_copy['declaration_file'] = self._transform_file_path(entity_copy['declaration_file'], name)
        if 'definition_files' in entity_copy:
            transformed_def_files = []
            for def_file in entity_copy['definition_files']:
                transformed_def_files.append(self._transform_file_path(def_file, name))
            entity_copy['definition_files'] = transformed_def_files
        if 'file' in entity_copy:
            entity_copy['file'] = self._transform_file_path(entity_copy['file'], name)
        return entity_copy
    
    def _flatten_class_stats(self, class_stats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Flatten nested class hierarchies to a list
        
        Args:
            class_stats: List of nested class hierarchies
            
        Returns:
            Flattened list of classes
        """
        flattened = []
        
        def _traverse(cls):
            class_copy = cls.copy()
            if 'children' in class_copy:
                del class_copy['children']
            flattened.append(class_copy)
            if 'children' in cls:
                for child in cls['children']:
                    _traverse(child)
        for cls in class_stats:
            _traverse(cls)
        return flattened
    
    def _to_dict(self, obj) -> Dict[str, Any]:
        """Convert OmegaConf or other objects to regular Python dicts
        
        Args:
            obj: Object to convert
            
        Returns:
            Dictionary representation
        """
        if isinstance(obj, OmegaConf):
            return OmegaConf.to_container(obj)
        elif isinstance(obj, dict):
            return {k: self._to_dict(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._to_dict(item) for item in obj]
        else:
            return obj
            
    @abstractmethod
    def generate_all(self):
        """Generate all markdown files"""
        pass
