#!/usr/bin/env python3

import re
from foamcd.feature_detectors import FeatureDetector

class OpenMPDetector(FeatureDetector):
    """Detector for OpenMP parallel programming model directives
    
    Detects pragma-based OpenMP directives in C++ code and extracts metadata
    about parallelism type, thread counts, and clause information.
    """
    
    # Define custom entity fields that will be stored in the database
    entity_fields = {
        "openmp_parallelism_type": {
            "type": "TEXT",
            "description": "Type of OpenMP parallelism (for, sections, task, etc.)"
        },
        "openmp_num_threads": {
            "type": "INTEGER",
            "description": "Number of threads specified in OpenMP directive"
        },
        "openmp_clause_info": {
            "type": "JSON",
            "description": "JSON object containing information about OpenMP clauses"
        }
    }
    
    def __init__(self):
        super().__init__("openmp", "DSL", "OpenMP parallel programming directives")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        # Quick check for OpenMP pragmas
        if '#pragma omp' not in token_str:
            return False
            
        # Extract more detailed info
        parallelism_type = None
        num_threads = None
        clause_info = {}
        
        # Detect parallelism type
        if 'parallel for' in token_str:
            parallelism_type = "parallel_for"
        elif 'parallel sections' in token_str:
            parallelism_type = "parallel_sections"
        elif 'task' in token_str:
            parallelism_type = "task"
        elif 'parallel' in token_str:
            parallelism_type = "parallel"
        elif 'simd' in token_str:
            parallelism_type = "simd"
        elif 'for' in token_str:
            parallelism_type = "for"
        elif 'sections' in token_str:
            parallelism_type = "sections"
            
        # Extract thread count
        thread_match = re.search(r'num_threads\s*\(\s*(\d+)\s*\)', token_str)
        if thread_match:
            num_threads = int(thread_match.group(1))
            
        # Extract scheduling
        if 'schedule' in token_str:
            sched_match = re.search(r'schedule\s*\(\s*([^,\)]+)(?:,\s*(\d+))?\s*\)', token_str)
            if sched_match:
                schedule_type = sched_match.group(1)
                chunk_size = sched_match.group(2)
                clause_info['schedule'] = {
                    'type': schedule_type,
                    'chunk_size': int(chunk_size) if chunk_size else None
                }
                
        # Check for reduction operations
        if 'reduction' in token_str:
            red_match = re.search(r'reduction\s*\(\s*([^\)]+)\s*\)', token_str)
            if red_match:
                reduction_spec = red_match.group(1)
                parts = reduction_spec.split(':')
                if len(parts) == 2:
                    clause_info['reduction'] = {
                        'operator': parts[0].strip(),
                        'variables': [v.strip() for v in parts[1].split(',')]
                    }
        
        # Check for data sharing clauses
        for clause in ['shared', 'private', 'firstprivate', 'lastprivate']:
            if clause in token_str:
                clause_match = re.search(r'%s\s*\(\s*([^\)]+)\s*\)' % clause, token_str)
                if clause_match:
                    variables = [v.strip() for v in clause_match.group(1).split(',')]
                    clause_info[clause] = variables
        
        return {
            'detected': True,
            'fields': {
                'openmp_parallelism_type': parallelism_type,
                'openmp_num_threads': num_threads,
                'openmp_clause_info': clause_info
            }
        }
