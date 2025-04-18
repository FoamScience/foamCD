#!/usr/bin/env python3

import unittest
import sys
import os
import tempfile
import uuid
from pathlib import Path

# Add src directory to Python path for imports
sys.path.append(str(Path(__file__).parent.parent.parent / "src"))

# Import logs module for consistent logger setup
from logs import setup_logging

# Configure logger for database tests
logger = setup_logging(verbose=True).getChild('test.db')

from db import EntityDatabase
from entity import Entity
from clang.cindex import CursorKind, AccessSpecifier

class TestEntityDatabase(unittest.TestCase):
    """Test cases for the EntityDatabase class focusing on entity storage and retrieval"""
    
    def setUp(self):
        """Set up test environment with a temporary database"""
        # Create a temporary database file
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix='.db')
        logger.info(f"Created temporary database at {self.temp_db_path}")
        
        # Initialize database
        self.db = EntityDatabase(self.temp_db_path)
        
        # Create sample entities for testing
        self.prepare_test_entities()
    
    def tearDown(self):
        """Clean up test environment"""
        # Close database connection
        self.db.close()
        
        # Close and remove temporary database file
        os.close(self.temp_db_fd)
        os.unlink(self.temp_db_path)
        logger.info(f"Removed temporary database at {self.temp_db_path}")
    
    def prepare_test_entities(self):
        """Prepare test entities with various attributes and relationships"""
        # Generate unique UUIDs for our entities
        self.class_uuid = str(uuid.uuid4())
        self.method_uuid = str(uuid.uuid4())
        self.field_uuid = str(uuid.uuid4())
        self.base_class_uuid = str(uuid.uuid4())
        
        # Create test file path
        self.test_file = "/home/test/example.cpp"
        
        # Base class with features
        self.base_class = {
            'uuid': self.base_class_uuid,
            'name': 'BaseClass',
            'kind': 'CLASS_DECL',
            'file': self.test_file,
            'line': 5,
            'column': 1,
            'documentation': '/** BaseClass documentation */',
            'access': 'PUBLIC',
            'cpp_features': ['classes', 'inheritance'],
            'class_info': {
                'is_abstract': True,
                'is_final': False
            },
            'children': []
        }
        
        # Class with inheritance, features, and classification
        self.class_entity = {
            'uuid': self.class_uuid,
            'name': 'TestClass',
            'kind': 'CLASS_DECL',
            'file': self.test_file,
            'line': 20,
            'column': 1,
            'documentation': '/** TestClass documentation with @param and @return tags */',
            'access': 'PUBLIC',
            'cpp_features': ['classes', 'inheritance', 'final_override'],
            'class_info': {
                'is_abstract': False,
                'is_final': True
            },
            'base_classes': [
                {
                    'uuid': self.base_class_uuid,
                    'name': 'BaseClass',
                    'access': 'PUBLIC',
                    'virtual': False
                }
            ],
            'parsed_doc': {
                'description': 'TestClass documentation',
                'params': {
                    'param1': 'First parameter',
                    'param2': 'Second parameter'
                },
                'returns': 'Return value description',
                'throws': ['std::exception'],
                'see': ['BaseClass'],
                'tags': {
                    'example': ['Example usage code'],
                    'note': ['Important note about usage']
                }
            },
            'children': []
        }
        
        # Method with features and method classification
        self.method_entity = {
            'uuid': self.method_uuid,
            'name': 'testMethod',
            'kind': 'CXX_METHOD',
            'file': self.test_file,
            'line': 25,
            'column': 5,
            'documentation': '/** Method documentation */',
            'access': 'PUBLIC',
            'parent_uuid': self.class_uuid,
            'cpp_features': ['final_override'],
            'method_info': {
                'is_virtual': True,
                'is_pure_virtual': False,
                'is_override': True,
                'is_final': True,
                'is_defaulted': False,
                'is_deleted': False
            }
        }
        
        # Field entity
        self.field_entity = {
            'uuid': self.field_uuid,
            'name': 'testField',
            'kind': 'FIELD_DECL',
            'file': self.test_file,
            'line': 22,
            'column': 5,
            'documentation': '/** Field documentation */',
            'access': 'PRIVATE',
            'parent_uuid': self.class_uuid,
            'type_info': 'int'
        }
        
        # Add children to class entity
        self.class_entity['children'] = [self.method_entity, self.field_entity]
    
    def test_store_and_retrieve_entity(self):
        """Test storing and retrieving a simple entity"""
        # Store the base class entity
        stored_uuid = self.db.store_entity(self.base_class)
        
        # Verify the UUID matches
        self.assertEqual(stored_uuid, self.base_class_uuid)
        
        # Retrieve the entity
        retrieved_entity = self.db.get_entity(self.base_class_uuid)
        
        # Verify basic properties
        self.assertIsNotNone(retrieved_entity)
        self.assertEqual(retrieved_entity['uuid'], self.base_class_uuid)
        self.assertEqual(retrieved_entity['name'], 'BaseClass')
        self.assertEqual(retrieved_entity['kind'], 'CLASS_DECL')
        self.assertEqual(retrieved_entity['file'], self.test_file)
        self.assertEqual(retrieved_entity['line'], 5)
        self.assertEqual(retrieved_entity['access_level'], 'PUBLIC')
        
        # Verify features were stored and retrieved
        self.assertIn('cpp_features', retrieved_entity)
        self.assertIsInstance(retrieved_entity['cpp_features'], list)
        self.assertIn('classes', retrieved_entity['cpp_features'])
        self.assertIn('inheritance', retrieved_entity['cpp_features'])
    
    def test_store_complex_entity_with_children(self):
        """Test storing and retrieving a complex entity with children"""
        # First store the base class
        self.db.store_entity(self.base_class)
        
        # Store the class entity which has children
        stored_uuid = self.db.store_entity(self.class_entity)
        
        # Verify UUID
        self.assertEqual(stored_uuid, self.class_uuid)
        
        # Retrieve the entity with children
        retrieved_entity = self.db.get_entity(self.class_uuid)
        
        # Verify it has children
        self.assertIn('children', retrieved_entity)
        self.assertEqual(len(retrieved_entity['children']), 2)
        
        # Find the method and field in the children
        method_found = False
        field_found = False
        
        for child in retrieved_entity['children']:
            if child['uuid'] == self.method_uuid:
                method_found = True
                # Verify method properties
                self.assertEqual(child['name'], 'testMethod')
                self.assertEqual(child['kind'], 'CXX_METHOD')
            elif child['uuid'] == self.field_uuid:
                field_found = True
                # Verify field properties
                self.assertEqual(child['name'], 'testField')
                self.assertEqual(child['kind'], 'FIELD_DECL')
                self.assertEqual(child['type_info'], 'int')
        
        # Verify both children were found
        self.assertTrue(method_found, "Method child was not found")
        self.assertTrue(field_found, "Field child was not found")
    
    def test_store_entity_features(self):
        """Test storing and retrieving entity C++ features"""
        # First store the parent class entity to satisfy foreign key constraints
        self.db.store_entity(self.class_entity)
        
        # Then store the method entity which has features
        self.db.store_entity(self.method_entity)
        
        # Retrieve the entity
        retrieved_entity = self.db.get_entity(self.method_uuid)
        
        # Verify features
        self.assertIn('cpp_features', retrieved_entity)
        self.assertIn('final_override', retrieved_entity['cpp_features'])
    
    def test_method_classification(self):
        """Test storing and retrieving method classification"""
        # First store the parent class entity to satisfy foreign key constraints
        self.db.store_entity(self.class_entity)
        
        # Then store the method entity
        self.db.store_entity(self.method_entity)
        
        # Use a direct SQL query to verify method classification storage
        self.db.cursor.execute(
            "SELECT is_virtual, is_override, is_final FROM method_classification WHERE entity_uuid = ?",
            (self.method_uuid,)
        )
        result = self.db.cursor.fetchone()
        
        # Verify method classification was stored correctly
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 1)  # is_virtual == True (stored as 1)
        self.assertEqual(result[1], 1)  # is_override == True (stored as 1)
        self.assertEqual(result[2], 1)  # is_final == True (stored as 1)
    
    def test_parsed_documentation(self):
        """Test storing and retrieving parsed documentation"""
        # Store the class entity which has parsed documentation
        self.db.store_entity(self.class_entity)
        
        # Query parsed docs table
        self.db.cursor.execute(
            "SELECT description, returns FROM parsed_docs WHERE entity_uuid = ?",
            (self.class_uuid,)
        )
        doc_result = self.db.cursor.fetchone()
        
        # Verify documentation was stored
        self.assertIsNotNone(doc_result)
        self.assertEqual(doc_result[0], 'TestClass documentation')
        self.assertEqual(doc_result[1], 'Return value description')
        
        # Query parameters
        self.db.cursor.execute(
            "SELECT param_name, description FROM doc_parameters WHERE entity_uuid = ?",
            (self.class_uuid,)
        )
        param_results = self.db.cursor.fetchall()
        
        # Verify parameters were stored
        self.assertEqual(len(param_results), 2)
        
        # Build a dictionary of parameters for easier assertion
        params = {row[0]: row[1] for row in param_results}
        self.assertEqual(params['param1'], 'First parameter')
        self.assertEqual(params['param2'], 'Second parameter')
        
        # Query throws
        self.db.cursor.execute(
            "SELECT description FROM doc_throws WHERE entity_uuid = ?",
            (self.class_uuid,)
        )
        throws_result = self.db.cursor.fetchone()
        
        # Verify throws were stored
        self.assertIsNotNone(throws_result)
        self.assertEqual(throws_result[0], 'std::exception')
    
    def test_inheritance_relationships(self):
        """Test storing and retrieving inheritance relationships"""
        # Store both classes
        self.db.store_entity(self.base_class)
        self.db.store_entity(self.class_entity)
        
        # Query inheritance table
        self.db.cursor.execute(
            "SELECT base_uuid, base_name, access_level FROM inheritance WHERE class_uuid = ?",
            (self.class_uuid,)
        )
        inheritance_result = self.db.cursor.fetchone()
        
        # Verify inheritance relationship was stored
        self.assertIsNotNone(inheritance_result)
        self.assertEqual(inheritance_result[0], self.base_class_uuid)
        self.assertEqual(inheritance_result[1], 'BaseClass')
        self.assertEqual(inheritance_result[2], 'PUBLIC')

if __name__ == '__main__':
    unittest.main()
