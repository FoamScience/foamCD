#!/usr/bin/env python3

import os
import sys
import hashlib
import argparse
import platform
from pathlib import Path
from typing import Dict, List, Optional, Set, Any

from logs import setup_logging
from db import EntityDatabase
from config import Config

logger = setup_logging()

CPP_FILE_EXTENSIONS = ['.hpp', '.hxx', '.h++', '.hh', '.H', '.cpp', '.cxx', '.c++', '.cc', '.C']

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
from entity import Entity

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
    
    def __init__(self, compilation_database_dir: str = None, db: Optional[EntityDatabase] = None, config: Optional[Config] = None):
        if not LIBCLANG_CONFIGURED:
            raise ImportError("libclang is not properly configured. Parser functionality is unavailable.")
        self.config = config or Config()
        self.index = clang.cindex.Index.create()
        self.entities: Dict[str, List[Entity]] = {}
        self.db = db
        if compilation_database_dir:
            try:
                self.compilation_database = clang.cindex.CompilationDatabase.fromDirectory(compilation_database_dir)
            except Exception as e:
                raise ValueError(f"Error loading compilation database: {e}")
        
    def get_compile_commands(self, filepath: str) -> List[str]:
        """Get compilation arguments for a file from the compilation database"""
        try:
            if hasattr(self, 'compilation_database'):
                commands = self.compilation_database.getCompileCommands(filepath)
                if commands:
                    all_args = []
                    for command in commands:
                        try:
                            if hasattr(command, 'arguments') and isinstance(command.arguments, list):
                                all_args.extend(command.arguments[1:])
                            elif hasattr(command, 'arguments'):
                                args = list(command.arguments)
                                if args and len(args) > 1:
                                    all_args.extend(args[1:])
                        except (IndexError, TypeError) as e:
                            logger.debug(f"Could not extract arguments from command: {e}")
                    if all_args:
                        return all_args
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
        """Extract documentation comment for a cursor"""
        raw_comment = cursor.raw_comment
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
            elif line.startswith('//'):
                line = line[2:]
            processed_lines.append(line.strip())
        return '\n'.join(processed_lines).strip()
    
    def detect_cpp_features(self, cursor: clang.cindex.Cursor) -> Set[str]:
        """Detect C++ language features used by this cursor and its children"""
        features = set()
        
        # Get all available cursor kinds for compatibility checking
        available_cursor_kinds = dir(CursorKind)
        all_token_spellings = [t.spelling for t in cursor.get_tokens()]
        all_token_text = ' '.join(all_token_spellings)
        
        # Basic feature detection based on token text
        if 'static_assert' in all_token_text:
            features.add('static_assert')  # C++11
        if 'decltype' in all_token_text:
            features.add('decltype')  # C++11
            
        if '...' in all_token_text and ('template' in all_token_text or
                cursor.kind in [CursorKind.FUNCTION_TEMPLATE, CursorKind.CLASS_TEMPLATE]):
            features.add('variadic_templates')  # C++11
            
        if 'template' in all_token_text and cursor.kind == CursorKind.VAR_DECL:
            features.add('variable_templates')  # C++14
            
        if cursor.kind == CursorKind.VAR_DECL and cursor.spelling.startswith('pi_v'):
            features.add('variable_templates')  # C++14
            
        if '[' in all_token_text and '=' in all_token_text and ']' in all_token_text and 'lambda_capture_init' in cursor.spelling:
            features.add('lambda_capture_init')  # C++14
        elif cursor.kind == CursorKind.LAMBDA_EXPR:
            capture_init_pattern = False
            for i in range(len(all_token_spellings) - 2):
                if all_token_spellings[i] == '[' and all_token_spellings[i+1] != ']' and '=' in all_token_spellings[i+1:i+5]:
                    capture_init_pattern = True
                    break
            if capture_init_pattern:
                features.add('lambda_capture_init')  # C++14
                
        if cursor.spelling == 'constexpr_extension' or 'constexpr_extension' in all_token_text:
            features.add('constexpr_extension')  # C++14
        elif 'constexpr' in all_token_spellings and cursor.kind == CursorKind.FUNCTION_DECL:
            has_complex_logic = False
            if 'for' in all_token_spellings or 'while' in all_token_spellings:
                has_complex_logic = True
            if has_complex_logic:
                features.add('constexpr_extension')  # C++14
        
        conversion_op_detected = False
        if cursor.kind == CursorKind.CONVERSION_FUNCTION:
            if 'explicit' in all_token_spellings:
                conversion_op_detected = True
            elif cursor.semantic_parent and hasattr(cursor, 'spelling'):
                class_name = cursor.semantic_parent.spelling
                if class_name and f"{class_name}::operator" in cursor.spelling:
                    conversion_op_detected = True
        elif 'explicit' in all_token_spellings and 'operator' in all_token_text:
            conversion_op_detected = True
        elif cursor.kind == CursorKind.CXX_METHOD:
            if 'operator' in cursor.spelling and not cursor.spelling.startswith('operator[]'):
                if 'explicit' in all_token_spellings:
                    conversion_op_detected = True
        if conversion_op_detected:
            features.add('explicit_conversion')  # C++11
            features.add('operator_overloading')  # C++98
        
        if cursor.kind in [CursorKind.CLASS_DECL, CursorKind.STRUCT_DECL]:
            features.add('classes')  # C++98
            base_specifiers = [child for child in cursor.get_children() 
                              if child.kind == CursorKind.CXX_BASE_SPECIFIER]
            if base_specifiers:
                features.add('inheritance')  # C++98
                if len(base_specifiers) >= 2:
                    features.add('multiple_inheritance')  # C++98
        
        elif cursor.kind == CursorKind.NAMESPACE:
            features.add('namespaces')  # C++98
            tokens = list(cursor.get_tokens())
            if len(tokens) >= 2:
                namespace_tokens = [t.spelling for t in tokens if t.spelling != '{' and t.spelling != '}'][:3]
                if '::' in namespace_tokens:
                    features.add('nested_namespaces')  # C++17
        
        elif cursor.kind in [CursorKind.FUNCTION_TEMPLATE, CursorKind.CLASS_TEMPLATE]:
            features.add('templates')  # C++98
            for child in cursor.get_children():
                if child.kind == CursorKind.TEMPLATE_TYPE_PARAMETER:
                    if '...' in child.spelling:
                        features.add('variadic_templates')  # C++11
                        break
            if cursor.spelling.startswith('variable_template') or \
               (cursor.kind == CursorKind.VAR_DECL and cursor.specialization_of):
                features.add('variable_templates')  # C++14
        
        elif cursor.kind == CursorKind.LAMBDA_EXPR:
            features.add('lambda_expressions')  # C++11
            for child in cursor.get_children():
                if child.kind == CursorKind.PARM_DECL and child.type.spelling == 'auto':
                    features.add('generic_lambdas')  # C++14
                    break
            for child in cursor.get_children():
                if child.kind == CursorKind.COMPOUND_STMT:
                    capture_init = False
                    for c in child.get_children():
                        if c.kind == CursorKind.INIT_CAPTURE_EXPR:
                            features.add('lambda_capture_init')  # C++14
                            capture_init = True
                            break
                    if capture_init:
                        break
                    
        elif cursor.kind == CursorKind.CXX_NULL_PTR_LITERAL_EXPR:
            features.add('nullptr')  # C++11
        elif cursor.kind == CursorKind.CXX_CATCH_STMT or cursor.kind == CursorKind.CXX_TRY_STMT:
            features.add('exceptions')  # C++98
        elif cursor.kind == CursorKind.CXX_METHOD and 'operator' in cursor.spelling:
            features.add('operator_overloading')  # C++98
            
        # Check for function overloading - requires context outside of just the cursor
        elif cursor.kind == CursorKind.FUNCTION_DECL:
            parent = cursor.semantic_parent
            if parent:
                overload_count = 0
                for child in parent.get_children():
                    if child.kind == CursorKind.FUNCTION_DECL and child.spelling == cursor.spelling:
                        overload_count += 1
                if overload_count > 1:
                    features.add('function_overloading')  # C++98
        
        elif 'CXX_AUTO_TYPE_DECL' in available_cursor_kinds and cursor.kind == CursorKind.CXX_AUTO_TYPE_DECL:
            features.add('auto_type')  # C++11
        elif cursor.kind == CursorKind.TYPE_REF and cursor.spelling == 'auto':
            features.add('auto_type')  # C++11, in case used libclang doesn't name it CXX_AUTO_TYPE_DECL
            
        elif cursor.kind == CursorKind.USING_DECLARATION:
            features.add('using_declaration')  # C++11
            
        elif cursor.kind == CursorKind.ENUM_DECL:
            tokens = list(cursor.get_tokens())
            for i, token in enumerate(tokens):
                if token.spelling == 'class' and i > 0 and tokens[i-1].spelling == 'enum':
                    features.add('class_enum')  # C++11
                    break
        
        elif cursor.kind == CursorKind.STATIC_ASSERT:
            features.add('static_assert')  # C++11
            
        elif cursor.kind == CursorKind.DECL_REF_EXPR or cursor.kind == CursorKind.TYPE_REF:
            tokens = list(cursor.get_tokens())
            if any(t.spelling == 'decltype' for t in tokens):
                features.add('decltype')  # C++11
        
        elif 'STRUCTURED_BINDING' in available_cursor_kinds and cursor.kind == CursorKind.STRUCTURED_BINDING:
            features.add('structured_bindings')  # C++17
            
        # TODO: check for selection statements with initializer (C++17)
        # Pattern: if (int x = foo(); x > 0) or similar
            
        # Check for constexpr if (C++17)
        elif cursor.kind == CursorKind.IF_STMT:
            tokens = list(cursor.get_tokens())
            token_spellings = [t.spelling for t in tokens]
            token_str = ' '.join(token_spellings)
            
            # Pattern 1: Direct 'constexpr if' sequence
            constexpr_found = False
            for i, token in enumerate(tokens):
                if token.spelling == 'constexpr':
                    constexpr_found = True
                    if i+1 < len(tokens):
                        if tokens[i+1].spelling == 'if':
                            features.add('constexpr_if')  # C++17
                            features.add('if_constexpr')   # Same feature, different name
                            break
                    
            # Pattern 2: Look for the pattern in the token string with spaces
            if 'constexpr if' in token_str or 'constexpr  if' in token_str:
                features.add('constexpr_if')  # C++17
                features.add('if_constexpr')   # Same feature, different name
                
            # Pattern 3: Look for both tokens in any order but close to each other
            if 'constexpr' in token_spellings and 'if' in token_spellings:
                constexpr_indices = [i for i, x in enumerate(token_spellings) if x == 'constexpr']
                if_indices = [i for i, x in enumerate(token_spellings) if x == 'if']
                
                for constexpr_idx in constexpr_indices:
                    for if_idx in if_indices:
                        # Check if 'if' appears after 'constexpr' within a reasonable distance
                        if if_idx > constexpr_idx:
                            distance = if_idx - constexpr_idx
                            if distance < 5:  # Allow some tokens between
                                features.add('constexpr_if')  # C++17
                                features.add('if_constexpr')   # Same feature, different name
                                break
                
        elif cursor.kind == CursorKind.BINARY_OPERATOR:
            tokens = list(cursor.get_tokens())
            token_str = ''.join(t.spelling for t in tokens)
            if '...' in token_str and any(op in token_str for op in ['+', '*', '&', '|', '&&', '||']):
                features.add('fold_expressions')  # C++17
        
        elif cursor.kind == CursorKind.CONCEPT_DECL:
            features.add('concepts')  # C++20
            
        elif cursor.kind == CursorKind.FUNCTION_DECL or cursor.kind == CursorKind.CXX_METHOD:
            tokens = list(cursor.get_tokens())
            token_str = ''.join(t.spelling for t in tokens)
            if 'co_await' in token_str or 'co_yield' in token_str or 'co_return' in token_str:
                features.add('coroutines')  # C++20
        
        tokens = list(cursor.get_tokens())
        token_spellings = [t.spelling for t in tokens]
        
        if cursor.kind == CursorKind.PARM_DECL or cursor.kind == CursorKind.VAR_DECL:
            if cursor.type and cursor.type.spelling and '&' in cursor.type.spelling and '&&' not in cursor.type.spelling:
                features.add('references')  # C++98
        
        if '&&' in token_spellings:
            features.add('rvalue_references')  # C++11
            if 'move' in token_spellings:
                features.add('move_semantics')  # C++11
        
        if 'for' in token_spellings and ':' in token_spellings:
            range_for_pattern = False
            for i, token in enumerate(token_spellings):
                if token == 'for' and i+2 < len(token_spellings) and token_spellings[i+2] == ':':  
                    range_for_pattern = True
                    break
            if range_for_pattern:
                features.add('range_based_for')  # C++11
        
        if 'unique_ptr' in ''.join(token_spellings) or 'shared_ptr' in ''.join(token_spellings):
            features.add('smart_pointers')  # C++11
            
        if '{' in token_spellings and '}' in token_spellings:
            is_initializer_list = False
            if cursor.kind in [CursorKind.CONSTRUCTOR, CursorKind.VAR_DECL, CursorKind.FIELD_DECL]:
                is_initializer_list = True
            if is_initializer_list:
                features.add('initializer_lists')  # C++11
        
        if cursor.kind in [CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD] and 'constexpr' in token_spellings:
            features.add('constexpr')  # C++11
            if 'consteval' in token_spellings:
                features.add('consteval')  # C++20
            if 'constinit' in token_spellings:
                features.add('constinit')  # C++20
            if 'virtual' in token_spellings:
                features.add('constexpr_virtual')  # C++20
        
        if cursor.kind == CursorKind.FUNCTION_DECL and 'auto' in token_spellings:
            features.add('return_type_deduction')  # C++14
        
        if '<=>' in token_spellings:
            features.add('three_way_comparison')  # C++20
        
        for token in token_spellings:
            if '0b' in token or '0B' in token:
                features.add('binary_literals')  # C++14
            if "'" in token and any(c.isdigit() for c in token):
                features.add('digit_separators')  # C++14
        
        if 'final' in token_spellings:
            features.add('final_override')  # C++11
        if 'override' in token_spellings:
            features.add('final_override')  # C++11
        
        if cursor.kind == CursorKind.CONVERSION_FUNCTION and 'explicit' in token_spellings:
            features.add('explicit_conversion')  # C++11
            features.add('operator_overloading')  # C++98
        elif (cursor.kind == CursorKind.CXX_METHOD and 
              'operator' in cursor.spelling and 
              'explicit' in token_spellings):
            features.add('explicit_conversion')  # C++11
            logger.debug(f"Detected explicit conversion via method name: {cursor.spelling} in {cursor.location.file.name if cursor.location.file else 'unknown'}:{cursor.location.line}")
            features.add('operator_overloading')  # C++98
        
        if cursor.kind == CursorKind.CONSTRUCTOR:
            class_name = cursor.semantic_parent.spelling if cursor.semantic_parent else None
            for child in cursor.get_children():
                if child.kind == CursorKind.MEMBER_REF_EXPR and child.spelling == class_name:
                    features.add('delegating_constructors')  # C++11
                    logger.debug(f"Detected delegating constructor via MEMBER_REF_EXPR: {cursor.spelling} in {cursor.location.file.name if cursor.location.file else 'unknown'}:{cursor.location.line}")
                    break
            tokens = list(cursor.get_tokens())
            token_str = ' '.join(t.spelling for t in tokens)
            if class_name and ': ' + class_name + '(' in token_str:
                features.add('delegating_constructors')  # C++11
            # Check for constructor initializers without relying on CXX_CTOR_INITIALIZER
            # This is a safer approach that works across different libclang versions
            for child in cursor.get_children():
                if (hasattr(child, 'referenced') and child.referenced and 
                    hasattr(child.referenced, 'semantic_parent') and child.referenced.semantic_parent and
                    child.referenced.semantic_parent.spelling == class_name):
                    features.add('delegating_constructors')  # C++11
                    break
        
        # Library features that are harder to detect just from AST

        token_str = ''.join(token_spellings)
        if 'type_traits' in token_str or '::is_' in token_str or '::has_' in token_str:
            features.add('type_traits')  # C++11
        if 'filesystem' in token_str or 'fs::' in token_str:
            features.add('filesystem')  # C++17
        if 'execution::par' in token_str or 'execution::seq' in token_str or 'execution::unseq' in token_str:
            features.add('parallel_algorithms')  # C++17
        if 'ranges::' in token_str or 'views::' in token_str:
            features.add('ranges')  # C++20
            
        src_text = ''.join([t.spelling for t in tokens])
        
        if '{.' in src_text and '=' in src_text:
            features.add('designated_initializers')  # C++20
        if '=default' in src_text or '=delete' in src_text:
            features.add('default_delete')  # C++11
        if 'invoke(' in src_text or 'std::invoke' in src_text:
            features.add('invoke')  # C++17
        if 'inline' in token_spellings and cursor.kind == CursorKind.VAR_DECL:
            features.add('inline_variables')  # C++17
        
        if 'import' in token_spellings or 'module' in token_spellings:
            src_text = ' '.join(token_spellings)
            if 'import ' in src_text or 'module ' in src_text:
                features.add('modules')  # C++20
                
        if cursor.kind == CursorKind.CLASS_DECL or cursor.kind == CursorKind.STRUCT_DECL:
            has_default_member_init = False
            for child in cursor.get_children():
                if child.kind == CursorKind.FIELD_DECL and list(child.get_children()):
                    has_default_member_init = True
                    break
            if has_default_member_init:
                features.add('aggregate_initialization')  # C++20
                
        if cursor.kind == CursorKind.TEMPLATE_NON_TYPE_PARAMETER:
            if cursor.type and cursor.type.kind != TypeKind.INVALID and \
               cursor.type.kind not in [TypeKind.BOOL, TypeKind.INT, TypeKind.LONG, TypeKind.LONGLONG]:
                features.add('nontype_template_parameters')  # C++20
        
        if cursor.kind == CursorKind.DECL_REF_EXPR and cursor.type:
            if '<' not in cursor.spelling and cursor.type.spelling and '<' in cursor.type.spelling:
                features.add('class_template_argument_deduction')  # C++17
                
        if cursor.kind == CursorKind.VAR_DECL and 'auto' in token_spellings:
            src_text = ''.join(token_spellings)
            if '{' in src_text and '}' in src_text:
                features.add('auto_deduction_from_braced_init')  # C++17
                
        if cursor.kind == CursorKind.MACRO_DEFINITION and cursor.spelling.startswith('__cpp_'):
            features.add('feature_test_macros')  # C++20
            
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
        entity.access = cursor.access_specifier
        entity.linkage = cursor.linkage
        if cursor.type and cursor.type.spelling:
            entity.type_info = cursor.type.spelling
        entity.cpp_features = self.detect_cpp_features(cursor)
        
        # Process method/class-specific attributes
        self._process_method_classification(entity, cursor)
        self._process_class_features(entity, cursor)
        
        return entity
        
    def _process_method_classification(self, entity: Entity, cursor: clang.cindex.Cursor) -> None:
        """Process C++ method classifications (virtual, override, etc.)"""
        if cursor.kind != clang.cindex.CursorKind.CXX_METHOD:
            return
            
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
        
        tokens = list(cursor.get_tokens())
        token_spellings = [t.spelling for t in tokens]
        
        if '=' in token_spellings:
            equal_index = token_spellings.index('=')
            if equal_index < len(token_spellings) - 1:
                next_token = token_spellings[equal_index + 1]
                if next_token == 'default':
                    entity.is_defaulted = True
                elif next_token == 'delete':
                    entity.is_deleted = True
    
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
        for _, entities in self.entities.items():
            for entity in entities:
                if entity.name == base_class_name:
                    base_class_info['uuid'] = entity.uuid
                    break
        
        return base_class_info
        
    def parse_file(self, filepath: str) -> List[Entity]:
        """Parse a C++ file and return its entities"""
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
        
        try:
            logger.debug(f"parsing translation unit {filepath} with index.parse")
            translation_unit = self.index.parse(filepath, clean_args)
            
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
                    logger.error(f"Parsing diagnostics for {filepath}: {error_count} errors, {warning_count} warnings, {note_count} notes\nTraceback: {traceback.format_exc()}")
                elif warning_count > 0:
                    logger.warning(f"Parsing diagnostics for {filepath}: {warning_count} warnings, {note_count} notes")
                    
                # Fatal error - can't continue with parsing
                if error_count > 0:
                    logger.error(f"Error parsing {filepath}: Failed to parse translation unit due to compilation errors.\nTraceback: {traceback.format_exc()}")
                    return []
                    
        except Exception as e:
            import traceback
            logger.error(f"Exception while parsing {filepath}: {e}\nTraceback: {traceback.format_exc()}")
            return []
        
        file_entities = []
        self._process_cursor(translation_unit.cursor, file_entities)
        self.entities[filepath] = file_entities
        if self.db:
            for entity in file_entities:
                self.db.store_entity(entity.to_dict())
        
        logger.info(f"Successfully parsed {len(file_entities)} top-level entities")
        return file_entities
    
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
                if parent:
                    parent.add_child(entity)
                else:
                    entities.append(entity)
                for child in cursor.get_children():
                    self._process_cursor(child, entities, entity)
        else:
            for child in cursor.get_children():
                self._process_cursor(child, entities, parent)

    def export_to_database(self, output_path: str):
        """Export parsed entities to SQLite database
        
        Args:
            output_path: Path to output SQLite database file
        """
        if self.db:
            if output_path != self.db.db_path:
                logger.info(f"Exporting entities to SQLite database {output_path}")
                new_db = EntityDatabase(output_path)
                all_entities = self.db.get_all_entities()
                for entity in all_entities:
                    new_db.store_entity(entity)
                new_db.close()
                logger.info(f"Exported entities to {output_path}")
        else:
            logger.info(f"Creating new SQLite database {output_path}")
            db = EntityDatabase(output_path)
            for file_entities in self.entities.values():
                for entity in file_entities:
                    db.store_entity(entity.to_dict())
            db.close()
            logger.info(f"Exported entities to {output_path}")

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
    parser = argparse.ArgumentParser(description='Parse C++ files using libclang and extract documentation.')
    parser.add_argument('--generate-config', '-g', type=str, help='Generate default configuration file at specified path')
    parser.add_argument('--config', '-c', type=str, help='Path to YAML configuration file')
    parser.add_argument('--compile-commands-dir', type=str, help='Path to directory containing compile_commands.json, overrides the YAML config')
    parser.add_argument('--output', '-o', type=str, help='Output SQLite database file, overrides the YAML config')
    parser.add_argument('--file', '-f', type=str, help='Path to specific file to parse, overrides compilation databases')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output')
    parser.add_argument('--test-libclang', action='store_true', help='Test libclang configuration and print diagnostic information')
    parser.add_argument('--debug-libclang', action='store_true', help='Enable detailed debug output for libclang configuration')
    args = parser.parse_args()
    
    if args.generate_config:
        Config.generate_default_config(args.generate_config)
        logger.info(f"Generated default configuration at {args.generate_config}")
        return 0
    config_obj = Config(args.config)
    logger = setup_logging(args.verbose or args.debug_libclang)
    
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
        parser = ClangParser(compile_commands_dir, db, config_obj)
        
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
