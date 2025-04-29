#!/usr/bin/env python3

"""
This is a very specialized plugin to support reflection-style parsing
with the end goal of "automatically" getting an always-up-to-date
and compiler-generated standard configuration of C++ classes.

Concerned reflection library: https://github.com/FoamScience/openfoam-reflections

WARNING: Uses cppyy/cling to run c++ code in an "interpreted fashion" (JITC).

NOTE: Currently, an OpenFOAM version must be sourced in the shell running this
detector. We don't much, just the libOpenFOAM.so library so we can get the
dictionary as a string. This conversion dictionary -> string is the only runtime
cost of doing this (besides including files and loading libraries obviously)

"""

import os
try:
    import cppyy
    CPPYY_AVAILABLE = True
except ImportError:
    CPPYY_AVAILABLE = False
from clang.cindex import CursorKind
from foamcd.feature_detectors import FeatureDetector
from foamcd.logs import setup_logging

logger = setup_logging()

class OpenFOAMReflectionsDetector(FeatureDetector):
    """
    Detector for OpenFOAM reflection library features.
    
    This detector identifies classes that implement self-reflection using the UI model
    pattern with declareSchemaTable and similar patterns. It uses cppyy to JIT compile
    and execute reflection code to extract standard configuration.
    
    For classes that implement the reflection pattern, it:
    1. Checks if they satisfy the SelfReflectableModel concept, provided by the above library
    2. Uses cppyy to compile and run Reflect::reflect<Type>::schema()
    3. Captures the output for use in documentation
    """
    
    # Define custom entity fields for reflection information
    entity_fields = {
        "standard_config": {
            "type": "TEXT",
            "description": "Standard configuration extracted from reflection"
        },
        "standard_config_details": {
            "type": "TEXT",
            "description": "Details about standard configuration"
        },
        "is_reflectable": {
            "type": "INTEGER",
            "description": "Flag indicating if the class is self-reflectable (1) or not (0)"
        },
        "reflection_type": {
            "type": "TEXT",
            "description": "Type of reflection pattern used"
        },
        "reflection_error": {
            "type": "TEXT",
            "description": "Any errors encountered during reflection extraction"
        }
    }
    
    def __init__(self):
        super().__init__("openfoam_reflections", "DSL", "OpenFOAM Reflection Features")
        
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        """
        Detect OpenFOAM reflection patterns in class declarations
        """
        # TODO: complex handling of templates; as we need concrete types 
        #       to test for concept
        if cursor.kind not in [CursorKind.CLASS_DECL, CursorKind.STRUCT_DECL]:
            return False
            
        # Check for reflection-related patterns
        reflection_patterns = [
            'declareSchemaTable',
            'uiElement',
            'withDefault',
            'withDescription',
            'withMin',
            'withMax'
        ]
        
        if not any(pattern in token_str for pattern in reflection_patterns):
            return False
        short_class_name = cursor.spelling
        if not short_class_name:
            return False

        # Fully qualified name
        namespace = ""
        parent = cursor.semantic_parent
        namespace_parts = []
        while parent and parent.kind != CursorKind.TRANSLATION_UNIT:
            if parent.spelling:
                namespace_parts.insert(0, parent.spelling)
            parent = parent.semantic_parent
        namespace = "::" + "::" .join(namespace_parts) + "::" if namespace_parts else ""
        class_name = namespace + short_class_name
        if class_name.startswith("::"):
            class_name = class_name[2:]
            
        file_path = cursor.location.file.name if cursor.location.file else None
        if not file_path:
            return False
            
        fields = {
            'is_reflectable': False,
            'reflection_type': 'SchemaTable',
            'standard_config': '',
            'standard_config_details': '',
            'reflection_error': ''
        }
        
        from foamcd.parse import CURRENT_PARSER
        parser = CURRENT_PARSER
        
        if not parser:
            logger.error("No parser picked up by the openfoam_reflections detector, cannot function...")
            return {'detected': False, 'fields': fields}

        # Here is the magical bit
        try:
            compile_args = parser.get_compile_commands(file_path) if hasattr(parser, 'get_compile_commands') else []
            is_reflectable, config, details = self._extract_reflection_config(class_name, file_path, compile_args)
            if is_reflectable:
                fields['is_reflectable'] = True
                fields['standard_config'] = config
                fields['standard_config_details'] = details
                logger.info(f"Successfully extracted reflection configuration for {class_name}")
        except Exception as e:
            logger.error(f"Error extracting reflection config: {e}")
            fields['reflection_error'] = str(e)
            
        return {
            'detected': fields["is_reflectable"],
            'fields': fields
        }
        
    def _extract_reflection_config(self, class_name, file_path, compile_args):
        """
        Use cppyy to compile and run reflection code to extract standard configuration
        
        Args:
            class_name: Name of the class to reflect
            file_path: Path to the source file
            compile_args: Compilation arguments from the parser
            
        Returns:
            True Boolean if class_name is reflectable type, False otherwise
            Extracted standard configuration as string or None if extraction failed
            Details on standard configuration as string or None if extraction failed
        """
        try:
            if not CPPYY_AVAILABLE:
                logger.error("cppyy module not available for JIT compilation")
                return False, None, None
            
            standard = [arg[5:] for arg in compile_args if arg.startswith('-std=')]
            if len(standard) > 0:
                standard = standard[-1]
            else:
                standard = "c++20"
            os.environ["CLING_STANDARD"] = standard
            include_paths = [arg[2:] for arg in compile_args if arg.startswith('-I')]
            macro_defs = [arg[2:] for arg in compile_args if arg.startswith('-D')]

            for include_path in include_paths:
                cppyy.add_include_path(include_path)
            
            # TODO: maybe work towards metigating the need for libOpenFOAM.so
            cppyy.add_library_path(os.environ["FOAM_LIBBIN"])
            cppyy.load_library("libOpenFOAM.so")

            for macro_def in macro_defs:
                try:
                    if '=' in macro_def:
                        name, value = macro_def.split('=', 1)
                        cppyy.cppdef(f"#define {name} {value}")
                    else:
                        cppyy.cppdef(f"#define {macro_def}")
                except Exception as e:
                    logger.warning(f"Failed to add macro definition {macro_def}: {e}")
            
            try:
                cppyy.include("dictionary.H")
                cppyy.include("OStringStream.H")
                cppyy.include(file_path)
                cppyy.include("reflectConcepts.H")
            except Exception as e:
                logger.error(f"Failed to include necessary headers: {e}")
                return False, None, None
            
            # The business end of things:
            cppyy.cppdef(f"""
            #ifndef __GET_REFLECTION_DICT__
            #define __GET_REFLECTION_DICT__
            template<class T, bool C>
            std::string getReflectionDict() {{
                Foam::OStringStream oss;
                oss << Foam::Reflect::reflect<T, C>::schema(Foam::dictionary::null);
                return oss.str();
            }}
            #endif
            """)

            try:
                standard_config = cppyy.gbl.getReflectionDict[class_name, "true"]()
                standard_config = standard_config.decode("utf-8").replace('\\"', '').replace('\\\n',' ').strip()
                standard_config_details = cppyy.gbl.getReflectionDict[class_name, "false"]()
                standard_config_details = standard_config_details.decode("utf-8").replace('\\"', '').replace('\\\n',' ').strip()
                logger.debug(f"{class_name} seems to support reflection. fetched standard configuration")
                return True, standard_config, standard_config_details
                
            except Exception as e:
                logger.debug(f"{class_name} seems to not support reflection. We just bail out: {e}")
                return False, None, None
        except Exception as e:
            logger.error(f"Something went wrong with checking reflectability. We just bail out {e}")
            return False, None, None
