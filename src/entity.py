#!/usr/bin/env python3

import hashlib
import re
from typing import Dict, List, Optional, Tuple, Set, Any
from clang.cindex import CursorKind, AccessSpecifier

class Entity:
    """Property container for documentable entities"""
    def __init__(self, name: str, kind: CursorKind, location: Tuple[str, int, int, int, int], 
                 doc_comment: str = "", parent: Optional['Entity'] = None):
        self.name = name
        self.kind = kind
        self.file, self.line, self.column, self.end_line, self.end_column = location
        self.doc_comment = doc_comment
        self.parent = parent
        self.children: List[Entity] = []
        self.access = AccessSpecifier.PUBLIC
        self.linkage = None
        self.type_info = None
        self.full_signature = None
        self.cpp_features: Set[str] = set()
        
        # Inheritance tracking
        self.base_classes: List[Dict[str, Any]] = []
        
        # Method classification
        self.is_virtual = False
        self.is_pure_virtual = False
        self.is_override = False
        self.is_final = False
        self.is_abstract = False  # For classes with at least one pure virtual method
        self.is_defaulted = False
        self.is_deleted = False
        
        # External reference flag (for placeholder entities from standard library, etc.)
        self.is_external_reference = False
        
        # Access level grouping for class members
        self._public_members: List[Entity] = []
        self._protected_members: List[Entity] = []
        self._private_members: List[Entity] = []
        
        # Parsed doc comments (maintains markdown format)
        self.parsed_doc = self._parse_doc_comment(doc_comment)
        
        # Custom fields added by DSL feature detectors
        self.custom_fields: Dict[str, Any] = {}
        
        # Generate UUID by hashing entity content
        self.uuid = self._generate_uuid()
    
    def add_child(self, child: 'Entity'):
        self.children.append(child)
        
        # Also add to the appropriate access level group if this is a class/struct
        if self.kind in (CursorKind.CLASS_DECL, CursorKind.STRUCT_DECL, CursorKind.CLASS_TEMPLATE):
            if child.access == AccessSpecifier.PUBLIC:
                self._public_members.append(child)
            elif child.access == AccessSpecifier.PROTECTED:
                self._protected_members.append(child)
            elif child.access == AccessSpecifier.PRIVATE:
                self._private_members.append(child)
    
    def add_base_class(self, base_class: Dict[str, Any]):
        """Add a base class with inheritance information
        
        Args:
            base_class: Dictionary with base class information:
                - name: Name of the base class
                - uuid: UUID of the base class entity if available
                - access: Inheritance access specifier (public, protected, private)
                - virtual: Whether this is virtual inheritance
        """
        self.base_classes.append(base_class)
        
    def _parse_doc_comment(self, doc_comment: str) -> Dict[str, Any]:
        """Parse documentation comment into structured data"""
        # TODO: This will probably be removed. Markdown content in comments will
        #       be gathered and forwarded to db as a single string
        #       maybe with options to skip specific comments
        if not doc_comment:
            return {}
        result = {
            'description': '',
            'params': {},
            'returns': '',
            'throws': [],
            'see': [],
            'deprecated': '',
            'since': '',
            'tags': {}
        }
        lines = doc_comment.split('\n')
        desc_lines = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('@') or line.startswith('\\'):
                break
            desc_lines.append(line)
            i += 1
        result['description'] = '\n'.join(desc_lines).strip()
        
        current_tag = None
        current_content = []
        while i < len(lines):
            line = lines[i].strip()
            i += 1
            tag_match = re.match(r'[@\\](\w+)\s*(.*)', line)
            if tag_match:
                if current_tag and current_content:
                    self._add_tag_to_result(result, current_tag, '\n'.join(current_content).strip())
                current_tag = tag_match.group(1).lower()
                current_content = [tag_match.group(2)] if tag_match.group(2) else []
            elif current_tag:
                current_content.append(line)
        if current_tag and current_content:
            self._add_tag_to_result(result, current_tag, '\n'.join(current_content).strip())
            
        return result
    
    def _add_tag_to_result(self, result: Dict[str, Any], tag: str, content: str):
        """Add parsed tag content to the appropriate place in the result"""
        if tag in ('param', 'parameter', 'arg', 'argument'):
            param_match = re.match(r'(\w+)\s+(.*)', content, re.DOTALL)
            if param_match:
                param_name = param_match.group(1)
                param_desc = param_match.group(2)
                result['params'][param_name] = param_desc
        elif tag in ('return', 'returns'):
            result['returns'] = content
        elif tag in ('throws', 'throw', 'exception'):
            result['throws'].append(content)
        elif tag == 'see':
            result['see'].append(content)
        elif tag == 'deprecated':
            result['deprecated'] = content
        elif tag == 'since':
            result['since'] = content
        else:
            if tag not in result['tags']:
                result['tags'][tag] = []
            result['tags'][tag].append(content)
        
    def _generate_uuid(self) -> str:
        """Generate a UUID by hashing the entity's content"""
        content = (
            f"{self.name}:{self.kind.name}:{self.file}:{self.line}:{self.column}:{self.end_line}:{self.end_column}"
        )
        if self.parent and hasattr(self.parent, 'uuid'):
            content += f":{self.parent.uuid}"
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize entities to Python dictionaries"""
        result = {
            'uuid': self.uuid,
            'name': self.name,
            'kind': self.kind.name if hasattr(self.kind, 'name') else str(self.kind),
            # Include parent_uuid explicitly to ensure parent-child relationships are preserved
            'parent_uuid': self.parent.uuid if self.parent else None,
            'location': {
                'file': self.file,
                'line': self.line,
                'column': self.column,
                'end_line': self.end_line,
                'end_column': self.end_column
            },
            'doc_comment': self.doc_comment,
            'parsed_doc': self.parsed_doc,
            'access': self.access.name if self.access else None,
            'type_info': self.type_info,
            'full_signature': self.full_signature,
            'cpp_features': list(self.cpp_features),
            'is_external_reference': self.is_external_reference,
        }
        if self.base_classes:
            result['base_classes'] = self.base_classes
        if self.kind in (CursorKind.CXX_METHOD, CursorKind.FUNCTION_DECL, CursorKind.FUNCTION_TEMPLATE):
            result['method_info'] = {
                'is_virtual': self.is_virtual,
                'is_pure_virtual': self.is_pure_virtual,
                'is_override': self.is_override,
                'is_final': self.is_final,
                'is_defaulted': self.is_defaulted,
                'is_deleted': self.is_deleted
            }
        if self.kind in (CursorKind.CLASS_DECL, CursorKind.STRUCT_DECL, CursorKind.CLASS_TEMPLATE):
            result['class_info'] = {
                'is_abstract': self.is_abstract,
                'is_final': self.is_final
            }
            result['members'] = {
                'public': [member.to_dict() for member in self._public_members],
                'protected': [member.to_dict() for member in self._protected_members],
                'private': [member.to_dict() for member in self._private_members]
            }
            result['children'] = [child.to_dict() for child in self.children]
        else:
            result['children'] = [child.to_dict() for child in self.children]
            
        # Include any custom fields from DSL feature detectors
        if self.custom_fields:
            result['custom_fields'] = self.custom_fields
            
        return result
