#!/usr/bin/env python3

import unittest
import sys
import os
from pathlib import Path

# Add src directory to Python path for imports
sys.path.append(str(Path(__file__).parent.parent.parent / "src"))

# Import logs module for consistent logger setup
from logs import setup_logging

# Configure logger for entity tests
logger = setup_logging(verbose=True).getChild('test.entity')

from entity import Entity
from clang.cindex import CursorKind, AccessSpecifier

class TestEntity(unittest.TestCase):
    def setUp(self):
        # Create a sample entity for testing
        self.location = ("/path/to/file.cpp", 10, 5)
        self.entity = Entity(
            name="TestClass",
            kind=CursorKind.CLASS_DECL,
            location=self.location,
            doc_comment="Test documentation",
        )
        
        # Create a child entity
        self.child_entity = Entity(
            name="TestMethod",
            kind=CursorKind.CXX_METHOD,
            location=("/path/to/file.cpp", 15, 10),
            doc_comment="Method documentation",
            parent=self.entity
        )
        self.entity.add_child(self.child_entity)

    def test_entity_initialization(self):
        """Test entity initialization and basic properties"""
        self.assertEqual(self.entity.name, "TestClass")
        self.assertEqual(self.entity.kind, CursorKind.CLASS_DECL)
        self.assertEqual(self.entity.file, "/path/to/file.cpp")
        self.assertEqual(self.entity.line, 10)
        self.assertEqual(self.entity.column, 5)
        self.assertEqual(self.entity.doc_comment, "Test documentation")
        self.assertEqual(self.entity.access, AccessSpecifier.PUBLIC)
        self.assertIsNone(self.entity.parent)
        self.assertEqual(len(self.entity.children), 1)

    def test_uuid_generation(self):
        """Test UUID generation for entities"""
        # Ensure UUID is generated
        self.assertIsNotNone(self.entity.uuid)
        self.assertTrue(isinstance(self.entity.uuid, str))
        self.assertEqual(len(self.entity.uuid), 64)  # SHA-256 hex digest is 64 chars
        
        # Two entities with the same properties should have the same UUID
        duplicate_entity = Entity(
            name="TestClass",
            kind=CursorKind.CLASS_DECL,
            location=self.location,
            doc_comment="Test documentation",
        )
        self.assertEqual(self.entity.uuid, duplicate_entity.uuid)
        
        # Entity with different properties should have different UUID
        different_entity = Entity(
            name="DifferentClass",
            kind=CursorKind.CLASS_DECL,
            location=self.location,
            doc_comment="Test documentation",
        )
        self.assertNotEqual(self.entity.uuid, different_entity.uuid)
        
        # Child should have a different UUID
        self.assertNotEqual(self.entity.uuid, self.child_entity.uuid)

    def test_parent_child_relationship(self):
        """Test parent-child relationships"""
        # Test parent reference in child
        self.assertEqual(self.child_entity.parent, self.entity)
        
        # Test child reference in parent
        self.assertEqual(len(self.entity.children), 1)
        self.assertEqual(self.entity.children[0], self.child_entity)

    def test_to_dict(self):
        """Test serialization to dictionary"""
        entity_dict = self.entity.to_dict()
        
        # Check basic properties
        self.assertEqual(entity_dict["uuid"], self.entity.uuid)
        self.assertEqual(entity_dict["name"], "TestClass")
        self.assertEqual(entity_dict["kind"], "CLASS_DECL")
        self.assertEqual(entity_dict["location"]["file"], "/path/to/file.cpp")
        self.assertEqual(entity_dict["location"]["line"], 10)
        self.assertEqual(entity_dict["location"]["column"], 5)
        self.assertEqual(entity_dict["doc_comment"], "Test documentation")
        self.assertEqual(entity_dict["access"], "PUBLIC")
        
        # Check children
        self.assertEqual(len(entity_dict["children"]), 1)
        child_dict = entity_dict["children"][0]
        self.assertEqual(child_dict["uuid"], self.child_entity.uuid)
        self.assertEqual(child_dict["name"], "TestMethod")
        self.assertEqual(child_dict["kind"], "CXX_METHOD")


if __name__ == "__main__":
    unittest.main()
