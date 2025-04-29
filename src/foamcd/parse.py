#!/usr/bin/env python3

import os
import sys
import hashlib
import argparse
import platform
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Any, Union

try:
    from .tree_sitter_subparser import TreeSitterSubparser, is_tree_sitter_available
    TREE_SITTER_IMPORT_SUCCESS = True
except ImportError:
    TREE_SITTER_IMPORT_SUCCESS = False

from .logs import setup_logging
from .db import EntityDatabase
from .config import Config
from .version import get_version
from .feature_detectors import FeatureDetectorRegistry, DeprecatedAttributeDetector
from .plugin_system import PluginManager
from clang.cindex import CursorKind

logger = setup_logging()

from .common import CPP_HEADER_EXTENSIONS, CPP_IMPLEM_EXTENSIONS, CPP_FILE_EXTENSIONS
CURRENT_PARSER = None

def configure_libclang(libclang_path: Optional[str] = None):
    """Configure libclang library path if necessary
    
    Args:
        libclang_path: Optional path to libclang library specified in configuration
    """
    try:
        import clang.cindex
        logger.debug(f"Python libclang module loaded from: {clang.__file__}")
        if libclang_path:
            try:
                clang.cindex.Config.set_library_file(libclang_path)
                clang.cindex.Index.create()
                logger.info(f"Using libclang from configured path: {libclang_path}")
                return True
            except Exception as e:
                logger.warning(f"Could not use configured libclang path '{libclang_path}': {e}")
                
        try:
            clang.cindex.Index.create()
            logger.info("Default libclang configuration works without additional setup")
            return True
        except Exception as e:
            logger.debug(f"Default libclang not accessible: {e}")
            logger.debug("Attempting to locate libclang library manually...")
            pass
            
        # Common library locations and versions
        possible_lib_paths = [
            '/usr/lib',
            '/usr/lib/llvm-*/lib',
            '/usr/lib/x86_64-linux-gnu',
            '/usr/local/lib',
            '/usr/local/opt/llvm/lib',
            '/lib/x86_64-linux-gnu',
        ]
        
        logger.debug(f"Searching for libclang in common locations: {possible_lib_paths}")
        for base_path in possible_lib_paths:
            if '*' in base_path:
                import glob
                expanded_paths = glob.glob(base_path)
            else:
                expanded_paths = [base_path]
            for path in expanded_paths:
                if os.path.exists(path):
                    logger.debug(f"Checking directory: {path}")
                    lib_files = [f for f in os.listdir(path) if f.startswith('libclang') and f.endswith('.so')]
                    if lib_files:
                        logger.debug(f"Found potential libclang libraries in {path}: {lib_files}")
                    else:
                        logger.debug(f"No libclang libraries found in {path}")
                    for lib_file in lib_files:
                        full_path = os.path.join(path, lib_file)
                        if os.path.islink(full_path):
                            real_path = os.path.realpath(full_path)
                            logger.debug(f"{full_path} is a symlink to {real_path}")
                            if not os.path.exists(real_path):
                                logger.warning(f"Symlink target {real_path} does not exist!")
                                continue
                        try:
                            logger.debug(f"Attempting to configure with: {full_path}")
                            clang.cindex.Config.set_library_file(full_path)
                            clang.cindex.Index.create()
                            logger.info(f"Successfully configured libclang with: {full_path}")
                            return True
                        except Exception as e:
                            logger.debug(f"Failed to configure libclang with {full_path}: {e}")
                            continue
        # If we get here, we couldn't find a working libclang
        logger.warning("Could not find a working libclang library.")
        return False
    except ImportError:
        import traceback
        logger.error(f"libclang Python module not found. \nTraceback: {traceback.format_exc()}")
        return False

config = Config()

# Try to configure libclang
libclang_path = config.get('parser.libclang_path')
LIBCLANG_CONFIGURED = configure_libclang(libclang_path)
if not LIBCLANG_CONFIGURED:
    logger.warning("Failed to configure libclang. Functionality requiring libclang will be limited.")
    logger.warning("Locations checked: /lib/x86_64-linux-gnu/, /usr/lib/, etc. Did you install libclang?")
    logger.warning("Add 'parser.libclang_path' to your configuration file to explicitly specify the location of libclang.so")

import clang.cindex
from clang.cindex import CursorKind, TokenKind, TypeKind, AccessSpecifier, LinkageKind
from .entity import Entity

# Map to track C++ language features by version
CPP_FEATURES = {
    # C++98/03 features
    'cpp98': {
        'classes', 'inheritance', 'templates', 'exceptions', 'namespaces',
        'operator_overloading', 'function_overloading', 'references',
    },
    # C++11 features
    'cpp11': {
        'lambda_expressions', 'auto_type', 'nullptr', 'rvalue_references',
        'move_semantics', 'smart_pointers', 'variadic_templates',
        'static_assert', 'range_based_for', 'class_enum', 'final_override',
        'decltype', 'constexpr', 'initializer_lists', 'delegating_constructors',
        'explicit_conversion', 'default_delete', 'type_traits',
    },
    # C++14 features
    'cpp14': {
        'generic_lambdas', 'lambda_capture_init', 'return_type_deduction',
        'constexpr_extension', 'variable_templates', 'binary_literals',
        'digit_separators',
    },
    # C++17 features
    'cpp17': {
        'structured_bindings', 'if_constexpr', 'inline_variables',
        'fold_expressions', 'class_template_argument_deduction',
        'auto_deduction_from_braced_init', 'nested_namespaces',
        'selection_statements_with_initializer', 'constexpr_if',
        'invoke', 'filesystem', 'parallel_algorithms',
    },
    # C++20 features
    'cpp20': {
        'concepts', 'ranges', 'coroutines', 'three_way_comparison',
        'designated_initializers', 'constexpr_virtual', 'modules',
        'feature_test_macros', 'consteval', 'constinit',
        'aggregate_initialization', 'nontype_template_parameters',
    },
}

class ClangParser:
    """Parser for C++ code using libclang"""
    
    def __init__(self, compilation_database_dir: str = None, db: Optional[EntityDatabase] = None, 
                 config: Optional[Config] = None, plugin_dirs: List[str] = None, 
                 disable_plugins: bool = False, use_tree_sitter_fallback: bool = True):
        if not LIBCLANG_CONFIGURED:
            raise ImportError("libclang is not properly configured. Parser functionality is unavailable.")
        self.config = config or Config()
        self.index = clang.cindex.Index.create()
        self.entities: Dict[str, List[Entity]] = {}
        self.db = db

        # TODO: consider adding PARSE_INCOMPLETE dynamically for headers...
        self.tu_options = (
            clang.cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD |
            clang.cindex.TranslationUnit.PARSE_INCLUDE_BRIEF_COMMENTS_IN_CODE_COMPLETION
        )
        
        self.use_tree_sitter_fallback = use_tree_sitter_fallback and TREE_SITTER_IMPORT_SUCCESS
        self.tree_sitter_subparser = None
        if self.use_tree_sitter_fallback:
            try:
                if is_tree_sitter_available():
                    self.tree_sitter_subparser = TreeSitterSubparser()
                    logger.info("Tree-sitter fallback parser initialized")
                else:
                    logger.warning("Tree-sitter is not available. Fallback parsing is disabled.")
                    self.use_tree_sitter_fallback = False
            except Exception as e:
                logger.warning(f"Could not initialize Tree-sitter fallback parser: {e}")
                self.use_tree_sitter_fallback = False
        
        # Initialize plugin system if not disabled
        self.disable_plugins = disable_plugins
        if not disable_plugins:
            if plugin_dirs is None and self.config:
                plugin_dirs = self.config.get("parser.plugin_dirs", [])
            plugin_config = None
            if self.config:
                plugin_config = self.config.get("parser.plugins", {})
            self.plugin_manager = PluginManager(plugin_dirs, plugin_config)
            self.plugin_manager.discover_plugins()
            plugin_count = len(self.plugin_manager.detectors)
            if plugin_count > 0:
                logger.info(f"Loaded {plugin_count} DSL feature detectors from plugins")
                if self.plugin_manager.disabled_plugins:
                    logger.info(f"Disabled plugins: {', '.join(self.plugin_manager.disabled_plugins)}")
                if self.plugin_manager.only_plugins:
                    logger.info(f"Only using whitelisted plugins: {', '.join(self.plugin_manager.only_plugins)}")
            
        if compilation_database_dir:
            try:
                self.compilation_database = clang.cindex.CompilationDatabase.fromDirectory(compilation_database_dir)
            except Exception as e:
                raise ValueError(f"Error loading compilation database: {e}")
        
        entities_to_skip = self.config.get("parser.entities_to_skip", [])
        self.entity_skip_patterns = [re.compile(pattern) for pattern in entities_to_skip]
        if self.entity_skip_patterns:
            logger.info(f"Loaded {len(self.entity_skip_patterns)} entity skip patterns: {entities_to_skip}")

    def get_compile_commands(self, filepath: str) -> List[str]:
        """Get compilation arguments for a file from the compilation database
        
        If the compilation database uses the 'arguments' field (rather than 'command'),
        it will scan the arguments for include paths and other file paths, making any
        relative paths absolute based on the 'directory' field in the database entry.

        Why? because that's the current format of Bear's compile_commands.json files.
        """
        try:
            if hasattr(self, 'compilation_database'):
                commands = self.compilation_database.getCompileCommands(filepath)
                if commands:
                    all_args = []
                    for command in commands:
                        try:
                            command_dir = command.directory if hasattr(command, 'directory') else None
                            if hasattr(command, 'arguments') and isinstance(command.arguments, list):
                                args = command.arguments[1:] if len(command.arguments) > 1 else []
                                if command_dir:
                                    args = [_normalize_path_in_argument(arg, command_dir) for arg in args]
                                all_args.extend(args)
                            elif hasattr(command, 'arguments'):
                                args = list(command.arguments)
                                if args and len(args) > 1:
                                    args = args[1:]
                                    if command_dir:
                                        args = [_normalize_path_in_argument(arg, command_dir) for arg in args]
                                    all_args.extend(args)
                        except (IndexError, TypeError) as e:
                            logger.debug(f"Could not extract arguments from command: {e}")
                    if all_args:
                        # add include paths from config, eg. to point to clang sys-includes
                        # also, remove the source file from the arguments, will be replaced 
                        # by its absolute path
                        include_paths = self.config.get('parser.include_paths', [])
                        if include_paths:
                            last_include_index = -1
                            for i, arg in enumerate(all_args):
                                if arg.startswith('-I'):
                                    last_include_index = i
                            additional_args = []
                            for include_path in include_paths:
                                include_arg = f"-I{include_path}"
                                if include_arg not in all_args:
                                    additional_args.append(include_arg)
                                    logger.debug(f"Adding include path from config: {include_arg}")
                            
                            if additional_args:
                                if last_include_index >= 0:
                                    all_args[last_include_index+1:last_include_index+1] = additional_args
                                    logger.debug(f"Inserted {len(additional_args)} include paths after existing include at position {last_include_index}")
                                else:
                                    all_args = additional_args + all_args
                                    logger.debug(f"Inserted {len(additional_args)} include paths at beginning of arguments")
                        filename = os.path.basename(filepath)
                        filepath_abs = os.path.abspath(filepath)
                        filtered_args = []
                        skip_next = False
                        for i, arg in enumerate(all_args):
                            if skip_next:
                                skip_next = False
                                continue
                            if arg == filename or arg == filepath or arg == filepath_abs:
                                logger.debug(f"Removed filename '{arg}' from arguments")
                                continue
                            if i < len(all_args) - 1 and arg in ('-c', '-o', '-MF', '-MT', '-MQ'):
                                next_arg = all_args[i+1]
                                if next_arg == filename or next_arg == filepath or next_arg == filepath_abs:
                                    filtered_args.append(arg)  # Keep the flag
                                    skip_next = True          # Skip the filename
                                    logger.debug(f"Removed filename '{next_arg}' after flag '{arg}'")
                                    continue
                                    
                            filtered_args.append(arg)
                        if filtered_args and filtered_args[-1] == "--":
                            filtered_args = filtered_args[:-1]
                            logger.debug("Removed trailing '--' from compilation arguments")
                            
                        logger.debug(f"Using compilation arguments from database: {filtered_args[:5]}...")
                        return filtered_args
        except Exception as e:
            logger.warning(f"Error getting compilation commands for {filepath}: {e}")
        
        filename = os.path.basename(filepath)
        extension = os.path.splitext(filepath)[1].lower()
        
        # Get C++ standard version from config
        std_version = self.config.get('parser.cpp_standard', 'c++20')
        include_paths = self.config.get('parser.include_paths', [])
        compile_flags = self.config.get('parser.compile_flags', [])
        
        # Build compilation arguments
        cpp_args = [
            '--driver-mode=g++',  # TODO: Maybe offer this as an option?
            f'-std={std_version}', 
            f'-I{os.path.dirname(filepath)}',
            '-c'
        ]
        
        # Add optional arguments
        for include_path in include_paths:
            cpp_args.append(f'-I{include_path}')
        cpp_args.extend(compile_flags)
        
        # Force c++ mode for popular extensions
        if extension in CPP_FILE_EXTENSIONS:
            cpp_args.extend(['-x', 'c++'])
        
        return cpp_args

    def extract_doc_comment(self, cursor: clang.cindex.Cursor) -> str:
        """Extract documentation comment for a cursor
        
        This extracts both doxygen-style (/** ... */) and simple C++ comments (// ...)
        that appear immediately before the declaration. If multiple comment blocks exist,
        they are combined.
        
        Args:
            cursor: The cursor to extract comments from
            
        Returns:
            Extracted and cleaned comment string
        """
        raw_comment = cursor.raw_comment
        if not raw_comment and cursor.location.file:
            try:
                file_path = cursor.location.file.name
                line_num = cursor.location.line
                if line_num > 1:  # Need at least one line above for a comment
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                        source_lines = f.readlines()
                    comment_lines = []
                    current_line = line_num - 2
                    
                    while current_line >= 0:
                        line = source_lines[current_line].strip()
                        if not line or not (line.startswith('//') or line.startswith('/*') or line.startswith('*')):
                            break
                        comment_lines.insert(0, line)
                        current_line -= 1
                    if comment_lines:
                        raw_comment = '\n'.join(comment_lines)
                        logger.debug(f"Manually extracted comment for {cursor.spelling} at {file_path}:{line_num}")
            except Exception as e:
                logger.debug(f"Error manually extracting comment: {e}")
        
        if not raw_comment:
            return ""
        lines = raw_comment.split('\n')
        processed_lines = []
        
        for line in lines:
            line = line.strip()
            if line.startswith('/**'):
                line = line[3:]
            elif line.startswith('/*'):
                line = line[2:]
            elif line.startswith('*/'):
                line = line[2:]
            elif line.startswith('*'):
                line = line[1:]
            elif line.startswith('///'):
                continue
            elif line.startswith('//'):
                line = line[2:]
            processed_lines.append(line.strip())
            
        result = '\n'.join(processed_lines).strip()
        logger.debug(f"Extracted comment: {result[:50]}{'...' if len(result) > 50 else ''}")
        return result
    
    def detect_cpp_features(self, cursor: clang.cindex.Cursor, entity=None) -> Set[str]:
        """Detect C++ language features used by this cursor and its children
        
        Args:
            cursor: libclang cursor for the entity
            entity: Optional Entity object to populate with custom fields
            
        Returns:
            Set of detected feature names
        """
        # Get token information once for efficiency
        all_token_spellings = [t.spelling for t in cursor.get_tokens()]
        all_token_text = ' '.join(all_token_spellings)
        available_cursor_kinds = dir(CursorKind)
        
        # Detect standard C++ features
        registry = FeatureDetectorRegistry()
        registry.register_all_detectors()
        features = registry.detect_features(cursor, all_token_spellings, all_token_text, available_cursor_kinds)
        
        # Set is_deprecated flag if we see the C++14 [[deprecated]] attribute
        if entity and 'deprecated_attribute' in features:
            entity.is_deprecated = True
            for detector in registry.detectors.values():
                if isinstance(detector, DeprecatedAttributeDetector) and hasattr(detector, 'deprecation_message'):
                    deprecation_message = detector.deprecation_message
                    if deprecation_message:
                        if not entity.parsed_doc:
                            entity.parsed_doc = {}
                        entity.parsed_doc['deprecated'] = deprecation_message
                        logger.debug(f"Captured deprecation message: {deprecation_message}")
                    break
            logger.debug(f"Setting is_deprecated=True for entity {entity.name} due to [[deprecated]] attribute")
        
        # Detect DSL features from plugins if enabled
        if not self.disable_plugins and hasattr(self, 'plugin_manager'):
            global CURRENT_PARSER
            CURRENT_PARSER = self
            
            dsl_result = self.plugin_manager.detect_features(
                cursor, all_token_spellings, all_token_text, available_cursor_kinds
            )
            
            # Add DSL features to the set
            if dsl_result['features']:
                features.update(dsl_result['features'])
                logger.debug(f"Detected DSL features: {', '.join(dsl_result['features'])}")
            
            # Add custom fields to the entity if provided
            if entity and dsl_result['custom_fields']:
                entity.custom_fields.update(dsl_result['custom_fields'])
        
        return features

    def _create_placeholder_entity(self, cursor: clang.cindex.Cursor, parent: Optional[Entity] = None) -> Optional[Entity]:
        """Create a placeholder entity for external references (e.g., standard library)
        
        This creates a minimal entity with just enough information to serve as a reference.
        It doesn't recursively process the entity's children or extract detailed information.
        Users choose which entities are treated this way, mainly for performance reasons.
        """
        if not cursor.location.file:
            return None
            
        file_path = os.path.realpath(cursor.location.file.name)
        location = (file_path, cursor.location.line, cursor.location.column, 
                  cursor.location.line, cursor.location.column)
        entity = Entity(cursor.spelling, cursor.kind, location, "", parent)
        entity.access = cursor.access_specifier
        if cursor.type and cursor.type.spelling:
            entity.type_info = cursor.type.spelling
        entity.is_external_reference = True
        return entity
        
    def _create_entity(self, cursor: clang.cindex.Cursor, parent: Optional[Entity] = None) -> Optional[Entity]:
        """Create an Entity from a cursor with enhanced features"""
        if not cursor.location.file:
            return None
        start = cursor.extent.start
        end = cursor.extent.end
        if not start.file:
            file_path = cursor.location.file.name
            try:
                file_path = os.path.realpath(file_path)
            except:
                pass
            location = (file_path, cursor.location.line, cursor.location.column, 
                      cursor.location.line, cursor.location.column)  # Use start as end position as fallback
        else:
            file_path = start.file.name
            try:
                file_path = os.path.realpath(file_path)
            except:
                pass
            location = (file_path, start.line, start.column, end.line, end.column)
        doc_comment = self.extract_doc_comment(cursor)
        entity = Entity(cursor.spelling, cursor.kind, location, doc_comment, parent)
        
        # Calculate and set namespace
        entity.namespace = self._get_namespace_path(cursor)
        
        entity.access = cursor.access_specifier
        entity.linkage = cursor.linkage
        if cursor.type and cursor.type.spelling:
            entity.type_info = cursor.type.spelling
            
        if cursor.kind in [
            clang.cindex.CursorKind.FUNCTION_DECL,
            clang.cindex.CursorKind.FUNCTION_TEMPLATE,
            clang.cindex.CursorKind.CXX_METHOD,
            clang.cindex.CursorKind.CONSTRUCTOR,
            clang.cindex.CursorKind.DESTRUCTOR,
            clang.cindex.CursorKind.CONCEPT_DECL,
            clang.cindex.CursorKind.CLASS_DECL,
            clang.cindex.CursorKind.STRUCT_DECL,
            clang.cindex.CursorKind.CLASS_TEMPLATE
        ]:
            tokens = list(cursor.get_tokens())
            if tokens:
                start_offset = cursor.extent.start.offset
                end_offset = cursor.extent.end.offset
                try:
                    with open(cursor.location.file.name, 'r') as f:
                        content = f.read()
                        if start_offset < len(content) and end_offset <= len(content):
                            full_decl = content[start_offset:end_offset]
                            body_start = full_decl.find('{')
                            if body_start > 0:
                                full_decl = full_decl[:body_start].strip()
                            full_decl = full_decl.rstrip(';').strip()
                            entity.full_signature = full_decl
                            logger.debug(f"Extracted full signature: {full_decl}")
                except Exception as e:
                    logger.debug(f"Error extracting full signature: {e}")
                    try:
                        full_text = ' '.join(t.spelling for t in tokens)
                        body_start = full_text.find('{')
                        if body_start > 0:
                            full_text = full_text[:body_start].strip()
                        full_text = full_text.rstrip(';').strip()
                        entity.full_signature = full_text
                    except Exception as e2:
                        logger.debug(f"Fallback signature extraction failed: {e2}")
                        
        entity.cpp_features = self.detect_cpp_features(cursor, entity)
        self._process_method_classification(entity, cursor)
        self._process_class_features(entity, cursor)
        self._detect_deprecation(entity, cursor)
        
        return entity
        
    def _process_method_classification(self, entity: Entity, cursor: clang.cindex.Cursor) -> None:
        """Process C++ method classifications (virtual, override, etc.)"""
        if cursor.kind not in [clang.cindex.CursorKind.CXX_METHOD,
                               clang.cindex.CursorKind.CONSTRUCTOR,
                               clang.cindex.CursorKind.DESTRUCTOR,
                               clang.cindex.CursorKind.FUNCTION_DECL]:  
            return
            
        if cursor.kind == clang.cindex.CursorKind.CXX_METHOD:
            parent_cursor = cursor.semantic_parent
            if parent_cursor and parent_cursor.kind in [clang.cindex.CursorKind.CLASS_DECL,
                                                        clang.cindex.CursorKind.STRUCT_DECL, 
                                                        clang.cindex.CursorKind.CLASS_TEMPLATE]:
                parent_name = parent_cursor.spelling
                method_name = cursor.spelling
                if method_name == parent_name:
                    entity.kind = clang.cindex.CursorKind.CONSTRUCTOR
                    logger.debug(f"Identified method '{method_name}' as a constructor of class '{parent_name}'")
                elif method_name == f"~{parent_name}":
                    entity.kind = clang.cindex.CursorKind.DESTRUCTOR
                    logger.debug(f"Identified method '{method_name}' as a destructor of class '{parent_name}'")
        
        if cursor.kind in [clang.cindex.CursorKind.CXX_METHOD, 
                          clang.cindex.CursorKind.CONSTRUCTOR,
                          clang.cindex.CursorKind.DESTRUCTOR]:
            entity.is_virtual = cursor.is_virtual_method()
            entity.is_pure_virtual = cursor.is_pure_virtual_method()
            try:
                entity.is_override = cursor.is_override_method()
            except AttributeError:
                tokens = list(cursor.get_tokens())
                entity.is_override = any(t.spelling == 'override' for t in tokens)
            try:
                entity.is_final = cursor.is_final_method()
            except AttributeError:
                tokens = list(cursor.get_tokens())
                entity.is_final = any(t.spelling == 'final' for t in tokens)
        
        try:
            entity.is_static = cursor.storage_class == clang.cindex.StorageClass.STATIC
        except AttributeError:
            tokens = list(cursor.get_tokens())
            token_spellings = [t.spelling for t in tokens]
            entity.is_static = 'static' in token_spellings
            
        entity.is_defaulted = cursor.is_default_method()
        entity.is_deleted = cursor.is_deleted_method()
        
    def _get_namespace_path(self, cursor: clang.cindex.Cursor) -> Optional[str]:
        """Extract namespace path from a cursor by traversing its semantic parents
        
        Args:
            cursor: Clang cursor to extract namespace from
            
        Returns:
            Namespace string in format 'ns1::ns2::ns3' or None if no namespace
        """
        if not cursor:
            return None
            
        namespaces = []
        parent = cursor.semantic_parent
        
        # Traverse up the semantic parent chain to collect namespaces
        while parent and parent.kind != clang.cindex.CursorKind.TRANSLATION_UNIT:
            if parent.kind == clang.cindex.CursorKind.NAMESPACE:
                # Only add non-empty namespace names (skip anonymous namespaces)
                if parent.spelling:
                    namespaces.insert(0, parent.spelling)
            parent = parent.semantic_parent
            
        # Return None for global namespace, otherwise join with ::
        if not namespaces:
            return None
        return '::'.join(namespaces)
    
    def _detect_deprecation(self, entity: Entity, cursor: clang.cindex.Cursor) -> None:
        """Detect and process deprecation information from both attributes and doc comments
        
        This method specifically looks for [[deprecated]] attributes and combines that information
        with any documentation-based deprecation. It works for all entity types.
        """
        self._check_deprecation_from_diagnostics(entity, cursor)
        if not entity.is_deprecated:
            self._check_deprecation_from_tokens(entity, cursor)
            if not entity.is_deprecated:
                self._check_deprecation_from_source(entity, cursor)
        if entity.is_deprecated and not entity.parsed_doc.get('deprecated'):
            if not entity.parsed_doc:
                entity.parsed_doc = {}
            entity_type = entity.kind.name.lower().replace('_', ' ')
            entity.parsed_doc['deprecated'] = f"This {entity_type} is marked as deprecated"
            
    def _check_deprecation_from_diagnostics(self, entity: Entity, cursor: clang.cindex.Cursor) -> None:
        """Check for deprecation warnings in Clang's diagnostics"""
        if not hasattr(cursor, 'translation_unit') or not cursor.translation_unit or not cursor.location.file:
            return
            
        for diagnostic in cursor.translation_unit.diagnostics:
            if (diagnostic.location.file and 
                diagnostic.location.file.name == cursor.location.file.name and
                diagnostic.location.line == cursor.location.line):
                warning_text = diagnostic.spelling.lower()
                if 'deprecated' in warning_text and (entity.name.lower() in warning_text or cursor.spelling.lower() in warning_text):
                    entity.is_deprecated = True
                    logger.debug(f"Found deprecation diagnostic for {entity.name}: {diagnostic.spelling}")
                    import re
                    message_match = re.search(r"deprecated:\s*(.*?)(?:\s*\[-W|$)", diagnostic.spelling)
                    if message_match:
                        message = message_match.group(1).strip()
                        if not entity.parsed_doc:
                            entity.parsed_doc = {}
                        entity.parsed_doc['deprecated'] = message
                        logger.debug(f"Extracted deprecation message: {message}")
                    break
                    
    def _check_deprecation_from_tokens(self, entity: Entity, cursor: clang.cindex.Cursor) -> None:
        """Check for [[deprecated]] attributes by analyzing tokens"""
        try:
            tokens = list(cursor.get_tokens())
            if not tokens:
                return
            token_spellings = [t.spelling for t in tokens]
            token_str = ' '.join(token_spellings)
            if '[[' in token_str and ']]' in token_str and 'deprecated' in token_str:
                entity.is_deprecated = True
                logger.debug(f"Found deprecation attribute in tokens for {entity.name}")
                import re
                message_match = re.search(r'\[\[deprecated\(\s*"([^"]*)"\s*\)\]\]', token_str)
                if message_match:
                    if not entity.parsed_doc:
                        entity.parsed_doc = {}
                    entity.parsed_doc['deprecated'] = message_match.group(1)
                    logger.debug(f"Extracted message from tokens: {message_match.group(1)}")
        except Exception as e:
            logger.debug(f"Error in token-based deprecation detection: {e}")
            
    def _check_deprecation_from_source(self, entity: Entity, cursor: clang.cindex.Cursor) -> None:
        """Check for [[deprecated]] attributes by directly analyzing source code"""
        try:
            if not cursor.location.file or not cursor.extent.start or not cursor.extent.end:
                return
            with open(cursor.location.file.name, 'r') as f:
                source_lines = f.readlines()
            line_idx = cursor.location.line - 1  # 0-indexed
            if line_idx > 0:
                preceding_line = source_lines[line_idx - 1].strip()
                if '[[deprecated' in preceding_line:
                    entity.is_deprecated = True
                    logger.debug(f"Found deprecation attribute in source for {entity.name}")
                    import re
                    message_match = re.search(r'\[\[deprecated\(\s*"([^"]*)"\s*\)\]\]', preceding_line)
                    if message_match:
                        if not entity.parsed_doc:
                            entity.parsed_doc = {}
                        entity.parsed_doc['deprecated'] = message_match.group(1)
                        logger.debug(f"Extracted message from source: {message_match.group(1)}")
        except Exception as e:
            logger.debug(f"Error in source-based deprecation detection: {e}")
        if entity.is_deprecated and not entity.parsed_doc.get('deprecated'):
            if not entity.parsed_doc:
                entity.parsed_doc = {}
            entity_type = entity.kind.name.lower().replace('_', ' ')
            entity.parsed_doc['deprecated'] = f"This {entity_type} is deprecated"
    
    def _should_skip_entity(self, entity: Union[Entity, Dict[str, Any]]) -> bool:
        """Check if an entity should be skipped based on configured patterns
        
        Args:
            entity: The entity to check (either Entity object or dictionary)
            
        Returns:
            True if the entity should be skipped, False otherwise
        """
        if not self.entity_skip_patterns:
            return False
            
        entity_name = entity.name if isinstance(entity, Entity) else entity.get("name", "")
        if not entity_name:
            return False
            
        for pattern in self.entity_skip_patterns:
            # Use search() instead of match() to find the pattern anywhere in the string
            # match() only checks at the beginning of the string
            if pattern.match(entity_name):
                logger.debug(f"Skipping entity '{entity_name}' as it matches skip pattern '{pattern.pattern}'")
                return True
                
        return False
    
    def _process_class_features(self, entity: Entity, cursor: clang.cindex.Cursor) -> None:
        """Process class-specific features (inheritance, abstract classification)"""
        if cursor.kind not in (clang.cindex.CursorKind.CLASS_DECL, 
                             clang.cindex.CursorKind.STRUCT_DECL, 
                             clang.cindex.CursorKind.CLASS_TEMPLATE):
            return
            
        has_pure_virtual_method = False
        is_final_class = False
        
        for child in cursor.get_children():
            if child.kind == clang.cindex.CursorKind.CXX_BASE_SPECIFIER:
                base_class = self._process_base_class(child)
                if base_class:
                    entity.add_base_class(base_class)
            elif child.kind == clang.cindex.CursorKind.CXX_METHOD and child.is_pure_virtual_method():
                has_pure_virtual_method = True
        try:
            is_final_class = cursor.is_final()
        except AttributeError:
            tokens = list(cursor.get_tokens())
            token_spellings = [t.spelling for t in tokens]
            if 'final' in token_spellings:
                name_idx = token_spellings.index(cursor.spelling) if cursor.spelling in token_spellings else -1
                if name_idx >= 0 and name_idx + 1 < len(token_spellings) and token_spellings[name_idx + 1] == 'final':
                    is_final_class = True
        entity.is_abstract = has_pure_virtual_method
        entity.is_final = is_final_class
    
    def _process_base_class(self, cursor: clang.cindex.Cursor) -> Dict[str, Any]:
        """Process a base class specifier"""
        base_class_info = {
            'name': cursor.type.spelling,
            'access': cursor.access_specifier.name if cursor.access_specifier else 'PUBLIC',
            'virtual': False  # Default
        }
        
        tokens = list(cursor.get_tokens())
        token_spellings = [t.spelling for t in tokens]
        if 'virtual' in token_spellings:
            base_class_info['virtual'] = True
        base_class_name = base_class_info['name']
        template_pos = base_class_name.find('<')
        if template_pos > 0:
            base_class_name = base_class_name[:template_pos]
            
        # Strip any namespace prefixes for more flexible matching
        simple_name = base_class_name
        namespace_pos = simple_name.rfind('::')
        if namespace_pos > 0:
            simple_name = simple_name[namespace_pos + 2:]
        
        found = False
        for _, entities in self.entities.items():
            for entity in entities:
                if entity.name == base_class_name:
                    base_class_info['uuid'] = entity.uuid
                    logger.debug(f"Found base class {base_class_name} with UUID {entity.uuid}")
                    found = True
                    break
                elif entity.name == simple_name:
                    base_class_info['uuid'] = entity.uuid
                    logger.debug(f"Found base class {simple_name} with UUID {entity.uuid} (matched without namespace)")
                    found = True
                    break
            if found:
                break
                
        if not found and not base_class_info.get('uuid') and self.db:
            try:
                self.db.cursor.execute(
                    "SELECT uuid FROM entities WHERE name = ? AND kind IN ('CLASS_DECL', 'CLASS_TEMPLATE', 'STRUCT_DECL')", 
                    (simple_name,)
                )
                result = self.db.cursor.fetchone()
                if result:
                    base_class_info['uuid'] = result[0]
                    logger.debug(f"Found base class {simple_name} with UUID {result[0]} in database")
                    found = True
            except Exception as e:
                logger.warning(f"Error looking up base class in database: {e}")
                
        return base_class_info
        
    def parse_file(self, filepath: str, force_tree_sitter: bool = False) -> List[Entity]:
        """Parse a C++ file and return its entities
        
        Args:
            filepath: Path to the file to parse
            force_tree_sitter: If True, always use the Tree-sitter parser instead of Clang
        
        Returns:
            List of entity objects extracted from the file
        """
        compile_args = self.get_compile_commands(filepath)
        if self.db:
            file_stats = os.stat(filepath)
            last_modified = int(file_stats.st_mtime)
            with open(filepath, 'rb') as f:
                file_content = f.read()
                file_hash = hashlib.md5(file_content).hexdigest()
            if not self.db.file_changed(filepath, last_modified, file_hash):
                cached_entities = self.db.get_entities_by_file(filepath)
                if cached_entities:
                    logger.info(f"Using cached entities for {filepath} (unchanged)")
                    self.entities[filepath] = cached_entities
                    return cached_entities
            self.db.clear_file_entities(filepath)
            self.db.track_file(filepath, last_modified, file_hash)
        
        extension = os.path.splitext(filepath)[1].lower()
        if extension in CPP_FILE_EXTENSIONS and '-x' not in compile_args:
            compile_args.extend(['-x', 'c++'])
        
        # Remove the filepath from compile_args if it's present
        # This avoids having the same file specified twice (once in filepath param, once in args)
        clean_args = []
        for arg in compile_args:
            if arg != filepath and not arg.endswith(filepath):
                clean_args.append(arg)
                
        logger.info(f"Parsing {filepath} with args: {clean_args}")
        
        use_fallback = force_tree_sitter
        libclang_error = None
        if not force_tree_sitter:
            try:
                logger.debug(f"parsing translation unit {filepath} with index.parse")
                translation_unit = self.index.parse(filepath, clean_args, options=self.tu_options)
            except Exception as e:
                import traceback
                libclang_error = e
                logger.error(f"Exception while parsing {filepath}: {e}\nTraceback: {traceback.format_exc()}")
                use_fallback = True
            
        if use_fallback and self.use_tree_sitter_fallback and self.tree_sitter_subparser:
            logger.info(f"Heavy-duty macro code? But that is OK, trying a fail-tolerant alternative...")
            logger.info(f"Trying Tree-sitter fallback for {filepath} after libclang error: {libclang_error}")
            try:
                tree_sitter_result = self.tree_sitter_subparser.parse_file(filepath)
                file_entities = self._convert_tree_sitter_result(tree_sitter_result, filepath)
                if file_entities:
                    logger.info(f"Successfully parsed {len(file_entities)} entities with Tree-sitter fallback")
                    self.entities[filepath] = file_entities
                    if self.db:
                        for entity in file_entities:
                            if not self._should_skip_entity(entity):
                                self.db.store_entity(entity.to_dict())
                            else:
                                logger.debug(f"Skipped storing entity {entity.name} to database (matches skip pattern)")
                    return file_entities
                else:
                    logger.warning(f"No entities extracted with Tree-sitter fallback")
            except Exception as fallback_e:
                logger.error(f"Tree-sitter fallback also failed for {filepath}: {fallback_e}")
            return []
            
        if use_fallback:
            return []
        try:
            if translation_unit is None:
                import traceback
                logger.error(f"Error parsing {filepath}: Translation unit is None\nTraceback: {traceback.format_exc()}")
                return []
                
            if len(translation_unit.diagnostics) > 0:
                error_count = 0
                warning_count = 0
                note_count = 0
                logger.debug(f"Found {len(translation_unit.diagnostics)} diagnostics while parsing {filepath}")
                for diag in translation_unit.diagnostics:
                    location = ""
                    if diag.location.file:
                        location = f"{diag.location.file.name}:{diag.location.line}:{diag.location.column}"
                    else:
                        location = "<unknown>"
                    if diag.severity >= 3:  # Error or fatal
                        error_count += 1
                        logger.error(f"[ERROR] {location}: {diag.spelling}")
                        for i, fix in enumerate(diag.fixits):
                            logger.error(f"  Fix {i+1}: Replace '{fix.range.start.file.name}:{fix.range.start.line}:{fix.range.start.column}-{fix.range.end.line}:{fix.range.end.column}' with '{fix.value}'")
                    elif diag.severity == 2:  # Warning
                        warning_count += 1
                        logger.warning(f"[WARNING] {location}: {diag.spelling}")
                    else:  # Note or remark
                        note_count += 1
                        logger.debug(f"[NOTE] {location}: {diag.spelling}")
                if error_count > 0:
                    logger.error(f"Parsing diagnostics for {filepath}: {error_count} errors, {warning_count} warnings, {note_count} notes")
                    if error_count > 0:
                        logger.error(f"Error parsing {filepath}: Failed to parse translation unit due to compilation errors.")
                        return []
                elif warning_count > 0:
                    logger.warning(f"Parsing diagnostics for {filepath}: {warning_count} warnings, {note_count} notes")
            
            cursor = translation_unit.cursor
            file_entities = []
            self._process_cursor(cursor, file_entities)
            self.entities[filepath] = file_entities
            
            if self.db:
                # First store all entities
                for entity in file_entities:
                    if not self._should_skip_entity(entity):
                        self.db.store_entity(entity.to_dict())
                    else:
                        logger.debug(f"Skipped storing entity {entity.name} to database (matches skip pattern)")
                
                # Then find and link declarations and definitions
                self._find_and_link_declarations_definitions(cursor, filepath)
        except Exception as e:
            import traceback
            logger.error(f"Error processing file {filepath}: {e}\nTraceback: {traceback.format_exc()}")
            return []
        
        logger.info(f"Successfully parsed {len(file_entities)} top-level entities")
        return file_entities
        
    def _find_and_link_declarations_definitions(self, cursor: clang.cindex.Cursor, filepath: str):
        """Find declarations and their matching definitions and link them in the database
        
        This method identifies when a class or function is declared in one place and defined
        in another, creating explicit links in the database to allow proper documentation
        generation that shows all implementation files.
        
        Args:
            cursor: libclang cursor for the translation unit
            filepath: Path to the file being parsed
        """
        logger.debug(f"Finding and linking declarations and definitions in {filepath}")
        processed_usrs = {}
        def process_cursor_for_links(current_cursor):
            if not current_cursor.location.file:
                return
            if current_cursor.kind in [
                clang.cindex.CursorKind.FUNCTION_DECL,
                clang.cindex.CursorKind.CXX_METHOD,
                clang.cindex.CursorKind.CONSTRUCTOR,
                clang.cindex.CursorKind.DESTRUCTOR,
                clang.cindex.CursorKind.FUNCTION_TEMPLATE,
                clang.cindex.CursorKind.CLASS_DECL,
                clang.cindex.CursorKind.STRUCT_DECL,
                clang.cindex.CursorKind.CLASS_TEMPLATE
            ]:
                try:
                    usr = current_cursor.get_usr()
                    if not usr or usr in processed_usrs:
                        return
                    processed_usrs[usr] = True
                except Exception as e:
                    logger.debug(f"Error getting USR: {e}")
                    return
                try:
                    definition = current_cursor.get_definition()
                    if not definition or definition == current_cursor:
                        return
                    if not current_cursor.location.file or not definition.location.file:
                        return
                    decl_file = os.path.realpath(current_cursor.location.file.name)
                    def_file = os.path.realpath(definition.location.file.name)
                    if decl_file == def_file:
                        return
                    
                    logger.debug(f"Found declaration-definition pair: {current_cursor.spelling} in {decl_file} -> {def_file}")
                    
                    decl_start = current_cursor.extent.start
                    decl_end = current_cursor.extent.end
                    decl_location = (decl_file, decl_start.line, decl_start.column, decl_end.line, decl_end.column)
                    def_start = definition.extent.start
                    def_end = definition.extent.end
                    def_location = (def_file, def_start.line, def_start.column, def_end.line, def_end.column)
                    query = f"""
                    SELECT uuid FROM entities 
                    WHERE name = ? AND kind = ? AND file = ? AND line = ?
                    """
                    
                    # Find declaration entity
                    self.db.cursor.execute(query, (
                        current_cursor.spelling, 
                        str(current_cursor.kind), 
                        decl_file, 
                        decl_start.line
                    ))
                    decl_row = self.db.cursor.fetchone()
                    
                    # Find definition entity
                    self.db.cursor.execute(query, (
                        definition.spelling, 
                        str(definition.kind), 
                        def_file, 
                        def_start.line
                    ))
                    def_row = self.db.cursor.fetchone()
                    if decl_row and def_row:
                        decl_uuid = decl_row[0]
                        def_uuid = def_row[0]
                        logger.debug(f"Linking declaration {current_cursor.spelling} in {decl_file} to definition in {def_file}")
                        self.db.link_declaration_definition(decl_uuid, def_uuid)
                except Exception as e:
                    logger.debug(f"Error processing declaration-definition: {e}")
                    raise
            
            for child in current_cursor.get_children():
                process_cursor_for_links(child)

        process_cursor_for_links(cursor)
    
    def _process_cursor(self, cursor: clang.cindex.Cursor, entities: List[Entity], 
                    parent: Optional[Entity] = None):
        """Process a cursor and its children recursively"""
        if cursor.location.file:
            file_path = os.path.realpath(cursor.location.file.name)
            prefixes_to_skip = self.config.get('parser.prefixes_to_skip', [])
            
            if any(file_path.startswith(prefix) for prefix in prefixes_to_skip):
                # Instead of completely skipping external references,
                # create a placeholder entity without recursing into children
                if cursor.kind in [
                    CursorKind.NAMESPACE,
                    CursorKind.CLASS_DECL,
                    CursorKind.STRUCT_DECL,
                    CursorKind.CLASS_TEMPLATE,
                    CursorKind.FUNCTION_DECL,
                    CursorKind.FUNCTION_TEMPLATE,
                    CursorKind.ENUM_DECL
                ]:
                    entity = self._create_placeholder_entity(cursor, parent)
                    if entity:
                        if parent:
                            parent.add_child(entity)
                        else:
                            entities.append(entity)
                return

        # Define which cursors should become their own entities
        # these are the main things the documentation should focus on.
        # TODO: offer configuration options for this?
        interesting_kinds = [
            CursorKind.NAMESPACE,
            CursorKind.CLASS_DECL,
            CursorKind.STRUCT_DECL,
            CursorKind.ENUM_DECL,
            CursorKind.FUNCTION_DECL,
            CursorKind.CXX_METHOD,
            CursorKind.CONSTRUCTOR,
            CursorKind.DESTRUCTOR,
            CursorKind.FIELD_DECL,
            CursorKind.ENUM_CONSTANT_DECL,
            CursorKind.VAR_DECL,
            CursorKind.TYPEDEF_DECL,
            CursorKind.TEMPLATE_TYPE_PARAMETER,
            CursorKind.TEMPLATE_NON_TYPE_PARAMETER,
            CursorKind.FUNCTION_TEMPLATE,
            CursorKind.CLASS_TEMPLATE,
            CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION,
            CursorKind.CONCEPT_DECL,  # C++20 concepts
            CursorKind.STATIC_ASSERT  # static_assert
        ]
        
        # Entities that are more like properties of main ones
        # We don't want these as separate entities but we want to detect them as features
        special_detections = [
            CursorKind.LAMBDA_EXPR,          # lambda expressions
            CursorKind.CXX_CATCH_STMT,       # exceptions
            CursorKind.CXX_TRY_STMT,         # exceptions
            CursorKind.CXX_FOR_RANGE_STMT,   # range-based for
            CursorKind.CXX_METHOD,           # methods (operator overloading)
            CursorKind.INIT_LIST_EXPR,       # initializer lists
            CursorKind.IF_STMT,              # constexpr if, selection statements with initializer
            CursorKind.DECL_STMT,            # auto declarations, structured bindings
            CursorKind.CXX_NULL_PTR_LITERAL_EXPR  # nullptr
        ]
        
        # We want to propagate these features to parent entities
        detected_features = set()
        
        if cursor.kind == CursorKind.LAMBDA_EXPR:
            detected_features.add('lambda_expressions')  # C++11
            for child in cursor.get_children():
                if child.kind == CursorKind.PARM_DECL and child.type.spelling == 'auto':
                    detected_features.add('generic_lambdas')  # C++14
                    break
                        
        elif cursor.kind == CursorKind.VAR_DECL:
            if cursor.type and cursor.type.spelling and 'auto' in cursor.type.spelling.split():
                detected_features.add('auto_type')  # C++11
                
        elif cursor.kind == CursorKind.CXX_FOR_RANGE_STMT:
            detected_features.add('range_based_for')  # C++11
            
        elif cursor.kind in [CursorKind.CXX_CATCH_STMT, CursorKind.CXX_TRY_STMT]:
            detected_features.add('exceptions')  # C++98
            
        elif cursor.kind == CursorKind.CXX_NULL_PTR_LITERAL_EXPR:
            detected_features.add('nullptr')  # C++11
            
        elif (cursor.kind == CursorKind.DECL_REF_EXPR and cursor.type and 
              ('unique_ptr' in cursor.type.spelling or 'shared_ptr' in cursor.type.spelling)):
            detected_features.add('smart_pointers')  # C++11
            
        if detected_features and parent and hasattr(parent, 'cpp_features'):
            parent.cpp_features.update(detected_features)
        
        if cursor.kind in interesting_kinds:
            entity = self._create_entity(cursor, parent)
            if entity:
                should_skip = self._should_skip_entity(entity)
                if should_skip:
                    logger.debug(f"Skipping entity {entity.name} ({entity.kind}) during processing due to skip pattern")
                    return
                if parent:
                    parent.add_child(entity)
                else:
                    entities.append(entity)
                for child in cursor.get_children():
                    self._process_cursor(child, entities, entity)
        else:
            for child in cursor.get_children():
                self._process_cursor(child, entities, parent)

    def resolve_inheritance_relationships(self) -> None:
        """Resolve all inheritance relationships after all files have been parsed
        
        This method should be called after all files have been parsed to ensure
        all entities are available for resolving inheritance relationships.
        """
        if not self.db:
            logger.warning("Cannot resolve inheritance relationships without a database")
            return
        self.db.cursor.execute("""
        SELECT i.class_uuid, i.class_name, i.base_name FROM inheritance i 
        WHERE i.base_uuid IS NULL
        """)
        unresolved = self.db.cursor.fetchall()
        logger.debug(f"Found {len(unresolved)} unresolved inheritance relationships")
        resolved_count = 0
        for class_uuid, class_name, base_name in unresolved:
            self.db.cursor.execute("""
            SELECT uuid FROM entities 
            WHERE name = ? AND kind IN ('CLASS_DECL', 'CLASS_TEMPLATE', 'STRUCT_DECL', 'STRUCT_TEMPLATE')
            """, (base_name,))
            base_result = self.db.cursor.fetchone()
            
            if base_result:
                base_uuid = base_result[0]
                self.db.cursor.execute("""
                UPDATE inheritance 
                SET base_uuid = ? 
                WHERE class_uuid = ? AND base_name = ?
                """, (base_uuid, class_uuid, base_name))
                resolved_count += 1
                logger.debug(f"Resolved base class {base_name} with UUID {base_uuid} for {class_name}")
        
        logger.debug(f"Resolved {resolved_count} out of {len(unresolved)} inheritance relationships")
        self.db.commit()
        self.db._populate_base_child_links()
        
    def export_to_database(self, output_path: str) -> None:
        """Export parsed entities to SQLite database
        
        Args:
            output_path: Path to output SQLite database file
        """
        if self.db:
            if output_path != self.db.db_path:
                logger.info(f"Exporting entities to SQLite database {output_path}")
                new_db = EntityDatabase(output_path)
                self.db.copy_to(new_db)
                new_db.commit()
                new_db.close()
                logger.info(f"Exported entities to {output_path}")
        else:
            logger.info(f"Creating new SQLite database {output_path}")
            db = EntityDatabase(output_path)
            
            for filepath, entities in self.entities.items():
                for entity in entities:
                    self._export_entity(db, entity)
            db.commit()
            db.close()
            logger.info(f"Exported entities to {output_path}")
            
    def _convert_tree_sitter_result(self, tree_sitter_result: Dict[str, Any], filepath: str) -> List[Entity]:
        """Convert Tree-sitter parsing result to Entity objects
        
        This method converts the lightweight parsing results from Tree-sitter into
        Entity objects that can be used by the rest of the system. This is used when
        libclang parsing fails and we need to fall back to Tree-sitter.
        
        Args:
            tree_sitter_result: Result dictionary from Tree-sitter parser
            filepath: Path to the file that was parsed
            
        Returns:
            List of Entity objects representing the parsed entities
        """
        from .entity import Entity
        entities = []
        
        for class_info in tree_sitter_result.get("classes", []):
            try:
                class_entity = Entity(
                    name=class_info.get("name", "UnknownClass"),
                    kind="CLASS_DECL",
                    file=filepath,
                    line=class_info.get("start_line", 0) + 1,  # Tree-sitter uses 0-indexed lines
                    column=class_info.get("start_column", 0),
                    end_line=class_info.get("end_line", 0) + 1,
                    end_column=class_info.get("end_column", 0),
                    parent=None
                )
                class_entity.access_specifier = "public"
                entities.append(class_entity)
            except Exception as e:
                logger.warning(f"Error converting Tree-sitter class to Entity: {e}")
        for test_case in tree_sitter_result.get("test_cases", []):
            try:
                test_entity = Entity(
                    name=test_case.get("name", "UnknownTest"),
                    kind=clang.cindex.CursorKind.FUNCTION_DECL,
                    location=(filepath,
                              int(test_case.get("start_line", 0)) + 1,
                              int(test_case.get("start_column", 0)),
                              int(test_case.get("end_line", 0)) + 1,
                              int(test_case.get("end_column", 0))),
                    parent=None
                )
                test_entity.custom_fields["is_test_case"] = True
                if "description" in test_case:
                    test_entity.custom_fields["test_description"] = test_case["description"]
                if "tags" in test_case and test_case["tags"]:
                    test_entity.custom_fields["tags"] = test_case["tags"]
                    logger.debug(f"Added tags to test case: {test_case['tags']}")
                if "references" in test_case and test_case["references"]:
                    test_entity.custom_fields["tree_sitter_references"] = ";".join(test_case["references"])
                    logger.debug(f"Added {len(test_case['references'])} type references to test case: {test_case['references']}")
                entities.append(test_entity)
            except Exception as e:
                import traceback
                logger.warning(f"Error converting Tree-sitter test to Entity: {e}\nTraceback: {traceback.format_exc()}")
                
        logger.info(f"Converted {len(entities)} entities from Tree-sitter result")
        return entities
    
    def _export_entity(self, db, entity):
        """Helper method to recursively export an entity and its children to the database
        
        Args:
            db: EntityDatabase instance
            entity: Entity to export
        """
        entity_dict = entity.to_dict()
        if hasattr(entity, 'custom_fields') and entity.custom_fields:
            entity_dict['custom_fields'] = entity.custom_fields
        children = entity_dict.pop('children', [])
        db.store_entity(entity_dict)
        for child in entity.children:
            self._export_entity(db, child)

def _normalize_path_in_argument(arg, base_dir):
    """Normalize paths in compilation arguments to be absolute
    
    Args:
        arg: The argument string
        base_dir: Base directory to use for relative paths
        
    Returns:
        Normalized argument with absolute paths
    """
    include_prefixes = ('-I', '-isystem', '-include', '-iquote', '-isysroot')
    for prefix in include_prefixes:
        if arg.startswith(prefix) and len(arg) > len(prefix):
            path = arg[len(prefix):]
            if not os.path.isabs(path):
                normalized_path = os.path.normpath(os.path.join(base_dir, path))
                return f"{prefix}{normalized_path}"
    
    io_prefixes = ('-o', '-c', '-MF', '-MT', '-MQ', '@')
    for prefix in io_prefixes:
        if arg == prefix:
            return arg
        if arg.startswith(prefix) and len(arg) > len(prefix):
            path = arg[len(prefix):]
            if path and not os.path.isabs(path) and ('/' in path or '\\' in path):
                normalized_path = os.path.normpath(os.path.join(base_dir, path))
                return f"{prefix}{normalized_path}"
    if not arg.startswith('-'):
        file_extensions = tuple(CPP_FILE_EXTENSIONS)
        has_path_sep = '/' in arg or '\\' in arg
        is_possible_file = arg.endswith(file_extensions) or has_path_sep
        if is_possible_file and not os.path.isabs(arg):
            return os.path.normpath(os.path.join(base_dir, arg))
    return arg

def get_source_files_from_compilation_database(compilation_database):
    """Extract source files from compilation database
    
    Args:
        compilation_database: Either a string path to a directory containing compile_commands.json
                             or a clang.cindex.CompilationDatabase object
    
    Returns:
        List of absolute paths to all source files found in the compilation database.
    """
    import clang.cindex
    
    if isinstance(compilation_database, str):
        try:
            logger.debug(f"Creating CompilationDatabase from directory: {compilation_database}")
            compilation_database = clang.cindex.CompilationDatabase.fromDirectory(compilation_database)
        except Exception as e:
            import traceback
            logger.error(f"Error creating CompilationDatabase from {compilation_database}: {e}\nTraceback: {traceback.format_exc()}")
            return []
    
    if not hasattr(compilation_database, 'getAllCompileCommands'):
        import traceback
        logger.error(f"Invalid compilation database object: {compilation_database}\nTraceback: {traceback.format_exc()}")
        return []
    
    files = set()
    try:
        for cmd in compilation_database.getAllCompileCommands():
            src_file = cmd.filename
            if src_file.endswith(tuple(CPP_FILE_EXTENSIONS)):
                src_path = Path(src_file)
                if not src_path.is_absolute():
                    src_path = Path(cmd.directory) / src_path
                files.add(str(src_path))
        logger.debug(f"Found {len(files)} source files in compilation database")
    except Exception as e:
        import traceback
        logger.error(f"Error extracting files from compilation database: {e}\nTraceback: {traceback.format_exc()}")
    
    return list(files)

def main():
    # Extract any +key=value arguments before argparse sees them
    override_args = []
    cleaned_argv = []
    overrides = {}
    
    for arg in sys.argv[1:]:
        if arg.startswith('+') and '=' in arg:
            override_args.append(arg)
            key = arg[1:].split('=', 1)[0]
            value = arg.split('=', 1)[1]
            overrides[key] = value
        else:
            cleaned_argv.append(arg)
    
    original_argv = sys.argv.copy()
    sys.argv = [sys.argv[0]] + cleaned_argv
    version_parser = argparse.ArgumentParser(add_help=False)
    version_parser.add_argument('--version', action='store_true', help='Show version information and exit')
    
    # Parse only the version flag
    version_args, _ = version_parser.parse_known_args()
    
    if version_args.version:
        print(f"foamCD {get_version()}")
        return 0
    
    parser = argparse.ArgumentParser(description='Parse C++ files using libclang and extract documentation.',
                                   formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('--generate-config', '-g', type=str, 
                      help='Generate default configuration file at specified path.\n'
                           'Can be combined with overrides using +key=value syntax, for example:\n'
                           '  --generate-config config.yaml +database.path=/tmp/docs.db +markdown.project_name="My Project"')
    parser.add_argument('--config', '-c', type=str, help='Path to YAML configuration file')
    parser.add_argument('--compile-commands-dir', type=str, help='Path to directory containing compile_commands.json, overrides the YAML config')
    parser.add_argument('--output', '-o', type=str, help='Output SQLite database file, overrides the YAML config')
    parser.add_argument('--file', '-f', type=str, help='Path to specific file to parse, overrides compilation databases')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output')
    parser.add_argument('--test-libclang', action='store_true', help='Test libclang configuration and print diagnostic information')
    parser.add_argument('--debug-libclang', action='store_true', help='Enable detailed debug output for libclang configuration')
    parser.add_argument('--version', action='store_true', help='Show version information and exit')
    
    # Plugin system options
    plugin_group = parser.add_argument_group('Plugin Options')
    plugin_group.add_argument('--plugin-dir', action='append', help='Additional plugin directory for DSL feature detectors')
    plugin_group.add_argument('--disable-plugins', action='store_true', help='Disable plugin system entirely')
    plugin_group.add_argument('--list-plugins', action='store_true', help='List all available plugins and exit')
    plugin_group.add_argument('--disable-plugin', action='append', dest='disabled_plugins', 
                         help='Disable specific plugin by name, can be used multiple times')
    plugin_group.add_argument('--only-plugin', action='append', dest='only_plugins',
                         help='Only enable specified plugin, can be used multiple times')
    args = parser.parse_args()
    
    # Version check is handled above, but keep this for completeness
    if args.version:
        print(f"foamCD {get_version()}")
        return 0
        
    if args.generate_config:
        Config.generate_default_config(args.generate_config, overrides)
        logger = setup_logging()
        if overrides:
            logger.info(f"Generated default configuration at {args.generate_config} with {len(overrides)} overrides")
            for key, value in overrides.items():
                logger.info(f"  {key} = {value}")
        else:
            logger.info(f"Generated default configuration at {args.generate_config}")
        return 0
        
    config_obj = Config(args.config)
    logger = setup_logging(args.verbose or args.debug_libclang)
    
    # Handle plugin listing if requested
    if args.list_plugins and not args.disable_plugins:
        # Get plugin configuration from both config file and command line args
        plugin_config = config_obj.get('parser.plugins', {})
        if args.disabled_plugins:
            plugin_config['disabled_plugins'] = args.disabled_plugins
        if args.only_plugins:
            plugin_config['only_plugins'] = args.only_plugins
            
        plugin_dirs = args.plugin_dir or config_obj.get("parser.plugin_dirs", [])
        
        # Create a single plugin manager to discover all plugins
        plugin_manager = PluginManager(plugin_dirs)
        
        # First do a discovery pass without filtering to find all available plugins
        logger.info("Discovering all available plugins...")
        plugin_manager.plugins_enabled = True  # Temporarily enable all plugins
        plugin_manager.disabled_plugins = set()
        plugin_manager.only_plugins = set()
        plugin_manager.discover_plugins()
        
        # Get all available plugin names
        all_plugins = set(plugin_manager.detectors.keys())
        
        # Now determine which would be enabled with current configuration
        enabled_plugins = set()
        for plugin_name in all_plugins:
            if plugin_config.get('disabled_plugins') and plugin_name in plugin_config.get('disabled_plugins', []):
                # Plugin is explicitly disabled
                continue
                
            if plugin_config.get('only_plugins') and plugin_name not in plugin_config.get('only_plugins', []):
                # Plugin is not in whitelist
                continue
                
            # Plugin would be enabled
            enabled_plugins.add(plugin_name)
        
        if plugin_manager.detectors:
            print("Available DSL feature detectors:")
            print("-" * 100)
            print(f"{'Name':<20} {'Status':<10} {'Version':<10} {'Description':<50}")
            print("-" * 100)
            for name, detector in sorted(plugin_manager.detectors.items()):
                status = "Enabled" if name in enabled_plugins else "Disabled"
                print(f"{name:<20} {status:<10} {detector.cpp_version:<10} {detector.description:<50}")
                
            # Show custom entity fields if any exist
            if plugin_manager.custom_entity_fields:
                print("\nCustom entity fields:")
                print("-" * 100)
                print(f"{'Field Name':<25} {'Type':<10} {'Plugin':<15} {'Status':<10} {'Description':<30}")
                print("-" * 100)
                for field_name, field_def in sorted(plugin_manager.custom_entity_fields.items()):
                    plugin = field_def['plugin']
                    status = "Enabled" if plugin in enabled_plugins else "Disabled"
                    print(f"{field_name:<25} {field_def['type']:<10} {plugin:<15} {status:<10} {field_def['description']:<30}")
                    
            # Show plugin configuration summary
            print("\nPlugin configuration:")
            print("-" * 100)
            if plugin_config.get('disabled_plugins'):
                print(f"Disabled plugins: {', '.join(plugin_config.get('disabled_plugins'))}")
            if plugin_config.get('only_plugins'):
                print(f"Whitelisted plugins: {', '.join(plugin_config.get('only_plugins'))}")
            if not plugin_config.get('disabled_plugins') and not plugin_config.get('only_plugins'):
                print("All discovered plugins are enabled")
        else:
            print("No plugins found.")
            
        return 0
    
    if args.debug_libclang:
        logger.debug("Libclang debugging enabled")
        logger.debug(f"Python executable: {sys.executable}")
        logger.debug(f"Python version: {platform.python_version()}")
        logger.debug(f"System: {platform.system()} {platform.release()}")
    
    if args.test_libclang:
        libclang_path = config_obj.get('parser.libclang_path')
        if libclang_path and os.path.exists(libclang_path):
            try:
                clang.cindex.Config.set_library_file(libclang_path)
                clang.cindex.Index.create()
                logger.info(f"Success! libclang configured with: {libclang_path}")
                return 0
            except Exception as e:
                import traceback
                logger.error(f"Could not use specified libclang library: {e}\nTraceback: {traceback.format_exc()}")
                return 1
        elif LIBCLANG_CONFIGURED:
            logger.info("Success! libclang is already configured and working.")
            return 0
        else:
            import traceback
            logger.error(f"libclang is not properly configured. Add 'parser.libclang_path' to your config file.\nTraceback: {traceback.format_exc()}")
            return 1
    
    try:
        # Command line args have priority over config values
        compile_commands_dir = args.compile_commands_dir or config_obj.get('parser.compile_commands_dir')
        if compile_commands_dir:
            logger.info(f"Using compilation database from: {compile_commands_dir}")
        else:
            logger.warning("No compilation database provided, using default compilation settings")
        db_path = args.output or config_obj.get('database.path', 'docs.db')
        db = EntityDatabase(db_path)
        
        # Setup plugin configuration from both config file and command line args
        plugin_config = config_obj.get('parser.plugins', {})
        
        # Command line arguments override config file settings
        if args.disabled_plugins:
            plugin_config['disabled_plugins'] = args.disabled_plugins
        if args.only_plugins:
            plugin_config['only_plugins'] = args.only_plugins
        
        # Initialize parser with plugin support
        parser = ClangParser(
            compilation_database_dir=compile_commands_dir,
            db=db,
            config=config_obj,
            plugin_dirs=args.plugin_dir,
            disable_plugins=args.disable_plugins
        )
        
        if args.file:
            if not os.path.exists(args.file):
                import traceback
                logger.error(f"File not found: {args.file}\nTraceback: {traceback.format_exc()}")
                return 1
            logger.debug(f"Parsing file: {args.file}")
            entities = parser.parse_file(args.file)
            logger.debug(f"Parsed {len(entities)} top-level entities")
        else:
            target_files = config_obj.get('parser.target_files', [])
            if compile_commands_dir and not target_files:
                target_files = get_source_files_from_compilation_database(compile_commands_dir)
            if not target_files:
                import traceback
                logger.error(f"""No files to parse. Specify --file, --compile-commands, or (compile_commands_dir or target_files) in config.
                             Kudos to you for somehow missing every single option! Get it together please!\nTraceback: {traceback.format_exc()}""")
                return 1
            parsed_count = 0
            unchanged_count = 0
            error_count = 0
            
            for filepath in target_files:
                if not os.path.exists(filepath):
                    logger.warning(f"File not found: {filepath}")
                    error_count += 1
                    continue
                    
                # Check if the file has changed since last parsing
                if db:
                    file_stats = os.stat(filepath)
                    last_modified = int(file_stats.st_mtime)
                    
                    with open(filepath, 'rb') as f:
                        file_content = f.read()
                        file_hash = hashlib.md5(file_content).hexdigest()
                    
                    if not db.file_changed(filepath, last_modified, file_hash):
                        cached_entities = db.get_entities_by_file(filepath)
                        if cached_entities:
                            logger.debug(f"Using cached entities for unchanged file: {filepath}")
                            parser.entities[filepath] = cached_entities
                            unchanged_count += 1
                            continue
                
                logger.debug(f"Parsing file: {filepath}")
                entities = parser.parse_file(filepath)
                if entities:
                    parsed_count += 1
                else:
                    error_count += 1
            
            logger.info(f"Processing complete: {parsed_count} parsed, {unchanged_count} unchanged, {error_count} errors (from {len(target_files)} total files)")
        
        logger.info("Resolving inheritance relationships between entities...")
        parser.resolve_inheritance_relationships()
        logger.debug("Inheritance relationships resolved and base_child_links populated")
        
        logger.info("Parsing complete")
        return 0
        
    except Exception as e:
        import traceback
        logger.error(f"Error: {e}\nTraceback: {traceback.format_exc()}")
        logger.debug("Exception details:", exc_info=True)
        return 1
    
    return 0

if __name__ == '__main__':
    sys.exit(main() or 0)
