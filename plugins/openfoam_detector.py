#!/usr/bin/env python3

import re
from clang.cindex import CursorKind
from feature_detectors import FeatureDetector

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
            "type": "JSON",
            "description": "List of missing RTS components"
        },
        "openfoam_rts_type": {
            "type": "TEXT",
            "description": "Type of pointer used in RTS (e.g., autoPtr, Ptr)"
        },
        "openfoam_rts_name": {
            "type": "TEXT",
            "description": "Name of the RTS table"
        },
        "openfoam_rts_constructor_params": {
            "type": "TEXT",
            "description": "Constructor parameters for the RTS"
        },
        "openfoam_rts_selector_params": {
            "type": "TEXT", 
            "description": "Parameters used to select from the RTS"
        },
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
        # Only process class, struct, and template class declarations
        if cursor.kind not in [CursorKind.CLASS_DECL, CursorKind.STRUCT_DECL, CursorKind.CLASS_TEMPLATE]:
            return False
            
        # Quick check if any OpenFOAM-specific macros are present
        openfoam_keywords = [
            'declareRunTimeSelectionTable',
            'defineTypeNameAndDebug',
            'TypeName',
            'ClassName',
            'addToRunTimeSelectionTable'
        ]
        
        if not any(keyword in token_str for keyword in openfoam_keywords):
            return False
            
        # Track components needed for complete RTS implementation
        rts_components = {
            'declareRunTimeSelectionTable': False,
            'defineTypeNameAndDebug': False,
            'typeName': False,  # Either through TypeName or ClassName
            'addToRunTimeSelectionTable': False
        }
        
        # Initialize result fields
        fields = {
            'openfoam_rts_status': 'none',
            'openfoam_rts_missing': []
        }
        
        # Detect declareRunTimeSelectionTable
        rts_tables = []
        rts_pattern = r'declareRunTimeSelectionTable\s*\(\s*([^,]+),\s*([^,]+),\s*([^,)]+)(?:,\s*\(([^)]*)\))(?:,\s*\(([^)]*)\))'
        
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
        
        # Store RTS table info if found
        if rts_tables:
            primary_rts = rts_tables[0]
            fields.update({
                'openfoam_rts_type': primary_rts['pointer_type'],
                'openfoam_rts_name': primary_rts['rts_name'],
                'openfoam_rts_constructor_params': primary_rts['ctor_decl_params'],
                'openfoam_rts_selector_params': primary_rts['ctor_params']
            })
            
        # Detect TypeName and ClassName
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
        
        # Detect defineTypeNameAndDebug
        type_debug_pattern = r'defineTypeNameAndDebug\s*\(\s*([^,]+),\s*(\d+)\s*\)'
        type_debug_match = re.search(type_debug_pattern, token_str)
        
        if type_debug_match:
            rts_components['defineTypeNameAndDebug'] = True
            class_name = type_debug_match.group(1).strip()
            debug_flag = int(type_debug_match.group(2))
            
            # Only update if not set by TypeName/ClassName
            if 'openfoam_type_name' not in fields:
                fields['openfoam_type_name'] = class_name
                
            fields['openfoam_debug_flag'] = debug_flag
        
        # Detect addToRunTimeSelectionTable
        add_pattern = r'addToRunTimeSelectionTable\s*\(\s*([^,]+),\s*([^,]+),\s*([^,)]+)'
        add_match = re.search(add_pattern, token_str)
        
        if add_match:
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
        elif any(rts_components.values()):
            fields['openfoam_rts_status'] = 'partial'
            fields['openfoam_rts_missing'] = missing_components
        if any(rts_components.values()):
            return {
                'detected': True,
                'fields': fields 
            }
            
        return False
