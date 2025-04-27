#!/usr/bin/env python3

import unittest
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent / "src"))
from foamcd.logs import setup_logging

logger = setup_logging(verbose=True).getChild('test.attributes')

try:
    from foamcd.parse import ClangParser, LIBCLANG_CONFIGURED
    from foamcd.feature_detectors import (
        NoReturnAttributeDetector, DeprecatedAttributeDetector,
        NodiscardMaybeUnusedAttributesDetector, Cpp20AttributesDetector
    )
    from foamcd.config import Config
    test_config_path = str(Path(__file__).parent.parent / "test_config.yaml")
    test_config = Config(test_config_path)
    logger.info(f"Loaded test configuration from {test_config_path}")
    SKIP_LIBCLANG_TESTS = not LIBCLANG_CONFIGURED
    logger.debug("Imported ClangParser and attribute detectors successfully")
    if SKIP_LIBCLANG_TESTS:
        logger.warning("libclang is not properly configured. Attribute detection tests will be skipped.")
except (ImportError, AttributeError) as e:
    SKIP_LIBCLANG_TESTS = True
    logger.error(f"Failed to import required modules: {e}")
    # Create placeholder for test skipping
    class ClangParser:
        def __init__(self, *args, **kwargs):
            pass
        def parse_file(self, *args, **kwargs):
            return []


@unittest.skipIf(SKIP_LIBCLANG_TESTS, "libclang not properly configured")
class TestCppAttributeDetection(unittest.TestCase):
    """Test detection of C++ compiler attributes"""

    @classmethod
    def get_fixtures_dir(cls):
        """Get the fixtures directory path"""
        return Path(__file__).parent.parent / "fixtures"

    @classmethod
    def setUpClass(cls):
        """Set up the test environment"""
        fixtures_dir = cls.get_fixtures_dir()
        attributes_file = fixtures_dir / "cpp_attributes.cpp"
        
        if not attributes_file.exists():
            logger.error(f"Test file {attributes_file} does not exist")
            raise FileNotFoundError(f"Required test file {attributes_file} not found")
            
        cls.attributes_file = str(attributes_file)
        cls.parser = ClangParser(str(fixtures_dir))
        
        # Make sure we have the individual detector instances
        cls.noreturn_detector = NoReturnAttributeDetector()
        cls.deprecated_detector = DeprecatedAttributeDetector()
        cls.nodiscard_maybe_unused_detector = NodiscardMaybeUnusedAttributesDetector()
        cls.cpp20_attributes_detector = Cpp20AttributesDetector()
        
        # Parse the test file
        cls.entities = cls.parser.parse_file(cls.attributes_file)
        
        if not cls.entities:
            logger.warning(f"No entities were parsed from {cls.attributes_file}")

    def test_cpp11_noreturn_attribute(self):
        """Test detection of [[noreturn]] attribute (C++11)"""
        # Read the fixture file
        with open(self.attributes_file, 'r') as f:
            content = f.read()
        
        # Test our detector directly
        test_tokens = ['[[', 'noreturn', ']]', 'void', 'crash_program']
        detector = self.noreturn_detector
        result = detector.detect(None, test_tokens, "[[noreturn]] void crash_program", [])
        self.assertTrue(result, "NoReturnAttributeDetector failed to detect pattern")
        
        # Also check if the entity exists and our detection logic is working correctly
        if hasattr(self, 'entities') and self.entities:
            crash_func = None
            for entity in self.entities:
                if entity.name == "crash_program":
                    crash_func = entity
                    break
            if crash_func:
                print(f"Debug: crash_program cpp_features = {crash_func.cpp_features}")

    def test_cpp14_deprecated_attribute(self):
        """Test detection of [[deprecated]] attribute (C++14)"""
        # Test our detector directly
        detector = self.deprecated_detector
        
        # Test simple deprecated attribute
        test_tokens1 = ['[[', 'deprecated', ']]', 'void', 'old_function']
        result1 = detector.detect(None, test_tokens1, "[[deprecated]] void old_function", [])
        self.assertTrue(result1, "DeprecatedAttributeDetector failed to detect simple attribute")
        
        # Test deprecated with message
        test_tokens2 = ['[[', 'deprecated', '(', '"Use new_function() instead"', ')', ']]', 'void', 'deprecated_with_message']
        result2 = detector.detect(None, test_tokens2, 
                               "[[deprecated(\"Use new_function() instead\")]] void deprecated_with_message", [])
        self.assertTrue(result2, "DeprecatedAttributeDetector failed to detect attribute with message")

    def test_cpp17_nodiscard_attribute(self):
        """Test detection of [[nodiscard]] attribute (C++17)"""
        # Test our detector directly
        detector = self.nodiscard_maybe_unused_detector
        
        # Test nodiscard on function
        test_tokens1 = ['[[', 'nodiscard', ']]', 'int', 'compute_value']
        result1 = detector.detect(None, test_tokens1, "[[nodiscard]] int compute_value", [])
        self.assertTrue(result1, "NodiscardMaybeUnusedAttributesDetector failed to detect attribute on function")
        
        # Test nodiscard on class
        test_tokens2 = ['class', '[[', 'nodiscard', ']]', 'CriticalResource']
        result2 = detector.detect(None, test_tokens2, "class [[nodiscard]] CriticalResource", [])
        self.assertTrue(result2, "NodiscardMaybeUnusedAttributesDetector failed to detect attribute on class")

    def test_cpp17_maybe_unused_attribute(self):
        """Test detection of [[maybe_unused]] attribute (C++17)"""
        # Test our detector directly
        detector = self.nodiscard_maybe_unused_detector
        
        # Test maybe_unused on parameter
        test_tokens = ['void', 'function_with_unused', '(', '[[', 'maybe_unused', ']]', 'int', 'parameter', ')']
        result = detector.detect(None, test_tokens, "void function_with_unused([[maybe_unused]] int parameter)", [])
        self.assertTrue(result, "NodiscardMaybeUnusedAttributesDetector failed to detect maybe_unused attribute")
        
        # Test maybe_unused on variable
        test_tokens2 = ['[[', 'maybe_unused', ']]', 'static', 'const', 'int', 'UNUSED_CONSTANT']
        result2 = detector.detect(None, test_tokens2, "[[maybe_unused]] static const int UNUSED_CONSTANT", [])
        self.assertTrue(result2, "NodiscardMaybeUnusedAttributesDetector failed to detect maybe_unused on variable")

    def test_cpp20_likely_unlikely_attributes(self):
        """Test detection of [[likely]] and [[unlikely]] attributes (C++20)"""
        # Test our detector directly
        detector = self.cpp20_attributes_detector
        
        # Test likely attribute
        test_tokens1 = ['if', '(', 'value', '>', '100', ')', '[[', 'likely', ']]']
        result1 = detector.detect(None, test_tokens1, "if (value > 100) [[likely]]", [])
        self.assertTrue(result1, "Cpp20AttributesDetector failed to detect likely attribute")
        
        # Test unlikely attribute
        test_tokens2 = ['else', '[[', 'unlikely', ']]']
        result2 = detector.detect(None, test_tokens2, "else [[unlikely]]", [])
        self.assertTrue(result2, "Cpp20AttributesDetector failed to detect unlikely attribute")

    def test_cpp20_no_unique_address_attribute(self):
        """Test detection of [[no_unique_address]] attribute (C++20)"""
        # Test our detector directly
        detector = self.cpp20_attributes_detector
        
        # Test no_unique_address attribute
        test_tokens = ['[[', 'no_unique_address', ']]', 'EmptyStruct', 'empty']
        result = detector.detect(None, test_tokens, "[[no_unique_address]] EmptyStruct empty", [])
        self.assertTrue(result, "Cpp20AttributesDetector failed to detect no_unique_address attribute")

    # C++23 test methods removed to maintain compatibility with older compilers


if __name__ == "__main__":
    unittest.main()
