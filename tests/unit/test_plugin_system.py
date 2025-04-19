#!/usr/bin/env python3

import unittest
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to Python path
sys.path.append(str(Path(__file__).parent.parent.parent / "src"))

from logs import setup_logging
from plugin_system import PluginManager
from feature_detectors import FeatureDetector

logger = setup_logging(verbose=True).getChild('test')

class MockCursor:
    """Mock cursor for testing feature detection"""
    def __init__(self, kind=None, spelling="test", location=None, type_info=None):
        self.kind = kind
        self.spelling = spelling
        self.location = location
        self.type = type_info
        self._children = []
        
    def get_children(self):
        return self._children
        
    def add_child(self, child):
        self._children.append(child)
        return child
        
    def get_tokens(self):
        return []


class TestPluginSystem(unittest.TestCase):
    """Test the plugin system"""
    
    def setUp(self):
        # Create a temporary directory for test plugins
        self.plugin_dir = tempfile.TemporaryDirectory()
        self.plugin_manager = PluginManager([self.plugin_dir.name])
        
    def tearDown(self):
        # Clean up temporary directory
        self.plugin_dir.cleanup()
        
    def test_plugin_manager_initialization(self):
        """Test plugin manager initialization"""
        self.assertEqual(len(self.plugin_manager.detectors), 0)
        self.assertEqual(len(self.plugin_manager.custom_entity_fields), 0)
        self.assertIn(self.plugin_dir.name, self.plugin_manager.plugin_dirs)
        
    def test_plugin_registration(self):
        """Test detector registration"""
        class TestDetector(FeatureDetector):
            def __init__(self):
                super().__init__("test_feature", "TEST", "Test feature")
                
            def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
                return "test" in token_str
                
        detector = TestDetector()
        self.assertTrue(self.plugin_manager.register_detector(detector))
        self.assertEqual(len(self.plugin_manager.detectors), 1)
        self.assertIn("test_feature", self.plugin_manager.detectors)
        
        # Try registering the same detector again - should fail
        self.assertFalse(self.plugin_manager.register_detector(detector))
        
    def test_plugin_detection(self):
        """Test feature detection with a plugin"""
        class TestDetector(FeatureDetector):
            def __init__(self):
                super().__init__("test_feature", "TEST", "Test feature")
                
            def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
                return "test" in token_str
                
        self.plugin_manager.register_detector(TestDetector())
        
        # Test detection with a match
        result = self.plugin_manager.detect_features(
            MockCursor(),
            ["test", "token"],
            "test token",
            []
        )
        self.assertEqual(len(result["features"]), 1)
        self.assertIn("test_feature", result["features"])
        
        # Test detection without a match
        result = self.plugin_manager.detect_features(
            MockCursor(),
            ["no", "match"],
            "no match",
            []
        )
        self.assertEqual(len(result["features"]), 0)
        
    def test_custom_fields_registration(self):
        """Test registration of custom entity fields"""
        class FieldDetector(FeatureDetector):
            entity_fields = {
                "test_field": {
                    "type": "TEXT",
                    "description": "Test field"
                },
                "number_field": {
                    "type": "INTEGER",
                    "description": "Number field"
                }
            }
            
            def __init__(self):
                super().__init__("field_feature", "TEST", "Feature with fields")
                
            def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
                return {"detected": True, "fields": {"test_field": "test value", "number_field": 42}}
                
        detector = FieldDetector()
        self.plugin_manager.register_detector(detector)
        self.plugin_manager.register_custom_entity_fields(detector.name, FieldDetector.entity_fields)
        
        # Check if fields were registered
        self.assertEqual(len(self.plugin_manager.custom_entity_fields), 2)
        self.assertIn("test_field", self.plugin_manager.custom_entity_fields)
        self.assertIn("number_field", self.plugin_manager.custom_entity_fields)
        
        # Check field properties
        self.assertEqual(self.plugin_manager.custom_entity_fields["test_field"]["type"], "TEXT")
        self.assertEqual(self.plugin_manager.custom_entity_fields["number_field"]["type"], "INTEGER")
        self.assertEqual(self.plugin_manager.custom_entity_fields["test_field"]["plugin"], "field_feature")
        
    def test_detect_features_with_custom_fields(self):
        """Test feature detection with custom fields"""
        class FieldDetector(FeatureDetector):
            entity_fields = {
                "test_field": {
                    "type": "TEXT",
                    "description": "Test field"
                },
                "number_field": {
                    "type": "INTEGER",
                    "description": "Number field"
                }
            }
            
            def __init__(self):
                super().__init__("field_feature", "TEST", "Feature with fields")
                
            def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
                if "field" in token_str:
                    return {
                        "detected": True,
                        "fields": {
                            "test_field": "test value",
                            "number_field": 42
                        }
                    }
                return False
                
        self.plugin_manager.register_detector(FieldDetector())
        self.plugin_manager.register_custom_entity_fields("field_feature", FieldDetector.entity_fields)
        
        # Test detection with fields
        result = self.plugin_manager.detect_features(
            MockCursor(),
            ["custom", "field", "test"],
            "custom field test",
            []
        )
        self.assertEqual(len(result["features"]), 1)
        self.assertIn("field_feature", result["features"])
        self.assertEqual(len(result["custom_fields"]), 2)
        self.assertEqual(result["custom_fields"]["test_field"], "test value")
        self.assertEqual(result["custom_fields"]["number_field"], 42)
        
    def test_dynamic_plugin_loading(self):
        """Test loading plugins from Python files"""
        # Create a test plugin file
        plugin_path = os.path.join(self.plugin_dir.name, "test_plugin.py")
        with open(plugin_path, "w") as f:
            f.write("""
from feature_detectors import FeatureDetector

class DynamicTestDetector(FeatureDetector):
    entity_fields = {
        "dynamic_field": {
            "type": "TEXT",
            "description": "Dynamic test field"
        }
    }
    
    def __init__(self):
        super().__init__("dynamic_feature", "TEST", "Dynamically loaded feature")
        
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if "dynamic" in token_str:
            return {
                "detected": True,
                "fields": {
                    "dynamic_field": "dynamic value"
                }
            }
        return False
""")
        
        # Load the plugin
        result = self.plugin_manager.load_plugin(plugin_path)
        self.assertTrue(result)
        self.assertIn("dynamic_feature", self.plugin_manager.detectors)
        self.assertIn("dynamic_field", self.plugin_manager.custom_entity_fields)
        
        # Test detection
        result = self.plugin_manager.detect_features(
            MockCursor(),
            ["dynamic", "test"],
            "dynamic test",
            []
        )
        self.assertEqual(len(result["features"]), 1)
        self.assertIn("dynamic_feature", result["features"])
        self.assertEqual(result["custom_fields"]["dynamic_field"], "dynamic value")
        
    def test_plugin_discovery(self):
        """Test plugin discovery from directories"""
        # Create multiple test plugin files
        os.makedirs(os.path.join(self.plugin_dir.name, "subdir"), exist_ok=True)
        
        # Plugin 1 in root directory
        with open(os.path.join(self.plugin_dir.name, "plugin1.py"), "w") as f:
            f.write("""
from feature_detectors import FeatureDetector

class Plugin1Detector(FeatureDetector):
    def __init__(self):
        super().__init__("feature1", "TEST", "Feature 1")
        
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        return "feature1" in token_str
""")
        
        # Plugin 2 in subdirectory
        with open(os.path.join(self.plugin_dir.name, "subdir", "plugin2.py"), "w") as f:
            f.write("""
from feature_detectors import FeatureDetector

class Plugin2Detector(FeatureDetector):
    def __init__(self):
        super().__init__("feature2", "TEST", "Feature 2")
        
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        return "feature2" in token_str
""")
        
        # Discover plugins
        self.plugin_manager.discover_plugins()
        
        # Check if both plugins were discovered and loaded
        self.assertIn("feature1", self.plugin_manager.detectors)
        self.assertIn("feature2", self.plugin_manager.detectors)
        
        # Test detection
        result1 = self.plugin_manager.detect_features(
            MockCursor(),
            ["test", "feature1"],
            "test feature1",
            []
        )
        self.assertIn("feature1", result1["features"])
        
        result2 = self.plugin_manager.detect_features(
            MockCursor(),
            ["test", "feature2"],
            "test feature2",
            []
        )
        self.assertIn("feature2", result2["features"])
        
    def test_error_handling(self):
        """Test error handling during plugin loading and detection"""
        # Create a plugin with syntax error
        plugin_path = os.path.join(self.plugin_dir.name, "error_plugin.py")
        with open(plugin_path, "w") as f:
            f.write("""
from feature_detectors import FeatureDetector

class ErrorDetector(FeatureDetector):
    def __init__(self):
        super().__init__("error_feature", "TEST", "Error feature")
        
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        # Intentional error
        undefined_variable
        return True
""")
        
        # Load the plugin - should fail gracefully
        result = self.plugin_manager.load_plugin(plugin_path)
        self.assertTrue(result)  # Plugin is loaded, but detector will fail
        
        # Create a detector that raises an exception
        class ExceptionDetector(FeatureDetector):
            def __init__(self):
                super().__init__("exception_feature", "TEST", "Exception feature")
                
            def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
                raise RuntimeError("Test exception")
                
        self.plugin_manager.register_detector(ExceptionDetector())
        
        # Test detection with error handler
        result = self.plugin_manager.detect_features(
            MockCursor(),
            ["test"],
            "test",
            []
        )
        # Should not crash, but not detect any features
        self.assertEqual(len(result["features"]), 0)
        
    def test_integration_with_database(self):
        """Test integration with the entity database (needs to be mocked)"""
        # This is an integration test that mocks database integration
        # In a real environment, this would connect to the actual database
        
        from entity import Entity
        from clang.cindex import CursorKind, AccessSpecifier
        
        # Create a mock entity
        entity = MagicMock(spec=Entity)
        entity.uuid = "test-uuid"
        entity.name = "TestEntity"
        entity.kind = CursorKind.CLASS_DECL
        entity.custom_fields = {}
        
        # Create a detector that adds custom fields
        class DBDetector(FeatureDetector):
            entity_fields = {
                "db_field": {
                    "type": "TEXT",
                    "description": "Database test field"
                }
            }
            
            def __init__(self):
                super().__init__("db_feature", "TEST", "Database feature")
                
            def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
                return {
                    "detected": True,
                    "fields": {
                        "db_field": "db value"
                    }
                }
                
        self.plugin_manager.register_detector(DBDetector())
        self.plugin_manager.register_custom_entity_fields("db_feature", DBDetector.entity_fields)
        
        # Mock cursor and detection
        cursor = MockCursor()
        token_spellings = ["test"]
        token_str = "test"
        
        # Detect features
        result = self.plugin_manager.detect_features(cursor, token_spellings, token_str, [])
        
        # Update entity with detected custom fields
        entity.custom_fields = result["custom_fields"]
        
        # Check if custom fields were added to entity
        self.assertEqual(entity.custom_fields["db_field"], "db value")
        
        # In a real test, we would store this entity in the database
        # and verify the custom fields are preserved

if __name__ == "__main__":
    unittest.main()
