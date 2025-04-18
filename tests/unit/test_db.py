#!/usr/bin/env python3

import unittest
import sys
import os
import tempfile
import uuid
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent / "src"))
from logs import setup_logging

logger = setup_logging(verbose=True).getChild('test.db')

from db import EntityDatabase

class TestEntityDatabase(unittest.TestCase):
    """Test cases for the EntityDatabase class focusing on entity storage and retrieval"""
    
    def setUp(self):
        """Set up test environment with a temporary database"""
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix='.db')
        logger.info(f"Created temporary database at {self.temp_db_path}")
        self.db = EntityDatabase(self.temp_db_path)
        self.prepare_test_entities()
    
    def tearDown(self):
        """Clean up test environment"""
        self.db.close()
        os.close(self.temp_db_fd)
        os.unlink(self.temp_db_path)
        logger.info(f"Removed temporary database at {self.temp_db_path}")
    
    def prepare_test_entities(self):
        """Prepare test entities with various attributes and relationships"""
        self.class_uuid = str(uuid.uuid4())
        self.method_uuid = str(uuid.uuid4())
        self.field_uuid = str(uuid.uuid4())
        self.base_class_uuid = str(uuid.uuid4())
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

        self.class_entity['children'] = [self.method_entity, self.field_entity]
    
    def test_store_and_retrieve_entity(self):
        """Test storing and retrieving a simple entity"""
        stored_uuid = self.db.store_entity(self.base_class)
        self.assertEqual(stored_uuid, self.base_class_uuid)
        retrieved_entity = self.db.get_entity(self.base_class_uuid)
        self.assertIsNotNone(retrieved_entity)
        self.assertEqual(retrieved_entity['uuid'], self.base_class_uuid)
        self.assertEqual(retrieved_entity['name'], 'BaseClass')
        self.assertEqual(retrieved_entity['kind'], 'CLASS_DECL')
        self.assertEqual(retrieved_entity['file'], self.test_file)
        self.assertEqual(retrieved_entity['line'], 5)
        self.assertEqual(retrieved_entity['access_level'], 'PUBLIC')
        self.assertIn('cpp_features', retrieved_entity)
        self.assertIsInstance(retrieved_entity['cpp_features'], list)
        self.assertIn('classes', retrieved_entity['cpp_features'])
        self.assertIn('inheritance', retrieved_entity['cpp_features'])
    
    def test_store_complex_entity_with_children(self):
        """Test storing and retrieving a complex entity with children"""
        self.db.store_entity(self.base_class)
        stored_uuid = self.db.store_entity(self.class_entity)
        self.assertEqual(stored_uuid, self.class_uuid)
        retrieved_entity = self.db.get_entity(self.class_uuid)
        self.assertIn('children', retrieved_entity)
        self.assertEqual(len(retrieved_entity['children']), 2)
        method_found = False
        field_found = False
        
        for child in retrieved_entity['children']:
            if child['uuid'] == self.method_uuid:
                method_found = True
                self.assertEqual(child['name'], 'testMethod')
                self.assertEqual(child['kind'], 'CXX_METHOD')
            elif child['uuid'] == self.field_uuid:
                field_found = True
                self.assertEqual(child['name'], 'testField')
                self.assertEqual(child['kind'], 'FIELD_DECL')
                self.assertEqual(child['type_info'], 'int')
        
        self.assertTrue(method_found, "Method child was not found")
        self.assertTrue(field_found, "Field child was not found")
    
    def test_store_entity_features(self):
        """Test storing and retrieving entity C++ features"""
        self.db.store_entity(self.class_entity)
        self.db.store_entity(self.method_entity)
        retrieved_entity = self.db.get_entity(self.method_uuid)
        self.assertIn('cpp_features', retrieved_entity)
        self.assertIn('final_override', retrieved_entity['cpp_features'])
    
    def test_method_classification(self):
        """Test storing and retrieving method classification"""
        self.db.store_entity(self.class_entity)
        self.db.store_entity(self.method_entity)
        self.db.cursor.execute(
            "SELECT is_virtual, is_override, is_final FROM method_classification WHERE entity_uuid = ?",
            (self.method_uuid,)
        )
        result = self.db.cursor.fetchone()
        self.assertIsNotNone(result)
        self.assertEqual(result[0], 1)  # is_virtual == True (stored as 1)
        self.assertEqual(result[1], 1)  # is_override == True (stored as 1)
        self.assertEqual(result[2], 1)  # is_final == True (stored as 1)
    
    def test_parsed_documentation(self):
        """Test storing and retrieving parsed documentation"""
        self.db.store_entity(self.class_entity)
        self.db.cursor.execute(
            "SELECT description, returns FROM parsed_docs WHERE entity_uuid = ?",
            (self.class_uuid,)
        )
        doc_result = self.db.cursor.fetchone()
        self.assertIsNotNone(doc_result)
        self.assertEqual(doc_result[0], 'TestClass documentation')
        self.assertEqual(doc_result[1], 'Return value description')
        self.db.cursor.execute(
            "SELECT param_name, description FROM doc_parameters WHERE entity_uuid = ?",
            (self.class_uuid,)
        )
        param_results = self.db.cursor.fetchall()
        self.assertEqual(len(param_results), 2)
        params = {row[0]: row[1] for row in param_results}
        self.assertEqual(params['param1'], 'First parameter')
        self.assertEqual(params['param2'], 'Second parameter')
        self.db.cursor.execute(
            "SELECT description FROM doc_throws WHERE entity_uuid = ?",
            (self.class_uuid,)
        )
        throws_result = self.db.cursor.fetchone()
        self.assertIsNotNone(throws_result)
        self.assertEqual(throws_result[0], 'std::exception')
    
    def test_inheritance_relationships(self):
        """Test storing and retrieving inheritance relationships"""
        self.db.store_entity(self.base_class)
        self.db.store_entity(self.class_entity)
        self.db.cursor.execute(
            "SELECT base_uuid, base_name, access_level FROM inheritance WHERE class_uuid = ?",
            (self.class_uuid,)
        )
        inheritance_result = self.db.cursor.fetchone()
        self.assertIsNotNone(inheritance_result)
        self.assertEqual(inheritance_result[0], self.base_class_uuid)
        self.assertEqual(inheritance_result[1], 'BaseClass')
        self.assertEqual(inheritance_result[2], 'PUBLIC')

if __name__ == '__main__':
    unittest.main()
