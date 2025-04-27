#!/usr/bin/env python3

import re
from clang.cindex import CursorKind
from foamcd.feature_detectors import FeatureDetector

class OpenFOAMDetector(FeatureDetector):
    """
    Detector for OpenFOAM-specific macros and patterns, with focus on the
    Runtime Selection Table (RTS) mechanism.
    
    This detector identifies and analyzes the following OpenFOAM components:
    1. declareRunTimeSelectionTable - The core RTS macro defining polymorphic tables
    2. TypeName/ClassName - Type registration macros that provide runtime type info
    3. defineTypeNameAndDebug - Type registration with debugging support
    4. addToRunTimeSelectionTable - Registration of derived classes in the RTS
    
    The detector tracks whether classes have complete or partial RTS implementation
    and stores detailed information about the RTS configuration.
    """
    
    # Define custom entity fields for OpenFOAM RTS and related information
    entity_fields = {
        "openfoam_rts_status": {
            "type": "TEXT",
            "description": "Status of RTS implementation: 'complete', 'partial', or 'none'"
        },
        "openfoam_rts_missing": {
            "type": "TEXT",
            "description": "Comma-separated list of missing RTS components"
        },
        "openfoam_rts_count": {
            "type": "INTEGER",
            "description": "Number of RTS tables defined in the class"
        },
        # Fields for all tables using pipe-delimited concatenation
        "openfoam_rts_names": {
            "type": "TEXT",
            "description": "Pipe-delimited list of all RTS table names"
        },
        "openfoam_rts_types": {
            "type": "TEXT",
            "description": "Pipe-delimited list of all RTS pointer types"
        },
        "openfoam_rts_constructor_params": {
            "type": "TEXT",
            "description": "Pipe-delimited list of all RTS constructor parameters"
        },
        "openfoam_rts_selector_params": {
            "type": "TEXT",
            "description": "Pipe-delimited list of all RTS selector parameters"
        },
        "openfoam_class_role": {
            "type": "TEXT",
            "description": "Role of the class in the RTS hierarchy: 'base', 'derived', or 'unknown'"
        },
        # Other OpenFOAM fields
        "openfoam_type_name": {
            "type": "TEXT",
            "description": "The TypeName string used for the class"
        },
        "openfoam_parent_class": {
            "type": "TEXT",
            "description": "Parent class with which this class is registered"
        },
        "openfoam_registration_name": {
            "type": "TEXT",
            "description": "Name used for registration in the RTS system"
        },
        "openfoam_debug_flag": {
            "type": "INTEGER",
            "description": "Debug flag value from defineTypeNameAndDebug"
        }
    }
    
    def __init__(self):
        super().__init__("openfoam", "DSL", "OpenFOAM Framework Features")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        """
        Detect OpenFOAM macros in class declarations, focusing on RTS mechanism
        """
        if cursor.kind not in [CursorKind.CLASS_DECL, CursorKind.STRUCT_DECL, CursorKind.CLASS_TEMPLATE]:
            return False
        openfoam_keywords = [
            'declareRunTimeSelectionTable',
            'TypeName',
            'ClassName',
            'addToRunTimeSelectionTable'
        ]
        
        if not any(keyword in token_str for keyword in openfoam_keywords):
            return False
            
        is_base_class = 'declareRunTimeSelectionTable' in token_str
        is_derived_class = 'addToRunTimeSelectionTable' in token_str
        if is_base_class:
            rts_components = {
                'declareRunTimeSelectionTable': False,  # Must have this declaration
                'typeName': False,  # Must have TypeName or ClassName
            }
        else:
            rts_components = {
                'typeName': False,  # Must have TypeName or ClassName
                'addToRunTimeSelectionTable': False  # Must have this to register with parent
            }
        
        fields = {
            'openfoam_rts_status': 'none',
            'openfoam_rts_missing': []
        }
        rts_tables = []
        # TODO: VERY scary regular expression. Maybe opt for tree-sitter here?
        rts_pattern = r'declareRunTimeSelectionTable\s*\(\s*([^,]+),\s*([^,]+),\s*([^,)\s]+)\s*(?:,\s*\(([^)]*)\))?\s*(?:,\s*\(([^)]*)\))?\s*\)'
        if is_base_class and 'declareRunTimeSelectionTable' in rts_components:
            rts_components['declareRunTimeSelectionTable'] = 'declareRunTimeSelectionTable' in token_str
        
        for match in re.finditer(rts_pattern, token_str):
            rts_components['declareRunTimeSelectionTable'] = True
            pointer_type = match.group(1).strip()
            class_name = match.group(2).strip()
            rts_name = match.group(3).strip()
            ctor_decl_params = match.group(4).strip() if match.group(4) else ""
            ctor_params = match.group(5).strip() if match.group(5) else ""
            
            rts_tables.append({
                "pointer_type": pointer_type,
                "class_name": class_name,
                "rts_name": rts_name,
                "ctor_decl_params": ctor_decl_params,
                "ctor_params": ctor_params
            })
        
        if rts_tables:
            fields['openfoam_rts_count'] = len(rts_tables)
            fields.update({
                'openfoam_rts_names': '|'.join(table['rts_name'] for table in rts_tables),
                'openfoam_rts_types': '|'.join(table['pointer_type'] for table in rts_tables),
                'openfoam_rts_constructor_params': '|'.join(table['ctor_decl_params'] for table in rts_tables),
                'openfoam_rts_selector_params': '|'.join(table['ctor_params'] for table in rts_tables)
            })
            fields['openfoam_rts_status'] = 'partial'
            
        typename_pattern = r'TypeName\s*\(\s*"([^"]*)"\s*\)'
        classname_pattern = r'ClassName\s*\(\s*"([^"]*)"\s*\)'
        typename_match = re.search(typename_pattern, token_str)
        classname_match = re.search(classname_pattern, token_str)
        
        if typename_match or classname_match:
            rts_components['typeName'] = True
            type_name = (typename_match.group(1) if typename_match else 
                         classname_match.group(1) if classname_match else None)
            if type_name:
                fields['openfoam_type_name'] = type_name
        
        type_debug_pattern = r'defineTypeNameAndDebug\s*\(\s*([^,]+),\s*(\d+)\s*\)'
        type_debug_match = re.search(type_debug_pattern, token_str)
        if type_debug_match:
            class_name = type_debug_match.group(1).strip()
            debug_flag = int(type_debug_match.group(2))
            if 'openfoam_type_name' not in fields:
                fields['openfoam_type_name'] = class_name
            fields['openfoam_debug_flag'] = debug_flag
        
        # TODO: Another scary regular expression, should really parse properly
        add_pattern = r'addToRunTimeSelectionTable\s*\(\s*([^,]+),\s*([^,]+),\s*([^,)]+)'
        add_match = re.search(add_pattern, token_str)
        
        if add_match:
            if 'addToRunTimeSelectionTable' in rts_components:
                rts_components['addToRunTimeSelectionTable'] = True
            parent_class = add_match.group(1).strip()
            class_name = add_match.group(2).strip()
            registration_name = add_match.group(3).strip()
            
            fields.update({
                'openfoam_parent_class': parent_class,
                'openfoam_registration_name': registration_name
            })
        
        missing_components = [comp for comp, present in rts_components.items() if not present]
        if not missing_components:
            fields['openfoam_rts_status'] = 'complete'
        else:
            fields['openfoam_rts_status'] = 'partial'
            fields['openfoam_rts_missing'] = ','.join(missing_components)
            
        if is_base_class and not is_derived_class:
            if not rts_components.get('declareRunTimeSelectionTable', False):
                return False
        elif is_derived_class:
            if not rts_components.get('addToRunTimeSelectionTable', False):
                return False
        class_name = cursor.spelling
        if re.fullmatch(r'add.*ConstructorToTable', class_name):
            return False
            
        if (is_base_class and rts_components.get('declareRunTimeSelectionTable', False)) or \
           (is_derived_class and rts_components.get('addToRunTimeSelectionTable', False)) or \
           any(rts_components.values()):
            fields['openfoam_class_role'] = 'base' if is_base_class else 'derived' if is_derived_class else 'unknown'
            return {
                'detected': True,
                'fields': fields 
            }
            
        return False
