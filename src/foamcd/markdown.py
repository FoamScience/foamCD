#!/usr/bin/env python3

import os
import sys
import argparse
import hashlib
import re
from typing import Dict, List, Any, Optional
import frontmatter
from datetime import datetime
from jinja2 import Template

from .logs import setup_logging
from .db import EntityDatabase
from .markdown_base import MarkdownGeneratorBase
from .markdown_class_index import ClassIndexGenerator
from .markdown_functions_index import FunctionsIndexGenerator
from .markdown_concepts_index import ConceptsIndexGenerator
from .git import get_git_root
from .version import get_version

logger = setup_logging()

class MarkdownGenerator(MarkdownGeneratorBase):
    """Generates Hugo-compatible markdown files from foamCD database
    
    This is the main coordinator that delegates to specialized generators
    """
    
    _unit_tests_db_cache = {}
    _verbose_unit_tests_logging = True  # Control verbose logging, only first load gets verbose log
    
    def __init__(self, db_path: str, output_path: str, project_dir: str = None, config_path: str = None):
        """Initialize the markdown generator
        
        Args:
            db_path: Path to the SQLite database
            output_path: Path to output markdown files
            project_dir: Optional project directory to filter entities by
            config_path: Optional path to configuration file
        """
        super().__init__(db_path, output_path, project_dir, config_path)
        self.class_index_generator = ClassIndexGenerator(db_path, output_path, project_dir, config_object=self.config)
        self.functions_index_generator = FunctionsIndexGenerator(db_path, output_path, project_dir, config_object=self.config)
        self.concepts_index_generator = ConceptsIndexGenerator(db_path, output_path, project_dir, config_object=self.config)
    
    def _transform_entity_paths(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        """Transform file paths in entity for inclusion in frontmatter
        
        Args:
            entity: Entity dictionary
            
        Returns:
            Updated entity with processed paths
        """
        entity_copy = entity.copy()
        if "file" in entity_copy:
            name = entity_copy.get("name", "")
            try:
                file_path = entity_copy["file"]
                transformed_path, _ = self._transform_file_path(file_path, name)
                entity_copy["file"] = transformed_path
            except Exception as e:
                logger.warning(f"Error transforming file path: {e}")
        if 'declaration_file' in entity_copy and entity_copy['declaration_file']:
            name = entity_copy.get("name", "")
            try:
                decl_file = entity_copy['declaration_file']
                if not '#' in decl_file:
                    line = entity_copy.get('line') or entity_copy.get('start_line')
                    end_line = entity_copy.get('end_line') or entity_copy.get('line')
                    if line and end_line:
                        decl_file = f"{decl_file}#L{line}-L{end_line}"
                        logger.debug(f"Added line numbers to declaration file: {decl_file}")
                transformed_path, _ = self._transform_file_path(decl_file, name)
                entity_copy['declaration_file'] = transformed_path
            except Exception as e:
                logger.warning(f"Error transforming declaration file path: {e}")
                
        if 'definition_files' in entity_copy and entity_copy['definition_files']:
            name = entity_copy.get("name", "")
            try:
                transformed_defs = []
                for def_file in entity_copy['definition_files']:
                    transformed_def, _ = self._transform_file_path(def_file, name, template_pattern="filename_uri", entity=entity_copy)
                    transformed_defs.append(transformed_def)
                entity_copy['definition_files'] = transformed_defs
            except Exception as e:
                logger.warning(f"Error transforming definition file paths: {e}")
                
        for key in ['methods', 'fields', 'children', 'bases']:
            if key in entity_copy and isinstance(entity_copy[key], list):
                entity_copy[key] = [self._transform_entity_paths(child) for child in entity_copy[key]]
                
        return entity_copy
        
    def generate_entity_pages(self):
        """Generate individual markdown pages for each class in the project_dir
        
        Generates a file for each class directly in the output path
        with filename format: {{namespace}}_{{className}}.md
        If a file already exists, its content is preserved and only the frontmatter is updated.
        """
        # Ensure output directory exists
        if not os.path.exists(self.output_path):
            os.makedirs(self.output_path)
            
        logger.info(f"Generating entity pages in {self.output_path}")
        effective_project_dir = self.project_dir
        if not effective_project_dir and self.config:
            compile_commands_dir = self.config.get("parser.compile_commands_dir")
            if compile_commands_dir:
                effective_project_dir = compile_commands_dir
                logger.info(f"Using compile_commands_dir as project directory: {effective_project_dir}")
        
        if not effective_project_dir:
            logger.warning("No project directory specified and no compile_commands_dir found in config, skipping entity page generation")
            return
            
        db = None
        class_entities = []
        try:
            db_path = self.db_path
            if not os.path.isabs(db_path):
                db_path = os.path.abspath(db_path)
            logger.debug(f"Connecting to database at: {db_path}")
            db = EntityDatabase(db_path)
            entity_count = 0
            try:
                entity_count = len(db.get_all_entities())
                logger.debug(f"Database contains {entity_count} total entities")
            except Exception as e:
                logger.warning(f"Error getting entity count: {e}")
            class_entities = db.get_entities_by_kind_in_project(
                ['CLASS_DECL', 'CLASS_TEMPLATE', 'STRUCT_DECL', 'STRUCT_TEMPLATE'],
                effective_project_dir
            )
            if class_entities:
                logger.debug(f"Database reports {len(class_entities)} classes in total")
            else:
                logger.warning("No classes found in database query")
                class_entities = []
        except Exception as e:
            logger.error(f"Error retrieving class entities: {e}")
            class_entities = []
        finally:
            if db and hasattr(db, 'conn') and db.conn:
                db.conn.close()
                logger.debug("Closed temporary database connection")
        
        logger.info(f"Found {len(class_entities)} classes in project directory: {effective_project_dir}")
        
        generated_count = 0
        skipped_count = 0
        for entity in class_entities:
            if not entity.get('name'):
                continue
            class_name = entity.get('name')
            import re
            # TODO: manually excluding add.*ConstructorToTable feels wrong
            # Maybe it's just an artifact of the unit tests
            if re.match(r'add.*ConstructorToTable', class_name):
                logger.debug(f"Skipping constructor table class: {class_name}")
                skipped_count += 1
                continue
            namespace = ''
            parent_uuid = entity.get('parent_uuid')
            if parent_uuid:
                namespace_db = None
                try:
                    namespace_db = EntityDatabase(self.db_path)
                    namespace = namespace_db._get_namespace_path(parent_uuid)
                    logger.debug(f"Determined namespace '{namespace}' for class {class_name}")
                except Exception as e:
                    logger.error(f"Error getting namespace for class {class_name}: {e}")
                finally:
                    if namespace_db and hasattr(namespace_db, 'conn') and namespace_db.conn:
                        namespace_db.conn.close()
            
            namespace_filename = namespace.replace('::', '_') if namespace else ''
            if namespace_filename:
                filename = f"{namespace_filename}_{class_name}.md"
            else:
                filename = f"{class_name}.md"
                
            protected_files = ['_index.md', 'functions.md', 'concepts.md']
            if filename in protected_files:
                logger.warning(f"Skipping generation of {filename} as it is a protected file")
                skipped_count += 1
                continue
                
            file_path = os.path.join(self.output_path, filename)
            frontmatter_data = {
                "title": class_name,
                "url": self._get_entity_url(entity),
                "layout": "class",
                "weight": 20,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "description": (entity.get("documentation", {}).get("brief", "") or 
                               entity.get("documentation", {}).get("description", "") or 
                               f"API documentation for {class_name}"),
                "categories": [
                    "api",
                    f"{self.config.get('markdown.project_name')} API"
                ],
                "api_tags": self._get_entity_api_tags(entity),
                "foamCD": {
                    "filename": self._get_entity_filename(entity),
                    "namespace": namespace,
                    "signature": entity.get("full_signature", ""),
                    "documentation": self._format_entity_documentation(entity),
                    "ctors": self._get_entity_constructors(entity),
                    "factory_methods": self._get_entity_factory_methods(entity),
                    "dtor": self._get_entity_destructor(entity),
                    "standard_config": self._get_entity_standard_config(entity),
                    "interface": {
                        "public_bases": self._get_entity_public_bases(entity),
                        "static_methods": self._get_entity_static_methods(entity),
                        "abstract_methods": self._get_entity_abstract_methods(entity),
                        "abstract_in_base_methods": self._get_entity_abstract_in_base_methods(entity),
                        "public_methods": self._get_entity_public_methods(entity)
                    },
                    "openfoam_dsl": {
                        "RTS": self._get_entity_rts_info(entity),
                        "reflection": self._get_entity_reflection_info(entity)
                    },
                    "unit_tests": self._get_entity_unit_tests(entity),
                    "knowledge_requirements": self._get_entity_knowledge_requirements(entity),
                    "protected_bases": self._get_entity_protected_bases(entity),
                    "protected_methods": self._get_entity_protected_methods(entity),
                    "private_bases": self._get_entity_private_bases(entity),
                    "private_methods": self._get_entity_private_methods(entity),
                    "mpi_comms": self._get_entity_mpi_comms(entity)
                }
            }
            
            if self.config.get("markdown", {}).get("frontmatter", {}).get("entities", {}).get("contributors_from_git", False):
                frontmatter_data["contributors"] = self._get_entity_contributors(entity)
            content = ""
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r') as f:
                        post = frontmatter.load(f)
                    content = post.content
                    logger.debug(f"Preserved content from existing entity page: {filename}")
                    if 'foamCD' in post and isinstance(post['foamCD'], dict):
                        existing_foamcd = post['foamCD']
                        if 'class_info' in existing_foamcd:
                            del existing_foamcd['class_info']
                        for k, v in existing_foamcd.items():
                            if k not in frontmatter_data['foamCD']:
                                frontmatter_data['foamCD'][k] = v
                except Exception as e:
                    logger.warning(f"Error reading existing entity file {filename}: {e}")
            else:
                content = ""
                logger.debug(f"Creating new entity page: {filename}")
            post = frontmatter.Post(content, **frontmatter_data)
            with open(file_path, 'w') as f:
                f.write(frontmatter.dumps(post))
            generated_count += 1
            
        # Track valid entity filenames to check for stale files
        valid_entity_filenames = set()
        for entity in class_entities:
            if not entity.get('name'):
                continue
            class_name = entity.get('name')
            if re.match(r'add.*ConstructorToTable', class_name):
                continue
            namespace = ''
            parent_uuid = entity.get('parent_uuid')
            if parent_uuid:
                try:
                    namespace_db = EntityDatabase(self.db_path)
                    namespace = namespace_db._get_namespace_path(parent_uuid)
                finally:
                    if 'namespace_db' in locals() and namespace_db and hasattr(namespace_db, 'conn') and namespace_db.conn:
                        namespace_db.conn.close()
            namespace_filename = namespace.replace('::', '_') if namespace else ''
            if namespace_filename:
                filename = f"{namespace_filename}_{class_name}.md"
            else:
                filename = f"{class_name}.md"
            valid_entity_filenames.add(filename)
        
        # Now check for stale files that need to be removed
        removed_count = 0
        protected_files = ['_index.md', 'functions.md', 'concepts.md']
        for filename in os.listdir(self.output_path):
            # Skip protected files and non-markdown files
            if not filename.endswith('.md') or filename in protected_files:
                continue
                
            # Only remove files that were previously generated by this system but are no longer valid
            if filename not in valid_entity_filenames:
                file_path = os.path.join(self.output_path, filename)
                try:
                    with open(file_path, 'r') as f:
                        post = frontmatter.load(f)
                    # Only remove if the file has foamCD frontmatter component
                    if 'foamCD' in post and isinstance(post['foamCD'], dict):
                        logger.info(f"Removing stale entity documentation: {filename}")
                        os.remove(file_path)
                        removed_count += 1
                    else:
                        logger.debug(f"Skipping non-foamCD markdown file: {filename}")
                except Exception as e:
                    logger.warning(f"Error checking stale entity file {filename}: {e}")
        
        logger.info(f"Entity page generation complete: {generated_count} pages generated, {skipped_count} classes skipped, {removed_count} stale entity files removed")
    
    def generate_all(self):
        """Generate all markdown files based on configuration settings"""
        if not os.path.exists(self.output_path):
            os.makedirs(self.output_path)
        logger.info(f"Generating markdown files in {self.output_path}")
        logger.info("Generating _index.md file (always required)")
        self.class_index_generator.generate_all()
        functions_enabled = self.config.get("markdown.frontmatter.index.functions_and_function_templates", True) if self.config else True
        if functions_enabled:
            logger.info("Generating functions.md (enabled in config)")
            self.functions_index_generator.generate_all()
        else:
            logger.info("Skipping functions.md (disabled in config)")
        
        concepts_enabled = self.config.get("markdown.frontmatter.index.concepts", True) if self.config else True
        if concepts_enabled:
            logger.info("Generating concepts.md (enabled in config)")
            self.concepts_index_generator.generate_all()
        else:
            logger.info("Skipping concepts.md (disabled in config)")
        self.generate_entity_pages()
        logger.info("Markdown generation complete")
        
    def _get_entity_api_tags(self, entity: Dict[str, Any]) -> List[str]:
        """Get API tags for an entity
        
        Args:
            entity: Entity dictionary
            
        Returns:
            List of API tags
        """
        # TODO: Partially implemented proper API tagging
        tags = ["class"]
        if entity.get("is_abstract", False):
            tags.append("abstract")
        custom_fields = entity.get("custom_fields", {})
        if custom_fields.get("openfoam_rts_name_1"):
            tags.append("rts_base")
        return tags
        
    def _get_entity_filename(self, entity: Dict[str, Any]) -> str:
        """Get the source filename for an entity, transformed via templates
        
        Args:
            entity: Entity dictionary
            
        Returns:
            Source filename with GitHub/GitLab URL if configured
        """
        if "file" in entity:
            file_path = entity["file"]
            name = entity.get("name", os.path.basename(file_path))
            start_line = entity.get("line") or entity.get("start_line")
            end_line = entity.get("end_line") or entity.get("line")
            if start_line and end_line:
                file_path = f"{file_path}#L{start_line}-L{end_line}"
                logger.debug(f"Added line numbers to file path: {file_path}")
            transformed_path, _ = self._transform_file_path(file_path, name)
            return transformed_path
            
        return "unknown.H"  # Placeholder
        
    def _format_entity_documentation(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        """Format entity documentation for inclusion in frontmatter
        
        This extracts documentation from the entity's 'documentation' field
        which is populated from the parsed_docs table and related doc tables.
        
        Args:
            entity: Entity dictionary
            
        Returns:
            Formatted documentation dictionary suitable for frontmatter
        """
        result = {
            "description": "",
            "params": {},
            "returns": "",
            "deprecated": "",
            "since": ""
        }
        
        if "documentation" in entity and isinstance(entity["documentation"], dict):
            doc = entity["documentation"]
            for field in ["description", "returns", "deprecated", "since"]:
                if field in doc and doc[field]:
                    result[field] = doc[field]
            result["tags"] = {}
            for tag_name in ["brief", "note", "warning", "todo", "attention"]:
                if tag_name in doc and doc[tag_name]:
                    result["tags"][tag_name] = doc[tag_name]
            if "tags" in doc and isinstance(doc["tags"], dict):
                result["tags"].update(doc["tags"])
            if not result["tags"]:
                del result["tags"]
            if "params" in doc and isinstance(doc["params"], dict):
                result["params"] = doc["params"]
        if not result["description"] and entity.get("doc_comment"):
            doc_comment = entity["doc_comment"]
            desc_lines = []
            for line in doc_comment.split('\n'):
                if re.match(r'^[@\\][a-zA-Z]+\b', line.strip()):
                    break
                desc_lines.append(line)
            result["description"] = '\n'.join(desc_lines).strip() or doc_comment
            
        if entity.get("deprecated_message") and not result["deprecated"]:
            result["deprecated"] = entity.get("deprecated_message")
        elif entity.get("is_deprecated", False) and not result["deprecated"]:
            entity_type = entity.get("kind", "").lower().replace("_", " ")
            result["deprecated"] = f"This {entity_type} is marked as deprecated"
        result["is_deprecated"] = bool(result["deprecated"] or entity.get("is_deprecated", False))
            
        return result
    
    def _get_entity_url(self, entity: Dict[str, Any]) -> str:
        """Get the URL for an entity, transformed via templates.
        For now, only handles classes/structs.
        
        Args:
            entity: Entity dictionary
            
        Returns:
            Entity URL
        """
        if entity.get("kind") not in ['CLASS_DECL', 'CLASS_TEMPLATE', 'STRUCT_DECL', 'STRUCT_TEMPLATE']:
            return None
        pattern = self.config.get('markdown.doc_uri')
        _, context = self._transform_file_path(entity['file'], entity['name'], entity['namespace'])
        try:
            template = Template(pattern)
            return template.render(**context)
        except Exception as e:
            logger.error(f"Error applying doc_uri template: {e}")
            raise

    def _format_method_info(self, method_entity: Dict[str, Any]) -> Dict[str, Any]:
        """Format method information for use in frontmatter
        
        Args:
            method_entity: Method entity dictionary
            
        Returns:
            Formatted method information dictionary
        """
        method_info = method_entity.get("method_info", {})
        name = method_entity.get("name", "")
        parent_name = method_entity.get("parent_name", "")
        is_constructor = (name == parent_name) or method_entity.get("kind", "") in ["CONSTRUCTOR", "CXX_CONSTRUCTOR"]
        is_destructor = (name == f"~{parent_name}") or method_entity.get("kind", "") in ["DESTRUCTOR", "CXX_DESTRUCTOR"]
        parameters = []
        for param in method_entity.get("parameters", []):
            param_info = {
                "name": param.get("name", ""),
                "type": param.get("type", "")
            }
            parameters.append(param_info)
        access = method_entity.get("access_specifier", "public").lower()
        qualifiers = []
        if is_constructor or is_destructor:
            result_type = None
        else:
            result_type = method_entity.get("result_type", "void")
        is_static = method_info.get("is_static", False)
        if is_static:
            qualifiers.append("static")
        if method_info.get("is_virtual", False):
            qualifiers.append("virtual")
        if method_entity.get("is_explicit", False):
            qualifiers.append("explicit")
        if method_entity.get("is_constexpr", False):
            qualifiers.append("constexpr")
        if method_entity.get("is_inline", False):
            qualifiers.append("inline")
            
        signature_contains_deleted = False
        if "full_signature" in method_entity and method_entity["full_signature"]:
            signature = method_entity["full_signature"]
            if " = delete" in signature:
                signature_contains_deleted = True
            logger.debug(f"Using full signature for {name}: {signature}")
        else:
            signature_parts = []
            if qualifiers:
                signature_parts.append(' '.join(qualifiers))
            if not (is_constructor or is_destructor) and result_type is not None:
                signature_parts.append(result_type)
            signature = ' '.join(signature_parts) + (' ' if signature_parts else '')
            signature += name
            if parameters:
                param_strings = [f"{p.get('type', '')} {p.get('name', '')}" for p in parameters]
                signature += f"({', '.join(param_strings)})"
            else:
                signature += "()"
                
            if method_info.get("is_const", False):
                signature += " const"
            if method_entity.get("is_noexcept", False):
                signature += " noexcept"
            if method_info.get("is_virtual", False) and method_info.get("is_pure_virtual", False):
                signature += " = 0"
            if method_info.get("is_defaulted", False):
                signature += " = default"
            elif method_info.get("is_deleted", False):
                signature += " = delete"
            
            logger.debug(f"Constructed signature for {name}: {signature}")
            
        used_cpp_features = set()
        method_uuid = method_entity.get("uuid")
        
        if method_uuid and self.db:
            try:
                self.db.cursor.execute(
                    """SELECT f.name 
                       FROM features f 
                       JOIN entity_features ef ON f.id = ef.feature_id 
                       WHERE ef.entity_uuid = ?""", 
                    (method_uuid,)
                )
                for row in self.db.cursor.fetchall():
                    feature_name = row[0]
                    if feature_name:
                        used_cpp_features.add(feature_name)
                logger.debug(f"Found {len(used_cpp_features)} C++ features for method {name} from database")
            except Exception as e:
                logger.warning(f"Error retrieving C++ features for method {name}: {e}")
                
        if not used_cpp_features:
            if method_info.get("is_virtual", False):
                used_cpp_features.add("virtual functions")
            if method_info.get("is_pure_virtual", False):
                used_cpp_features.add("pure virtual functions")
            if is_static:
                used_cpp_features.add("static methods")
            if method_info.get("is_const", False):
                used_cpp_features.add("const methods")
            if "template_parameters" in method_entity and method_entity["template_parameters"]:
                used_cpp_features.add("template functions")
                
        formatted_info = {
            "name": name,
            "signature": signature.strip(),
            "parameters": parameters,
            "return_type": result_type,
            "is_constructor": is_constructor,
            "is_destructor": is_destructor,
            "is_virtual": method_info.get("is_virtual", False),
            "is_pure_virtual": method_info.get("is_pure_virtual", False),
            "is_override": method_info.get("is_override", False),
            "is_final": method_info.get("is_final", False),
            "is_static": method_info.get("is_static", False),
            "is_defaulted": method_info.get("is_defaulted", False),
            "is_deleted": method_info.get("is_deleted", False) or signature_contains_deleted,
            "is_const": method_info.get("is_const", False),
            "is_noexcept": method_entity.get("is_noexcept", False),
            "is_deprecated": method_entity.get("is_deprecated", False),
            "access_specifier": method_entity.get("access_specifier", "public").lower()
        }
        
        formatted_info["documentation"] = {
            "description": "",
            "returns": "",
            "deprecated": "",
            "since": ""
        }
        if method_entity.get("deprecated_message"):
            formatted_info["documentation"]["deprecated"] = method_entity.get("deprecated_message")
        elif method_entity.get("is_deprecated", False):
            method_type = "method" if not is_constructor and not is_destructor else ("constructor" if is_constructor else "destructor")
            formatted_info["documentation"]["deprecated"] = f"This {method_type} is marked as deprecated"
        if "documentation" in method_entity:
            doc = method_entity["documentation"]
            if doc.get("deprecated") and not formatted_info["documentation"]["deprecated"]:
                formatted_info["documentation"]["deprecated"] = doc.get("deprecated")
            formatted_info["documentation"]["description"] = doc.get("description", "")
            formatted_info["documentation"]["returns"] = doc.get("returns", "")
            formatted_info["documentation"]["since"] = doc.get("since", "")
            for tag_name in ["brief", "note", "warning", "todo", "attention"]:
                if tag_name in doc and doc[tag_name]:
                    if "tags" not in formatted_info["documentation"]:
                        formatted_info["documentation"]["tags"] = {}
                    formatted_info["documentation"]["tags"][tag_name] = doc[tag_name]
            if "params" in doc and parameters:
                param_docs = doc.get("params", {})
                for param in formatted_info["parameters"]:
                    param_name = param.get("name")
                    if param_name and param_name in param_docs:
                        param["description"] = param_docs[param_name]
        elif method_entity.get("doc_comment"):
            formatted_info["documentation"] = {
                "description": method_entity.get("doc_comment", "")
            }
        if "file" in method_entity:
            file_path = method_entity["file"]
            line = method_entity.get("line") or method_entity.get("start_line")
            end_line = method_entity.get("end_line") or method_entity.get("line")
            if line and end_line:
                file_path = f"{file_path}#L{line}-L{end_line}"
            namespace = method_entity.get("namespace")
            transformed_path, _ = self._transform_file_path(file_path, name,
                                                            namespace,
                                                            template_pattern="method_doc_uri",
                                                            entity=method_entity)
            formatted_info["definition_file"] = transformed_path
            
        return formatted_info
    
    def _get_entity_constructors(self, entity: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get constructor information for an entity
        
        Args:
            entity: Entity dictionary
            
        Returns:
            List of constructor dictionaries with standardized format
        """
        constructors = []
        class_name = entity.get("name", "")
        
        if "children" not in entity:
            return constructors
        for child in entity.get("children", []):
            if child.get("kind", "") in ["CONSTRUCTOR", "CXX_CONSTRUCTOR"]:
                ctor_info = self._format_method_info(child)
                constructors.append(ctor_info)
            elif child.get("kind", "") == "CXX_METHOD" and child.get("name", "") == class_name:
                ctor_info = self._format_method_info(child)
                constructors.append(ctor_info)
                
        return constructors
        
    def _get_entity_destructor(self, entity: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get destructor information for an entity
        
        Args:
            entity: Entity dictionary
            
        Returns:
            Destructor dictionary with standardized format or None if no destructor found
        """
        class_name = entity.get("name", "")
        if "children" not in entity:
            return None
        for child in entity.get("children", []):
            if child.get("kind", "") in ["DESTRUCTOR", "CXX_DESTRUCTOR"]:
                dtor_info = self._format_method_info(child)
                return dtor_info
            elif child.get("kind", "") == "CXX_METHOD" and child.get("name", "") == f"~{class_name}":
                dtor_info = self._format_method_info(child)
                return dtor_info
                
        return None
        
    def _is_factory_method(self, method: Dict[str, Any], class_name: str) -> bool:
        """Determine if a method is a factory method
        
        Args:
            method: Method entity dictionary
            class_name: Name of the containing class
            
        Returns:
            True if the method is a factory method, False otherwise
        """
        method_info = method.get("method_info", {})
        is_static = method_info.get("is_static", False)
        is_method = method.get("kind", "") in ["CXX_METHOD", "FUNCTION_TEMPLATE"]
        is_public = method.get("access_specifier", "public").lower() == "public"
        
        if not (is_method and is_static and is_public):
            return False
            
        factory_method_exact = [
            "New",           # OpenFOAM standard factory method
            "create",        # Common factory pattern
            "Create",        # Capitalized version
            "newInstance",   # Java-style factory
            "getInstance",   # Singleton getter
            "instance",      # Singleton pattern
            "clone",         # Prototype pattern
            "copy",          # Copy factory
            "factory",       # Direct factory reference
            "builder"        # Builder pattern
        ]
        factory_method_contains = [
            "new",           # stuff like newObj(), newInstance() and the like
            "make",          # C++ factory idiom (makeFoo, makeNew, etc.)
            "create",        # createFoo, createFrom, etc.
            "build",         # buildFoo, buildNew, etc.
            "construct",     # constructFoo, etc.
            "get",           # getInstanceOf, etc.
            "allocate",      # allocateFoo, etc.
            "instantiate",   # instantiateFoo, etc.
            "produce",       # produceFoo, etc.
            "from"           # fooFromBar, newFrom, etc.
        ]
        
        method_name = method.get("name", "")
        is_factory_pattern = method_name in factory_method_exact
        if not is_factory_pattern:
            is_factory_pattern = any(pattern in method_name.lower() for pattern in factory_method_contains)
        method_info = method.get("method_info", {})
        return_type = method_info.get("return_type", "") or method.get("result_type", "") or ""
        returns_class_type = class_name in return_type
        logger.debug(f"Factory method check: {method_name}, return type: {return_type}, class name: {class_name}, matches: {returns_class_type}")
        if not returns_class_type:
            returns_class_type = any(pattern in return_type for pattern in [
                f"*{class_name}",        # Raw pointer
                f"&{class_name}",        # Reference
                f"autoPtr<{class_name}",  # OpenFOAM smart pointer
                f"refPtr<{class_name}",   # OpenFOAM reference pointer
                f"tmp<{class_name}",      # OpenFOAM temporary
                f"unique_ptr<{class_name}", # C++ unique_ptr
                f"shared_ptr<{class_name}", # C++ shared_ptr
                f"Ptr<{class_name}",     # Generic smart pointer
                f"auto_ptr<{class_name}>", # Legacy C++ auto_ptr
                "autoPtr",               # Generic autoPtr without template
                "Ptr",                   # Generic Ptr without template
                "unique_ptr",            # Generic unique_ptr without template
                "shared_ptr"             # Generic shared_ptr without template
            ])
        if not returns_class_type and "dictionary" in return_type.lower():
            returns_class_type = True
        return is_factory_pattern and returns_class_type
        
    def _get_entity_factory_methods(self, entity: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get factory method information for an entity
        
        Args:
            entity: Entity dictionary
            
        Returns:
            List of factory method dictionaries with standardized format
        """
        factory_methods = []
        class_name = entity.get("name", "")
        if "children" not in entity:
            return factory_methods
        for child in entity.get("children", []):
            if self._is_factory_method(child, class_name):
                method_name = child.get("name", "")
                factory_info = self._format_method_info(child)
                method_entry = None
                for entry in factory_methods:
                    if entry.get("name") == method_name:
                        method_entry = entry
                        break
                if method_entry:
                    if "overloads" not in method_entry:
                        method_entry["overloads"] = []
                    method_entry["overloads"].append(factory_info)
                else:
                    new_entry = {"name": method_name, "overloads": [factory_info]}
                    factory_methods.append(new_entry)
                
        return factory_methods
        
    def _get_entity_standard_config(self, entity: Dict[str, Any]) -> str:
        """Get standard configuration for an entity
        
        Args:
            entity: Entity dictionary
            
        Returns:
            Standard configuration as string
        """
        # TODO: Standard class configuration needs reflection plugin
        # and possibly "Just-in-time compilation"
        return ""
        
    def _get_entity_public_bases(self, entity: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get public methods inherited from base classes for an entity
        
        This function queries the base_child_links table to find all base classes (both direct and
        indirect) that have PUBLIC access, and retrieves their public methods that will be inherited.
        
        Args:
            entity: Entity dictionary
            
        Returns:
            List of dictionaries containing base class info and their public methods
        """
        result = []
        entity_uuid = entity.get("uuid", "")
        if not entity_uuid:
            return result
        query = """
        SELECT e.uuid, e.name, e.namespace, bcl.direct, bcl.depth 
        FROM entities e
        JOIN base_child_links bcl ON e.uuid = bcl.base_uuid
        WHERE bcl.child_uuid = ? AND bcl.access_level = 'PUBLIC'
        ORDER BY bcl.depth ASC
        """
        
        try:
            self.db.cursor.execute(query, (entity_uuid,))
            for row in self.db.cursor.fetchall():
                base_uuid = row[0]
                base_name = row[1]
                base_namespace = row[2]
                is_direct = bool(row[3])
                depth = row[4]
                base_entity = self.db.get_entity_by_uuid(base_uuid)
                if not base_entity:
                    continue
                public_methods = []
                for child in base_entity.get("children", []):
                    if not child.get("kind", "") in ["CXX_METHOD", "FUNCTION_TEMPLATE"]:
                        continue
                    if child.get("access_specifier", "public").lower() != "public":
                        continue
                    method_name = child.get("name", "")
                    if method_name == base_name or method_name == f"~{base_name}":
                        continue
                    method_info = self._format_method_info(child)
                    method_entry = None
                    for entry in public_methods:
                        if entry.get("name") == method_name:
                            method_entry = entry
                            break
                    if method_entry:
                        if "overloads" not in method_entry:
                            method_entry["overloads"] = []
                        method_entry["overloads"].append(method_info)
                    else:
                        new_entry = {"name": method_name, "overloads": [method_info]}
                        public_methods.append(new_entry)
                base_info = {
                    "name": base_name,
                    "namespace": base_namespace,
                    "uuid": base_uuid,
                    "is_direct": is_direct,
                    "depth": depth,
                    "public_methods": public_methods
                }
                result.append(base_info)
                
        except Exception as e:
            logger.error(f"Error retrieving public base classes: {e}")
            
        return result
        
    def _get_entity_static_methods(self, entity: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get static method information for an entity
        
        Args:
            entity: Entity dictionary
            
        Returns:
            List of static method dictionaries with standardized format
        """
        static_methods = []
        class_name = entity.get("name", "")
        if "children" not in entity:
            return static_methods
        for child in entity.get("children", []):
            method_info = child.get("method_info", {})
            is_static = method_info.get("is_static", False)
            is_method = child.get("kind", "") in ["CXX_METHOD", "FUNCTION_TEMPLATE"]
            is_public = child.get("access_specifier", "public").lower() == "public"
            if not is_public:
                continue
            if is_method and is_static:
                if self._is_factory_method(child, class_name):
                    continue
                method_name = child.get("name", "")
                static_info = self._format_method_info(child)
                method_entry = None
                for entry in static_methods:
                    if entry.get("name") == method_name:
                        method_entry = entry
                        break
                if method_entry:
                    if "overloads" not in method_entry:
                        method_entry["overloads"] = []
                    method_entry["overloads"].append(static_info)
                else:
                    new_entry = {"name": method_name, "overloads": [static_info]}
                    static_methods.append(new_entry)
                
        return static_methods
        
    def _get_entity_abstract_methods(self, entity: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get abstract method information for an entity
        
        Args:
            entity: Entity dictionary
            
        Returns:
            List of abstract method dictionaries with standardized format
        """
        abstract_methods = []
        if "children" not in entity:
            return abstract_methods
        for child in entity.get("children", []):
            if not child.get("kind", "") in ["CXX_METHOD", "FUNCTION_TEMPLATE"]:
                continue
            if child.get("access_specifier", "public").lower() != "public":
                continue
            method_info = child.get("method_info", {})
            if method_info.get("is_pure_virtual", False):
                method_name = child.get("name", "")
                abstract_info = self._format_method_info(child)
                method_entry = None
                for entry in abstract_methods:
                    if entry.get("name") == method_name:
                        method_entry = entry
                        break
                if method_entry:
                    if "overloads" not in method_entry:
                        method_entry["overloads"] = []
                    method_entry["overloads"].append(abstract_info)
                else:
                    new_entry = {"name": method_name, "overloads": [abstract_info]}
                    abstract_methods.append(new_entry)
        return abstract_methods
        
    def _get_entity_abstract_in_base_methods(self, entity: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get abstract methods from base classes that are implemented in this class
        
        This function finds methods that:
        1. Are abstract (pure virtual) in base classes
        2. Are directly implemented in the current class
        3. Are public (to maintain interface section consistency)
        
        Args:
            entity: Entity dictionary
            
        Returns:
            List of implemented abstract method dictionaries
        """
        implemented_abstract_methods = []
        entity_uuid = entity.get("uuid", "")
        if not entity_uuid or "children" not in entity:
            return implemented_abstract_methods
        class_methods = {}
        for child in entity.get("children", []):
            if child.get("kind", "") in ["CXX_METHOD", "FUNCTION_TEMPLATE"] and \
               child.get("access_specifier", "public").lower() == "public":
                method_name = child.get("name", "")
                if method_name not in class_methods:
                    class_methods[method_name] = []
                class_methods[method_name].append(child)
        if not class_methods:
            return implemented_abstract_methods
        query = """
        SELECT e.uuid, e.name, bcl.access_level 
        FROM entities e
        JOIN base_child_links bcl ON e.uuid = bcl.base_uuid
        WHERE bcl.child_uuid = ? AND bcl.access_level IN ('PUBLIC', 'PROTECTED')
        """
        
        try:
            self.db.cursor.execute(query, (entity_uuid,))
            processed_methods = set()
            for row in self.db.cursor.fetchall():
                base_uuid = row[0]
                base_name = row[1]
                access_level = row[2]
                base_entity = self.db.get_entity_by_uuid(base_uuid)
                if not base_entity:
                    continue
                for child in base_entity.get("children", []):
                    if child.get("kind", "") not in ["CXX_METHOD", "FUNCTION_TEMPLATE"]:
                        continue
                    method_name = child.get("name", "")
                    if method_name == base_name or method_name == f"~{base_name}":
                        continue
                    method_access = child.get("access_specifier", "public").lower()
                    if access_level == "PUBLIC" and method_access not in ["public"]:
                        continue
                    if access_level == "PROTECTED" and method_access not in ["public", "protected"]:
                        continue
                    method_info = child.get("method_info", {})
                    if not method_info.get("is_pure_virtual", False):
                        continue
                    if method_name in processed_methods:
                        continue
                    if method_name in class_methods:
                        for impl in class_methods[method_name]:
                            processed_methods.add(method_name)
                            impl_info = self._format_method_info(impl)
                            base_file = base_entity.get("file", "")
                            transformed_file, _ = self._transform_file_path(base_file, base_name,
                                                                            base_entity.get("namespace", ""),
                                                                            template_pattern="method_doc_uri",
                                                                            entity=base_entity)
                            
                            impl_info["implements_abstract_from"] = {
                                "class_name": base_name,
                                "class_uuid": base_uuid,
                                "namespace": base_entity.get("namespace", ""),
                                "definition_file": transformed_file,
                                "access_level": access_level.lower(),
                            }
                            method_entry = None
                            for entry in implemented_abstract_methods:
                                if entry.get("name") == method_name:
                                    method_entry = entry
                                    break
                            if method_entry:
                                if "overloads" not in method_entry:
                                    method_entry["overloads"] = []
                                method_entry["overloads"].append(impl_info)
                            else:
                                new_entry = {"name": method_name, "overloads": [impl_info]}
                                implemented_abstract_methods.append(new_entry)
            self._abstract_implemented_methods = processed_methods
                
        except Exception as e:
            logger.error(f"Error finding abstract methods in base classes: {e}")
            self._abstract_implemented_methods = set()
            
        return implemented_abstract_methods
        
    def _get_entity_public_methods(self, entity: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get public method information for an entity
        
        Args:
            entity: Entity dictionary
            
        Returns:
            List of public method dictionaries with standardized format
        """
        public_methods = []
        if "children" not in entity:
            return public_methods
        excluded_methods = set()
        for ctor in self._get_entity_constructors(entity):
            excluded_methods.add(ctor.get("name", ""))
        for factory in self._get_entity_factory_methods(entity):
            excluded_methods.add(factory.get("name", ""))
        for static in self._get_entity_static_methods(entity):
            excluded_methods.add(static.get("name", ""))
        for abstract in self._get_entity_abstract_methods(entity):
            excluded_methods.add(abstract.get("name", ""))
        abstract_implementations = self._get_entity_abstract_in_base_methods(entity)
        if hasattr(self, '_abstract_implemented_methods'):
            excluded_methods.update(self._abstract_implemented_methods)
        for child in entity.get("children", []):
            if not child.get("kind", "") in ["CXX_METHOD", "FUNCTION_TEMPLATE"]:
                continue
            method_name = child.get("name", "")
            if method_name in excluded_methods:
                continue
            if child.get("access_specifier", "public").lower() != "public":
                continue
            public_info = self._format_method_info(child)
            method_entry = None
            for entry in public_methods:
                if entry.get("name") == method_name:
                    method_entry = entry
                    break
            if method_entry:
                if "overloads" not in method_entry:
                    method_entry["overloads"] = []
                method_entry["overloads"].append(public_info)
            else:
                new_entry = {"name": method_name, "overloads": [public_info]}
                public_methods.append(new_entry)
                
        return public_methods
        
    def _get_entity_rts_info(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        """Get OpenFOAM RunTimeSelection information for an entity
        
        This function checks for OpenFOAM RunTime Selection tables and mechanisms.
        It looks for custom fields added by the OpenFOAM plugin to identify:
        - Base classes that define RTS tables
        - Child classes that register with those tables
        - The selection mechanisms and table names
        - Relationships between RTS base classes and their derived implementations
        
        Args:
            entity: Entity dictionary
            
        Returns:
            RTS information dictionary with comprehensive details
        """
        has_openfoam_rts_fields = False
        try:
            query = """
            SELECT COUNT(*) FROM custom_entity_fields 
            WHERE field_name LIKE 'openfoam_rts%'
            """
            self.db.cursor.execute(query)
            count = self.db.cursor.fetchone()[0]
            has_openfoam_rts_fields = count > 0
        except Exception as e:
            logger.error(f"Error checking OpenFOAM RTS plugin status: {e}")
        custom_fields = entity.get("custom_fields", {})
        if not has_openfoam_rts_fields:
            return {
                "plugin_active": False,
                "note": "OpenFOAM RTS mechanisms not detected in codebase"
            }
        rts_info = {
            "plugin_active": True,
            "is_RTS_base": False,
            "RTS_table_names": [],
            "is_RTS_child": False,
            "base_RTS_classes": [],
            "class_role": "unknown"
        }
        entity_uuid = entity.get("uuid", "")
        if not entity_uuid:
            return rts_info
        try:
            self.db.cursor.execute("""
            SELECT text_value FROM custom_entity_fields
            WHERE entity_uuid = ? AND field_name = 'openfoam_rts_status'
            """, (entity_uuid,))
            status_row = self.db.cursor.fetchone()
            if status_row:
                rts_info["rts_status"] = status_row[0]
        except Exception as e:
            logger.error(f"Error retrieving RTS status: {e}")
        try:
            self.db.cursor.execute("""
            SELECT text_value FROM custom_entity_fields
            WHERE entity_uuid = ? AND field_name = 'openfoam_class_role'
            """, (entity_uuid,))
            role_row = self.db.cursor.fetchone()
            if role_row:
                rts_info["class_role"] = role_row[0]
                if role_row[0] == "base":
                    rts_info["is_RTS_base"] = True
                elif role_row[0] == "child":
                    rts_info["is_RTS_child"] = True
        except Exception as e:
            logger.error(f"Error retrieving class role: {e}")
        try:
            self.db.cursor.execute("""
            SELECT text_value FROM custom_entity_fields
            WHERE entity_uuid = ? AND field_name = 'openfoam_rts_names'
            """, (entity_uuid,))
            names_row = self.db.cursor.fetchone()
            if names_row and names_row[0]:
                rts_table_names = names_row[0].split('|')
                rts_info["RTS_table_names"] = rts_table_names
                if rts_table_names:
                    rts_info["is_RTS_base"] = True
        except Exception as e:
            logger.error(f"Error retrieving RTS table names: {e}")
        try:
            self.db.cursor.execute("""
            SELECT text_value FROM custom_entity_fields
            WHERE entity_uuid = ? AND field_name = 'openfoam_rts_types'
            """, (entity_uuid,))
            types_row = self.db.cursor.fetchone()
            if types_row and types_row[0]:
                rts_info["RTS_table_types"] = types_row[0].split('|')
        except Exception as e:
            logger.error(f"Error retrieving RTS table types: {e}")
        try:
            self.db.cursor.execute("""
            SELECT text_value FROM custom_entity_fields
            WHERE entity_uuid = ? AND field_name = 'openfoam_rts_count'
            """, (entity_uuid,))
            count_row = self.db.cursor.fetchone()
            if count_row and count_row[0]:
                rts_info["RTS_table_count"] = int(count_row[0])
        except Exception as e:
            logger.error(f"Error retrieving RTS table count: {e}")
        if rts_info["is_RTS_base"] and rts_info["RTS_table_names"]:
            try:
                implemented_classes = []
                for table_name in rts_info["RTS_table_names"]:
                    self.db.cursor.execute("""
                    SELECT e.uuid, e.name 
                    FROM entities e
                    JOIN custom_entity_fields cf ON e.uuid = cf.entity_uuid
                    WHERE cf.field_name LIKE 'openfoam_rts_child_%'
                    AND cf.text_value = ?
                    """, (table_name,))
                    
                    for row in self.db.cursor.fetchall():
                        implemented_classes.append({
                            "uuid": row[0],
                            "name": row[1],
                            "table": table_name
                        })
                        
                if implemented_classes:
                    rts_info["implemented_classes"] = implemented_classes
            except Exception as e:
                logger.error(f"Error retrieving implemented classes: {e}")
        
        if rts_info["is_RTS_child"] or rts_info.get("class_role") == "child":
            try:
                self.db.cursor.execute("""
                SELECT field_name, text_value 
                FROM custom_entity_fields
                WHERE entity_uuid = ? AND field_name LIKE 'openfoam_rts_child_%'
                """, (entity_uuid,))
                implemented_tables = []
                for row in self.db.cursor.fetchall():
                    table_name = row[1]
                    implemented_tables.append(table_name)
                    self.db.cursor.execute("""
                    SELECT e.uuid, e.name 
                    FROM entities e
                    JOIN custom_entity_fields cf ON e.uuid = cf.entity_uuid
                    WHERE (cf.field_name = 'openfoam_rts_name_1' OR 
                          cf.field_name = 'openfoam_rts_name_2' OR 
                          cf.field_name = 'openfoam_rts_name_3')
                    AND cf.text_value = ?
                    """, (table_name,))
                    for base_row in self.db.cursor.fetchall():
                        base_uuid = base_row[0]
                        base_name = base_row[1]
                        rts_info["base_RTS_classes"].append({
                            "uuid": base_uuid,
                            "name": base_name,
                            "table": table_name
                        })
                if implemented_tables:
                    rts_info["implemented_tables"] = implemented_tables
                    rts_info["is_RTS_child"] = True
            except Exception as e:
                logger.error(f"Error retrieving base RTS classes: {e}")
                
        return rts_info
        
    def _get_entity_reflection_info(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        """Get OpenFOAM reflection information for this entity

        This method extracts reflection information from the entity custom fields.
        It provides details about reflectable classes including:
        - Whether the class supports reflection via the SchemaTable mechanism
        - The standard configuration extracted from the reflection
        - Detailed configuration information including types and defaults
        
        Args:
            entity: Entity to process

        Returns:
            Dictionary with reflection information
        """
        reflection_info = {
            "is_reflectable": False,
            "reflection_type": "",
            "standard_config": "",
            "standard_config_details": "",
            "reflection_error": ""
        }

        try:
            # Check if this entity has reflection information in custom fields
            if 'custom_fields' in entity and 'is_reflectable' in entity['custom_fields']:
                reflection_info["is_reflectable"] = bool(entity['custom_fields'].get('is_reflectable'))
                
                if 'reflection_type' in entity['custom_fields']:
                    reflection_info["reflection_type"] = entity['custom_fields'].get('reflection_type')
                
                if 'standard_config' in entity['custom_fields']:
                    reflection_info["standard_config"] = entity['custom_fields'].get('standard_config')
                
                if 'standard_config_details' in entity['custom_fields']:
                    reflection_info["standard_config_details"] = entity['custom_fields'].get('standard_config_details')
                
                if 'reflection_error' in entity['custom_fields']:
                    reflection_info["reflection_error"] = entity['custom_fields'].get('reflection_error')

                if reflection_info["is_reflectable"]:
                    logger.info(f"Reflection information extracted for {entity.get('name', 'unknown entity')}")
        except Exception as e:
            logger.error(f"Error retrieving reflection information: {e}")

        return reflection_info
        
    def _get_entity_unit_tests(self, entity: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get unit test information for an entity
        
        This method detects unit tests for a specific C++ class by:
        1. Looking for a separate unit tests database based on project name
        2. Parsing Catch2-style unit tests with tree-sitter parser
        3. Searching for references to the class name in test cases
        
        It uses markdown.frontmatter.entities.unit_tests_compile_commands_dir from config.yaml
        to override the parser.compile_commands_dir for unit test parsing.
        
        Args:
            entity: Entity dictionary
            
        Returns:
            List of unit test dictionaries containing test file, name, and location
        """
        if not entity or not entity.get("name"):
            return []
        class_name = entity.get("name")
        entity_uuid = entity.get("uuid", "")
        if not entity_uuid:
            return []
        unit_tests_enabled = self.config.get("markdown.frontmatter.entities.unit_tests", True) if self.config else True
        if not unit_tests_enabled:
            logger.info(f"Unit test detection disabled in config for {class_name}")
            return []
        # Get the main DB path either from the database object or config
        main_db_path = self.db.db_path
        if not main_db_path and self.config:
            main_db_path = self.config.get("database.path")
            
        if not main_db_path:
            logger.warning("Cannot determine main database path for unit tests")
            return []
            
        # Create a consistent name for the unit tests database
        project_name = os.path.splitext(os.path.basename(main_db_path))[0]
        unit_tests_db_path = os.path.join(os.path.dirname(main_db_path), f"{project_name}_unit_tests.db")
        
        if not os.path.exists(unit_tests_db_path):
            logger.info(f"Unit tests database not found at {unit_tests_db_path}, will create it")
            unit_tests_dir = self.config.get("markdown.frontmatter.entities.unit_tests_compile_commands_dir", None)
            logger.info(f"Attempting to load unittests from {unit_tests_dir}")
            if not unit_tests_dir:
                logger.info(f"No unit tests compile commands directory specified in config")
                return []
            compile_commands_path = os.path.join(unit_tests_dir, "compile_commands.json")
            if not os.path.exists(compile_commands_path):
                logger.warning(f"No compile_commands.json found at {compile_commands_path}")
                return []
                
            try:
                logger.info(f"Creating unit tests database at {unit_tests_db_path} from {unit_tests_dir}")
                
                from .config import Config
                if self.config:
                    if self.config_path and os.path.exists(self.config_path):
                        unit_tests_config = Config(self.config_path)
                    else:
                        unit_tests_config = self.config
                else:
                    unit_tests_config = Config()
                from omegaconf import OmegaConf
                config_dict = OmegaConf.to_container(unit_tests_config.config)
                
                if 'parser' not in config_dict:
                    config_dict['parser'] = {}
                config_dict['parser']['compile_commands_dir'] = unit_tests_dir
                if 'database' not in config_dict:
                    config_dict['database'] = {}
                config_dict['database']['path'] = unit_tests_db_path
                unit_tests_config.config = OmegaConf.create(config_dict)
                from .db import EntityDatabase
                from .parse import ClangParser, get_source_files_from_compilation_database
                unit_tests_db = EntityDatabase(unit_tests_db_path, create_tables=True)
                parser = ClangParser(
                    compilation_database_dir=unit_tests_dir,
                    db=unit_tests_db,
                    config=unit_tests_config
                )
                parser.use_tree_sitter_fallback = True
                logger.info("Forcing Tree-sitter parser for unit tests")
                try:
                    target_files = get_source_files_from_compilation_database(unit_tests_dir)
                    if not target_files:
                        logger.warning(f"No source files found in unit tests compilation database")
                        return []
                        
                    logger.info(f"Parsing {len(target_files)} unit test files")
                    parsed_count = 0
                    error_count = 0
                    
                    for filepath in target_files:
                        try:
                            if not os.path.exists(filepath):
                                logger.warning(f"Unit test file not found: {filepath}")
                                error_count += 1
                                continue
                            file_stats = os.stat(filepath)
                            last_modified = int(file_stats.st_mtime)
                            with open(filepath, 'rb') as f:
                                file_content = f.read()
                                file_hash = hashlib.md5(file_content).hexdigest()
                            unit_tests_db.track_file(filepath, last_modified, file_hash)
                            logger.info(f"Parsing unit test file: {filepath}")
                            try:
                                compile_args = parser.get_compile_commands(filepath)
                                if compile_args:
                                    filtered_args = []
                                    skip_next = False
                                    for i, arg in enumerate(compile_args):
                                        if skip_next:
                                            skip_next = False
                                            continue
                                        if arg.endswith('.a') or arg.endswith('.so') or arg.endswith('.dylib'):
                                            continue
                                        if arg in ['-o', '--output']:
                                            skip_next = True
                                            continue
                                        if arg.endswith('.o'):
                                            continue
                                        filtered_args.append(arg)
                                    logger.debug(f"Using filtered compilation arguments: {filtered_args}")
                                    original_get_compile_commands = parser.get_compile_commands
                                    parser.get_compile_commands = lambda _: filtered_args
                            except Exception as arg_e:
                                logger.warning(f"Error filtering compilation arguments: {arg_e}")
                            try:
                                entities = parser.parse_file(filepath, force_tree_sitter=True)
                            except Exception as parse_error:
                                logger.warning(f"Unit test parsing failed with Tree-sitter: {parse_error}")
                                raise
                            if entities:
                                for entity in entities:
                                    parser._export_entity(unit_tests_db, entity)
                                parsed_count += 1
                                logger.info(f"Parsed {len(entities)} entities from {filepath}")
                            else:
                                logger.warning(f"No entities found in {filepath}")
                                error_count += 1
                        except Exception as file_e:
                            logger.warning(f"Error parsing unit test file {filepath}: {file_e}")
                            error_count += 1
                    logger.info("Resolving inheritance relationships in unit tests...")
                    parser.resolve_inheritance_relationships()
                    logger.info(f"Successfully created unit tests database at {unit_tests_db_path} with {parsed_count} files parsed")
                    if hasattr(entity, 'to_dict'):
                        entity_dict = entity.to_dict()
                        logger.info(f"Converting Entity object to dictionary for recursive call")
                    else:
                        entity_dict = entity
                    return self._get_entity_unit_tests(entity_dict)  # Recursive call, will take the load path
                except Exception as e:
                    logger.error(f"Error getting source files from unit tests compilation database: {e}")
                    return []
            except Exception as e:
                logger.error(f"Error creating unit tests database: {e}")
                return []
        
        # Now load the unit tests database (using cache if available)
        try:
            if unit_tests_db_path in MarkdownGenerator._unit_tests_db_cache:
                unit_tests_db = MarkdownGenerator._unit_tests_db_cache[unit_tests_db_path]
                logger.debug(f"Using cached unit tests database from {unit_tests_db_path}")
            else:
                from .db import EntityDatabase
                unit_tests_db = EntityDatabase(unit_tests_db_path)
                MarkdownGenerator._unit_tests_db_cache[unit_tests_db_path] = unit_tests_db
                if MarkdownGenerator._verbose_unit_tests_logging:
                    logger.info(f"Loaded unit tests database from {unit_tests_db_path}")
                    MarkdownGenerator._verbose_unit_tests_logging = False
                else:
                    logger.debug(f"Loaded unit tests database from {unit_tests_db_path} (subsequent load)")
        except Exception as e:
            logger.error(f"Error loading unit tests database: {e}")
            return []
            
        unit_tests = []
        try:
            uuid_query = f"""
            SELECT entity_uuid 
            FROM custom_entity_fields
            WHERE field_name = 'tree_sitter_references'
            AND text_value LIKE '%{class_name}%'
            """
            unit_tests_db.cursor.execute(uuid_query)
            matching_uuids = [row[0] for row in unit_tests_db.cursor.fetchall()]
            potential_tests = []
            if matching_uuids:
                uuid_str = ",".join([f"'{uuid}'" for uuid in matching_uuids])
                entity_query = f"""
                SELECT uuid, name, kind, file, line, end_line, parent_uuid
                FROM entities 
                WHERE uuid IN ({uuid_str})
                """
                unit_tests_db.cursor.execute(entity_query)
                potential_tests = unit_tests_db.cursor.fetchall()
                for row in potential_tests:
                    test_uuid = row[0]
                    test_name = row[1]
                    test_file = row[3]
                    test_line = row[4]
                    test_end_line = row[5]
                    metadata_query = """
                    SELECT field_name, text_value FROM custom_entity_fields 
                    WHERE entity_uuid = ?
                    """
                    unit_tests_db.cursor.execute(metadata_query, (test_uuid,))
                    metadata_rows = unit_tests_db.cursor.fetchall()
                    meta_dict = {}
                    for field_name, text_value in metadata_rows:
                        meta_dict[field_name] = text_value
                    description = ""
                    tags = ""
                    references = []
                    test_kind = "TEST_CASE"  # Default kind
                    if 'test_description' in meta_dict:
                        description = meta_dict['test_description']
                    if 'tags' in meta_dict:
                        tags = meta_dict['tags']
                    if not description and "TEST_CASE" in test_name:
                        desc_match = re.search(r'TEST_CASE\s*\(\s*"([^"]+)"', test_name)
                        if desc_match:
                            description = desc_match.group(1)
                        if not tags:
                            tags_match = re.search(r'TEST_CASE\s*\(\s*"[^"]+"\s*,\s*"([^"]+)"', test_name)
                            if tags_match:
                                tags = tags_match.group(1)
                    if 'tree_sitter_references' in meta_dict:
                        references = [r.strip() for r in meta_dict['tree_sitter_references'].split(';') if r.strip()]
                    base_file = test_file
                    try:
                        git_root = None
                        if os.path.exists(base_file):
                            git_root = get_git_root(os.path.dirname(base_file))
                        if git_root and base_file.startswith(git_root):
                            rel_path = os.path.relpath(base_file, git_root)
                            base_file = rel_path
                    except Exception as e:
                        logger.debug(f"Could not make file path relative to git repo: {e}")
                        
                    file_with_lines = test_file
                    if test_line and test_end_line:
                        if '#' not in file_with_lines:
                            file_with_lines = f"{file_with_lines}#L{test_line}-L{test_end_line}"
                    transformed_file, _ = self._transform_file_path(
                        file_with_lines,
                        test_name,
                        namespace="",
                        template_pattern="unit_test_uri")
                    test_entry = {
                        "name": description if description else test_name,
                        "file": transformed_file,
                        "kind": test_kind
                    }
                    if tags:
                        test_entry["tags"] = tags
                    unit_tests.append(test_entry)
                    logger.debug(f"Added test case {test_name} for class {class_name}")
            
        except Exception as e:
            import traceback
            logger.error(f"Error searching for unit tests: {e}\n{traceback.format_exc()}")
            
        return unit_tests
        
    def _get_entity_knowledge_requirements(self, entity: Dict[str, Any]) -> List[str]:
        """Get knowledge requirements for understanding an entity
        
        Analyzes class structure, methods, and OpenFOAM-specific features to determine
        what knowledge is required to understand this entity.
        
        Args:
            entity: Entity dictionary
            
        Returns:
            Flat list of knowledge requirements
        """
        requirements = set()
        if entity.get("kind") not in ['CLASS_DECL', 'CLASS_TEMPLATE', 'STRUCT_DECL', 'STRUCT_TEMPLATE']:
            return []
        requirements.add("classes")
        entity_uuid = entity.get("uuid")
        if entity_uuid and self.db:
            try:
                self.db.cursor.execute(
                    """SELECT f.name 
                       FROM features f 
                       JOIN entity_features ef ON f.id = ef.feature_id 
                       WHERE ef.entity_uuid = ?""", 
                    (entity_uuid,)
                )
                for row in self.db.cursor.fetchall():
                    feature_name = row[0]
                    if feature_name:
                        if feature_name == "openfoam":
                            requirements.add("openfoam_basics")
                        else:
                            requirements.add(feature_name)
                logger.debug(f"Found {len(requirements)} features for class {entity.get('name')} from database")
                methods = []
                methods.extend(entity.get("methods", []))
                methods.extend(entity.get("constructors", []))
                if entity.get("destructor"):
                    methods.append(entity.get("destructor"))
                
                for method in methods:
                    method_uuid = method.get("uuid")
                    if method_uuid:
                        self.db.cursor.execute(
                            """SELECT f.name 
                               FROM features f 
                               JOIN entity_features ef ON f.id = ef.feature_id 
                               WHERE ef.entity_uuid = ?""", 
                            (method_uuid,)
                        )
                        
                        for row in self.db.cursor.fetchall():
                            feature_name = row[0]
                            if feature_name:
                                requirements.add(feature_name)
                
            except Exception as e:
                logger.warning(f"Error retrieving features for class {entity.get('name')}: {e}")
        
        if len(requirements) <= 1:  # Only has "classes" requirement
            bases = entity.get("bases", [])
            if bases:
                requirements.add("inheritance")
                if len(bases) > 1:
                    requirements.add("multiple_inheritance")
            if entity.get("template_parameters", []):
                requirements.add("templates")
            for method in methods:
                method_info = method.get("method_info", {})
                if method_info.get("is_virtual", False):
                    requirements.add("virtual_functions")
                    break

        # Check for RTS usage
        custom_fields = entity.get("custom_fields", {})
        rts_tables = []
        if custom_fields.get("openfoam_rts_count", 0) > 0:
            rts_tables = custom_fields.get("openfoam_rts_names").split('|')
            requirements.add("openfoam_rts")
        return sorted(list(requirements))
        
    def _get_entity_protected_bases(self, entity: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get protected methods inherited from base classes for an entity
        
        This function queries the base_child_links table to find all base classes (both direct and
        indirect) that have PROTECTED access, and retrieves their methods that will be inherited.
        
        Args:
            entity: Entity dictionary
            
        Returns:
            List of dictionaries containing base class info and their protected methods
        """
        result = []
        entity_uuid = entity.get("uuid", "")
        
        if not entity_uuid:
            return result
        query = """
        SELECT e.uuid, e.name, e.namespace, bcl.direct, bcl.depth 
        FROM entities e
        JOIN base_child_links bcl ON e.uuid = bcl.base_uuid
        WHERE bcl.child_uuid = ? AND bcl.access_level = 'PROTECTED'
        ORDER BY bcl.depth ASC
        """
        
        try:
            self.db.cursor.execute(query, (entity_uuid,))
            for row in self.db.cursor.fetchall():
                base_uuid = row[0]
                base_name = row[1]
                base_namespace = row[2]
                is_direct = bool(row[3])
                depth = row[4]
                base_entity = self.db.get_entity_by_uuid(base_uuid)
                if not base_entity:
                    continue
                protected_methods = []
                for child in base_entity.get("children", []):
                    if not child.get("kind", "") in ["CXX_METHOD", "FUNCTION_TEMPLATE"]:
                        continue
                    if child.get("access_specifier", "public").lower() != "protected":
                        continue
                    method_name = child.get("name", "")
                    if method_name == base_name or method_name == f"~{base_name}":
                        continue
                    method_info = self._format_method_info(child)
                    method_entry = None
                    for entry in protected_methods:
                        if entry.get("name") == method_name:
                            method_entry = entry
                            break
                    if method_entry:
                        if "overloads" not in method_entry:
                            method_entry["overloads"] = []
                        method_entry["overloads"].append(method_info)
                    else:
                        new_entry = {"name": method_name, "overloads": [method_info]}
                        protected_methods.append(new_entry)
                base_info = {
                    "name": base_name,
                    "namespace": base_namespace,
                    "uuid": base_uuid,
                    "is_direct": is_direct,
                    "depth": depth,
                    "protected_methods": protected_methods
                }
                
                result.append(base_info)
                
        except Exception as e:
            logger.error(f"Error retrieving protected base classes: {e}")
            
        return result
        
    def _get_entity_protected_methods(self, entity: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get protected method information for an entity
        
        Args:
            entity: Entity dictionary
            
        Returns:
            List of protected method dictionaries with standardized format
        """
        protected_methods = []
        if "children" not in entity:
            return protected_methods
        excluded_methods = set()
        for child in entity.get("children", []):
            if not child.get("kind", "") in ["CXX_METHOD", "FUNCTION_TEMPLATE"]:
                continue
            if child.get("access_specifier", "public").lower() != "protected":
                continue
            method_name = child.get("name", "")
            if method_name in excluded_methods:
                continue
            class_name = entity.get("name", "")
            if method_name == class_name or method_name == f"~{class_name}":
                continue
            protected_info = self._format_method_info(child)
            method_entry = None
            for entry in protected_methods:
                if entry.get("name") == method_name:
                    method_entry = entry
                    break
            
            if method_entry:
                if "overloads" not in method_entry:
                    method_entry["overloads"] = []
                method_entry["overloads"].append(protected_info)
            else:
                new_entry = {"name": method_name, "overloads": [protected_info]}
                protected_methods.append(new_entry)
                
        return protected_methods
        
    def _get_entity_private_bases(self, entity: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get private methods inherited from base classes for an entity
        
        This function queries the base_child_links table to find all base classes (both direct and
        indirect) that have PRIVATE access, and retrieves their methods that will be inherited.
        
        Args:
            entity: Entity dictionary
            
        Returns:
            List of dictionaries containing base class info and their private methods
        """
        result = []
        entity_uuid = entity.get("uuid", "")
        
        if not entity_uuid:
            return result
        query = """
        SELECT e.uuid, e.name, e.namespace, bcl.direct, bcl.depth 
        FROM entities e
        JOIN base_child_links bcl ON e.uuid = bcl.base_uuid
        WHERE bcl.child_uuid = ? AND bcl.access_level = 'PRIVATE'
        ORDER BY bcl.depth ASC
        """
        
        try:
            self.db.cursor.execute(query, (entity_uuid,))
            for row in self.db.cursor.fetchall():
                base_uuid = row[0]
                base_name = row[1]
                base_namespace = row[2]
                is_direct = bool(row[3])
                depth = row[4]
                base_entity = self.db.get_entity_by_uuid(base_uuid)
                if not base_entity:
                    continue
                private_methods = []
                for child in base_entity.get("children", []):
                    if not child.get("kind", "") in ["CXX_METHOD", "FUNCTION_TEMPLATE"]:
                        continue
                    method_name = child.get("name", "")
                    if method_name == base_name or method_name == f"~{base_name}":
                        continue
                    method_info = self._format_method_info(child)
                    method_entry = None
                    for entry in private_methods:
                        if entry.get("name") == method_name:
                            method_entry = entry
                            break
                    if method_entry:
                        if "overloads" not in method_entry:
                            method_entry["overloads"] = []
                        method_entry["overloads"].append(method_info)
                    else:
                        new_entry = {"name": method_name, "overloads": [method_info]}
                        private_methods.append(new_entry)
                base_info = {
                    "name": base_name,
                    "namespace": base_namespace,
                    "uuid": base_uuid,
                    "is_direct": is_direct,
                    "depth": depth,
                    "private_methods": private_methods,
                    "note": "Private methods are not accessible from derived classes in C++, shown for documentation purposes only."
                }
                
                result.append(base_info)
                
        except Exception as e:
            logger.error(f"Error retrieving private base classes: {e}")
            
        return result
        
    def _get_entity_private_methods(self, entity: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get private method information for an entity
        
        Args:
            entity: Entity dictionary
            
        Returns:
            List of private method dictionaries with standardized format
        """
        private_methods = []
        
        if "children" not in entity:
            return private_methods
        excluded_methods = set()
        for child in entity.get("children", []):
            if not child.get("kind", "") in ["CXX_METHOD", "FUNCTION_TEMPLATE"]:
                continue
            if child.get("access_specifier", "public").lower() != "private":
                continue
            method_name = child.get("name", "")
            if method_name in excluded_methods:
                continue
            class_name = entity.get("name", "")
            if method_name == class_name or method_name == f"~{class_name}":
                continue
            private_info = self._format_method_info(child)
            method_entry = None
            for entry in private_methods:
                if entry.get("name") == method_name:
                    method_entry = entry
                    break
            
            if method_entry:
                if "overloads" not in method_entry:
                    method_entry["overloads"] = []
                method_entry["overloads"].append(private_info)
            else:
                new_entry = {"name": method_name, "overloads": [private_info]}
                private_methods.append(new_entry)
                
        return private_methods
        
    def _get_entity_mpi_comms(self, entity: Dict[str, Any]) -> Dict[str, bool]:
        """Get MPI communication details for an entity
        
        Args:
            entity: Entity dictionary
            
        Returns:
            MPI communication details dictionary
        """
        # TODO: Implement proper MPI communication details detection
        return {
            "parallel_streams": False,
            "random_access_lists": False,
            "linked_lists": False,
            "has_member_reference": False,
            "handles_member_reference_through_mpi": False
        }  # Placeholder
        
    def _get_entity_contributors(self, entity: Dict[str, Any]) -> List[str]:
        """Get list of contributors for an entity from Git history
        
        Args:
            entity: Entity dictionary
            
        Returns:
            List of contributor names
        """
        from .git import get_file_authors_by_line_range, is_git_repository
        
        contributors = set()
        file_path = entity.get('file')
        
        if not file_path or not os.path.exists(file_path):
            file_path = entity.get('declaration_file')
            if file_path and '#' in file_path:
                file_path = file_path.split('#')[0]
                
        if not file_path or not os.path.exists(file_path) or not is_git_repository(os.path.dirname(file_path)):
            return ["__unknown__"]
            
        start_line = entity.get('line') or entity.get('start_line')
        end_line = entity.get('end_line') or start_line
        if start_line and end_line and start_line != end_line:
            authors_info = get_file_authors_by_line_range(file_path, start_line, end_line)
            for author_info in authors_info:
                if 'author' in author_info:
                    contributors.add(author_info['author'])
        else:
            # Fallback - if line range is null or same, get all authors for the file
            try:
                with open(file_path, 'r') as f:
                    num_lines = sum(1 for _ in f)
                authors_info = get_file_authors_by_line_range(file_path, 1, num_lines)
                for author_info in authors_info:
                    if 'author' in author_info:
                        contributors.add(author_info['author'])
            except Exception as e:
                logger.warning(f"Error getting file line count: {e}")
                return ["__unknown__"]
                
        return list(contributors) if contributors else ["__unknown__"]


def main():
    """Main entry point for markdown generation"""
    # First check for version flag without enforcing required arguments
    version_parser = argparse.ArgumentParser(add_help=False)
    version_parser.add_argument("--version", action="store_true", help="Show version information and exit")
    
    # Parse only the known args first to check for version
    version_args, _ = version_parser.parse_known_args()
    
    if version_args.version:
        logger.info(f"foamCD {get_version()}")
        return 0
    
    # If not showing version, use the regular parser with required arguments
    parser = argparse.ArgumentParser(description="Generate markdown documentation from foamCD database")
    parser.add_argument("--db", dest="db_path", required=True, help="Path to foamCD SQLite database")
    parser.add_argument("--output", dest="output_path", required=True, help="Path to output markdown files")
    parser.add_argument("--project", dest="project_dir", default=None, help="Project directory to filter entities by")
    parser.add_argument("--config", dest="config_path", default=None, help="Path to configuration file")
    parser.add_argument("--version", action="store_true", help="Show version information and exit")
    args = parser.parse_args()
    
    # Version check is handled above, but keep this for completeness
    if args.version:
        logger.info(f"foamCD {get_version()}")
        return 0
    
    try:
        generator = MarkdownGenerator(
            db_path=args.db_path,
            output_path=args.output_path,
            project_dir=args.project_dir,
            config_path=args.config_path
        )
        generator.generate_all()
        return 0
    except Exception as e:
        logger.error(f"Error generating markdown: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 1


if __name__ == '__main__':
    sys.exit(main() or 0)
