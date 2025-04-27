#!/usr/bin/env python3

import re
from foamcd.feature_detectors import FeatureDetector

class OpenACCDetector(FeatureDetector):
    """Detector for OpenACC GPU programming directives"""
    
    entity_fields = {
        "openacc_construct_type": {
            "type": "TEXT",
            "description": "Type of OpenACC construct (parallel, kernels, data, etc.)"
        },
        "openacc_gang_workers": {
            "type": "INTEGER",
            "description": "Number of gang workers specified"
        },
        "openacc_vector_length": {
            "type": "INTEGER",
            "description": "Vector length specified in directive"
        }
    }
    
    def __init__(self):
        super().__init__("openacc", "DSL", "OpenACC GPU programming directives")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if '#pragma acc' not in token_str:
            return False
            
        construct_type = None
        gang_workers = None
        vector_length = None
        
        # Detect construct type
        if 'parallel' in token_str:
            construct_type = "parallel"
        elif 'kernels' in token_str:
            construct_type = "kernels"
        elif 'data' in token_str:
            construct_type = "data"
        elif 'loop' in token_str:
            construct_type = "loop"
        elif 'update' in token_str:
            construct_type = "update"
        
        # Extract gang workers
        gang_match = re.search(r'gang\s*\(\s*(\d+)\s*\)', token_str)
        if gang_match:
            gang_workers = int(gang_match.group(1))
            
        # Extract vector length
        vector_match = re.search(r'vector\s*\(\s*(\d+)\s*\)', token_str)
        if vector_match:
            vector_length = int(vector_match.group(1))
        
        return {
            'detected': True,
            'fields': {
                'openacc_construct_type': construct_type,
                'openacc_gang_workers': gang_workers,
                'openacc_vector_length': vector_length
            }
        }
