#!/usr/bin/env python3

import unittest
import sys
import os
import tempfile
import uuid
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent / "src"))
from foamcd.logs import setup_logging

logger = setup_logging(verbose=True).getChild('test.decl_def_links')

from foamcd.db import EntityDatabase

class TestDeclarationDefinitionLinks(unittest.TestCase):
    """Test cases for declaration-definition linking functionality"""
    
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
        """Prepare test entities for declaration and definition linking tests"""
        # Create file paths
        self.header_file = "/home/test/example.h"
        self.impl_file = "/home/test/example.cpp"
        
        # Create class declaration (in header)
        self.class_decl_uuid = str(uuid.uuid4())
        self.class_decl = {
            'uuid': self.class_decl_uuid,
            'name': 'TestClass',
            'kind': 'CLASS_DECL',
            'file': self.header_file,
            'line': 10,
            'column': 1,
            'end_line': 20,
            'end_column': 1,
            'documentation': '/** TestClass declaration */',
            'access': 'PUBLIC',
            'cpp_features': ['classes'],
            'parent_uuid': None
        }
        
        # Create method declaration (in header)
        self.method_decl_uuid = str(uuid.uuid4())
        self.method_decl = {
            'uuid': self.method_decl_uuid,
            'name': 'testMethod',
            'kind': 'CXX_METHOD',
            'file': self.header_file,
            'line': 15,
            'column': 3,
            'end_line': 15,
            'end_column': 50,
            'documentation': '/** testMethod declaration */',
            'access': 'PUBLIC',
            'cpp_features': ['methods'],
            'parent_uuid': self.class_decl_uuid
        }
        
        # Create function declaration (in header)
        self.function_decl_uuid = str(uuid.uuid4())
        self.function_decl = {
            'uuid': self.function_decl_uuid,
            'name': 'testFunction',
            'kind': 'FUNCTION_DECL',
            'file': self.header_file,
            'line': 30,
            'column': 1,
            'end_line': 30,
            'end_column': 50,
            'documentation': '/** testFunction declaration */',
            'access': None,
            'cpp_features': ['functions'],
            'parent_uuid': None
        }
        
        # Create method definition (in impl file)
        self.method_def_uuid = str(uuid.uuid4())
        self.method_def = {
            'uuid': self.method_def_uuid,
            'name': 'testMethod',
            'kind': 'CXX_METHOD',
            'file': self.impl_file,
            'line': 25,
            'column': 1,
            'end_line': 28,
            'end_column': 1,
            'documentation': '',
            'access': 'PUBLIC',
            'cpp_features': ['methods'],
            'parent_uuid': self.class_decl_uuid
        }
        
        # Create function definition (in impl file)
        self.function_def_uuid = str(uuid.uuid4())
        self.function_def = {
            'uuid': self.function_def_uuid,
            'name': 'testFunction',
            'kind': 'FUNCTION_DECL',
            'file': self.impl_file,
            'line': 40,
            'column': 1,
            'end_line': 45,
            'end_column': 1,
            'documentation': '',
            'access': None,
            'cpp_features': ['functions'],
            'parent_uuid': None
        }
        
        # Store all entities in the database
        for entity in [
            self.class_decl, self.method_decl, self.function_decl,
            self.method_def, self.function_def
        ]:
            self.db.store_entity(entity)
    
    def test_link_declaration_definition(self):
        """Test linking declarations to definitions"""
        # Link method declaration to definition
        result = self.db.link_declaration_definition(
            self.method_decl_uuid, self.method_def_uuid
        )
        self.assertTrue(result, "Method declaration-definition linking should succeed")
        
        # Link function declaration to definition
        result = self.db.link_declaration_definition(
            self.function_decl_uuid, self.function_def_uuid
        )
        self.assertTrue(result, "Function declaration-definition linking should succeed")
        
        # Verify links in database
        self.db.cursor.execute(
            "SELECT COUNT(*) FROM decl_def_links WHERE decl_uuid = ? AND def_uuid = ?",
            (self.method_decl_uuid, self.method_def_uuid)
        )
        count = self.db.cursor.fetchone()[0]
        self.assertEqual(count, 1, "Method declaration-definition link should exist")
        
        self.db.cursor.execute(
            "SELECT COUNT(*) FROM decl_def_links WHERE decl_uuid = ? AND def_uuid = ?",
            (self.function_decl_uuid, self.function_def_uuid)
        )
        count = self.db.cursor.fetchone()[0]
        self.assertEqual(count, 1, "Function declaration-definition link should exist")

    def test_get_entity_definitions(self):
        """Test retrieving definitions for a declaration"""
        # Link method and function declarations to definitions
        self.db.link_declaration_definition(
            self.method_decl_uuid, self.method_def_uuid
        )
        self.db.link_declaration_definition(
            self.function_decl_uuid, self.function_def_uuid
        )
        
        # Get definitions for method declaration
        definitions = self.db.get_entity_definitions(self.method_decl_uuid)
        self.assertEqual(len(definitions), 1, "Should find one definition for method")
        self.assertEqual(definitions[0].get('uuid'), self.method_def_uuid)
        self.assertEqual(definitions[0].get('file'), self.impl_file)
        
        # Get definitions for function declaration
        definitions = self.db.get_entity_definitions(self.function_decl_uuid)
        self.assertEqual(len(definitions), 1, "Should find one definition for function")
        self.assertEqual(definitions[0].get('uuid'), self.function_def_uuid)
        self.assertEqual(definitions[0].get('file'), self.impl_file)
        
        # Get definitions for class without definitions
        definitions = self.db.get_entity_definitions(self.class_decl_uuid)
        self.assertEqual(len(definitions), 0, "Should find no definitions for class")
    
    def test_get_entity_declaration(self):
        """Test retrieving declaration for a definition"""
        # Link method and function declarations to definitions
        self.db.link_declaration_definition(
            self.method_decl_uuid, self.method_def_uuid
        )
        self.db.link_declaration_definition(
            self.function_decl_uuid, self.function_def_uuid
        )
        
        # Get declaration for method definition
        declaration = self.db.get_entity_declaration(self.method_def_uuid)
        self.assertIsNotNone(declaration, "Should find declaration for method definition")
        self.assertEqual(declaration.get('uuid'), self.method_decl_uuid)
        self.assertEqual(declaration.get('file'), self.header_file)
        
        # Get declaration for function definition
        declaration = self.db.get_entity_declaration(self.function_def_uuid)
        self.assertIsNotNone(declaration, "Should find declaration for function definition")
        self.assertEqual(declaration.get('uuid'), self.function_decl_uuid)
        self.assertEqual(declaration.get('file'), self.header_file)
    
    def test_get_definition_files(self):
        """Test retrieving all definition files for a class"""
        # Link method declaration to definition
        self.db.link_declaration_definition(
            self.method_decl_uuid, self.method_def_uuid
        )
        
        # Test getting definition files for the class
        definition_files = self.db._get_definition_files(self.class_decl_uuid)
        self.assertIn(self.impl_file, definition_files, 
                      "Implementation file should be in definition files")
        
        # Verify no duplicates
        self.assertEqual(len(definition_files), len(set(definition_files)),
                         "Definition files should contain no duplicates")

    def test_class_stats_with_definitions(self):
        """Test that get_class_stats includes definition files"""
        # Link method declaration to definition
        self.db.link_declaration_definition(
            self.method_decl_uuid, self.method_def_uuid
        )
        
        # Get class stats
        class_stats = self.db.get_class_stats()
        
        # Find our test class
        test_class = None
        for class_info in class_stats:
            if class_info.get('name') == 'TestClass':
                test_class = class_info
                break
                
        self.assertIsNotNone(test_class, "TestClass should be in class stats")
        self.assertIn('definition_files', test_class, 
                      "Class stats should include definition_files")
        self.assertIn(self.impl_file, test_class['definition_files'],
                     "Implementation file should be in definition_files")

if __name__ == '__main__':
    unittest.main()
