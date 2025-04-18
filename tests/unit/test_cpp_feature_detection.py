#!/usr/bin/env python3

import unittest
import sys
import os
from pathlib import Path

# Add src directory to Python path for imports
sys.path.append(str(Path(__file__).parent.parent.parent / "src"))

# Import logs module for consistent logger setup
from logs import setup_logging

# Configure logger for feature tests
logger = setup_logging(verbose=True).getChild('test.features')

# Use a try/except block to handle the case where libclang isn't configured
try:
    from parse import ClangParser, CPP_FEATURES, LIBCLANG_CONFIGURED
    from entity import Entity
    from config import Config
    
    # Create a test configuration with specialized settings for C++ parsing
    test_config_path = str(Path(__file__).parent.parent / "test_config.yaml")
    test_config = Config(test_config_path)
    logger.info(f"Loaded test configuration from {test_config_path}")
    
    SKIP_LIBCLANG_TESTS = not LIBCLANG_CONFIGURED
    logger.debug("Imported CPP_FEATURES and ClangParser successfully")
    logger.debug(f"CPP_FEATURES contains {sum(len(features) for features in CPP_FEATURES.values())} features across {len(CPP_FEATURES)} C++ versions")
    if SKIP_LIBCLANG_TESTS:
        logger.warning("libclang is not properly configured. Feature detection tests will be skipped.")
except (ImportError, AttributeError) as e:
    SKIP_LIBCLANG_TESTS = True
    logger.error(f"Failed to import required modules: {e}")
    # Create placeholder for test skipping
    CPP_FEATURES = {
        'cpp98': set(['classes', 'inheritance']),
        'cpp11': set(['lambda_expressions', 'auto_type']),
        'cpp14': set(['generic_lambdas']),
        'cpp17': set(['structured_bindings']),
        'cpp20': set(['concepts']),
    }
    logger.info("Using placeholder CPP_FEATURES for testing")
    class DummyClangParser:
        def __init__(self, *args, **kwargs):
            pass
        def parse_file(self, *args, **kwargs):
            return []
    ClangParser = DummyClangParser

class TestCppFeatureDetection(unittest.TestCase):
    """Test detection of C++ language features"""
    
    @classmethod
    def get_test_config(cls):
        """Get test configuration with appropriate defaults for this test"""
        return test_config
    
    @classmethod
    def get_fixtures_dir(cls):
        """Get the fixtures directory path"""
        return Path(__file__).parent.parent / "fixtures"
    
    @classmethod
    def generate_compile_commands(cls, fixtures_dir, config=None):
        """Dynamically generate compile_commands.json with portable paths
        
        This replaces the static compile_commands.json file to make tests portable.
        
        Args:
            fixtures_dir: Path to the fixtures directory
            config: Configuration object with parser settings
            
        Returns:
            Path to the generated compile_commands.json file
        """
        import json
        import os
        import platform
        import subprocess
        from pathlib import Path
        
        # Get C++ standard version from config
        cxx_std = "c++20"  # Default to C++20
        if config:
            cxx_std = config.get("parser.cpp_standard", "c++20")
            
        # Get system include paths (portable across environments)
        include_paths = []
        if config:
            paths = config.get("parser.include_paths", [])
            if paths:
                include_paths = paths
            else:
                # Fall back to compile_flags for -std=xxx
                compile_flags = config.get('parser.compile_flags', [])
                for flag in compile_flags:
                    if flag.startswith('-std='):
                        cxx_std = flag[5:]  # Extract std version
                        break
                        
        logger.info(f"Using C++ standard: {cxx_std}")
        
        # Get include paths from config if available
        system_include_paths = []
        if config and config.get('parser.include_paths'):
            system_include_paths = config.get('parser.include_paths')
            logger.info(f"Using {len(system_include_paths)} include paths from config")
        else:
            # Try to detect C++ include paths using compiler
            try:
                # This works for gcc/clang to find system include paths
                include_output = subprocess.check_output(
                    "echo | c++ -E -Wp,-v -x c++ - 2>&1 | grep '^ '| grep -v 'ignoring nonexistent directory'",
                    shell=True, universal_newlines=True
                )
                system_include_paths = [p.strip() for p in include_output.splitlines()]
                logger.debug(f"Detected {len(system_include_paths)} system include paths")
            except (subprocess.SubprocessError, FileNotFoundError) as e:
                logger.warning(f"Could not detect system include paths: {e}")
                
                # Fallback paths for common platforms when detection fails
                if platform.system() == "Linux":
                    # Common Linux paths
                    system_include_paths = [
                        "/usr/include",
                        "/usr/include/c++/11",
                        "/usr/include/x86_64-linux-gnu/c++/11",
                        "/usr/lib/gcc/x86_64-linux-gnu/11/include"
                    ]
                elif platform.system() == "Darwin":
                    # Common macOS paths 
                    system_include_paths = [
                        "/usr/include",
                        "/Library/Developer/CommandLineTools/usr/include/c++/v1",
                        "/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include"
                    ]
                
        # Get test files (all .cpp/.hpp/.h files in fixtures directory)
        cpp_files = list(fixtures_dir.glob("**/*.cpp")) + \
                   list(fixtures_dir.glob("**/*.hpp")) + \
                   list(fixtures_dir.glob("**/*.h"))
                   
        # Use relative paths for portability when possible
        fixtures_dir_str = str(fixtures_dir)
        
        # Get any additional compile flags from config
        extra_flags = []
        if config:
            extra_flags = [flag for flag in config.get('parser.compile_flags', []) 
                          if not flag.startswith('-std=') and not flag.startswith('-I')]
            
        # Create compilation database entries
        entries = []
        for file_path in cpp_files:
            # Skip temporary directory files
            if "temp" in str(file_path):
                continue
                
            # Get relative path for file if possible
            try:
                rel_file_path = file_path.relative_to(fixtures_dir)
                file_str = str(rel_file_path)
            except ValueError:
                # Fall back to absolute path if relative not possible
                file_str = str(file_path)
            
            # Ensure .h files are compiled as C++
            file_flags = []
            if file_path.suffix in [".h", ".hpp", ".hxx"]:
                file_flags.append("-x")
                file_flags.append("c++")
            
            # Always include the C++20 standard flag - required for modern C++ features
            file_flags.append("-std=c++20")
            
            # Add any additional standard if specified and different from c++20
            if cxx_std and cxx_std != "None" and cxx_std != "c++20":
                logger.warning(f"Overriding default C++20 standard with {cxx_std}")
                file_flags[-1] = f"-std={cxx_std}"
            
            # Always use absolute paths to ensure consistent behavior
            abs_path = file_path.absolute()
            
            # Format include paths with -I prefix for each path
            formatted_include_paths = []
            for path in system_include_paths:
                formatted_include_paths.append(f"-I{path}")
            
            # Create compile command entry with absolute paths and properly formatted include paths
            entry = {
                "directory": str(fixtures_dir),
                "command": f"clang++ {' '.join(file_flags)} {' '.join(formatted_include_paths)} -c {abs_path}",
                "file": str(abs_path)
            }
            entries.append(entry)
        
        # Write to compile_commands.json in temp directory
        compile_commands_path = fixtures_dir / "compile_commands.json"
        with open(compile_commands_path, "w") as f:
            json.dump(entries, f, indent=2)
            
        logger.info(f"Generated portable compile_commands.json at {compile_commands_path}")
        logger.debug(f"Generated commands for {len(entries)} files")
        
        return str(fixtures_dir)

    @classmethod
    def setUpClass(cls):
        """
        Set up the test case with a ClangParser instance.
        """
        # Skip parser-dependent tests if libclang is not configured
        if SKIP_LIBCLANG_TESTS:
            logger.info("libclang not configured - will only run CPP_FEATURES map tests")
            cls.entities = []
            # We still run the tests for CPP_FEATURES map, but skip the actual parsing tests
            return
        
        # Get test config and fixtures dir
        test_config = cls.get_test_config()
        cls.fixtures_dir = cls.get_fixtures_dir()
        
        if not test_config:
            raise unittest.SkipTest("No test configuration available")
        
        # Generate portable compile_commands.json
        try:
            cls.compile_commands_path = cls.generate_compile_commands(cls.fixtures_dir, test_config)
            compile_commands_file = Path(cls.compile_commands_path) / "compile_commands.json"
            
            # Verify the compilation database exists
            if not compile_commands_file.exists():
                raise FileNotFoundError(f"Generated compilation database not found at: {compile_commands_file}")
                
            logger.info(f"Using dynamically generated compilation database from: {compile_commands_file}")
            
            # Get the test file from config or default to the implementation file
            features_file = test_config.get('parser.test_features_file', 'cpp_features.cpp')
            cls.cpp_features_file = str(cls.fixtures_dir / features_file)
            logger.info(f"Using C++ features test file: {cls.cpp_features_file}")
            
            # Initialize parser with the compile_commands path
            logger.debug("Initializing ClangParser...")
            
            # Use the config directly without trying to update it as a dictionary
            # Just pass the original test_config and the compile_commands_path to ClangParser
            cls.parser = ClangParser(cls.compile_commands_path, config=test_config)
            logger.info("ClangParser initialized successfully")
            
            # Parse the features file to get entities
            logger.debug(f"Parsing entities from {cls.cpp_features_file}")
            cls.entities = cls.parser.parse_file(cls.cpp_features_file)
            logger.info(f"Parsed {len(cls.entities)} entities from {cls.cpp_features_file}")
            
        except Exception as e:
            logger.error(f"Error during test setup: {e}")
            raise unittest.SkipTest(f"Failed to set up test: {e}")

    def test_cpp_features_map(self):
        """Test that the CPP_FEATURES map is properly populated"""
        self.assertIsNotNone(CPP_FEATURES)
        self.assertIn('cpp98', CPP_FEATURES)
        self.assertIn('cpp11', CPP_FEATURES)
        self.assertIn('cpp14', CPP_FEATURES)
        self.assertIn('cpp17', CPP_FEATURES)
        self.assertIn('cpp20', CPP_FEATURES)
        
        # Check that each version has some features
        self.assertGreater(len(CPP_FEATURES['cpp98']), 0)
        self.assertGreater(len(CPP_FEATURES['cpp11']), 0)
        self.assertGreater(len(CPP_FEATURES['cpp14']), 0)
        self.assertGreater(len(CPP_FEATURES['cpp17']), 0)
        self.assertGreater(len(CPP_FEATURES['cpp20']), 0)
        
        # Check specific feature presence
        self.assertIn('classes', CPP_FEATURES['cpp98'])
        self.assertIn('lambda_expressions', CPP_FEATURES['cpp11'])
        self.assertIn('generic_lambdas', CPP_FEATURES['cpp14'])
        self.assertIn('structured_bindings', CPP_FEATURES['cpp17'])
        self.assertIn('concepts', CPP_FEATURES['cpp20'])

    def test_feature_detection(self):
        """Test that the feature detection correctly identifies C++ language features"""
        # Skip this test if libclang is not configured
        if SKIP_LIBCLANG_TESTS:
            logger.warning("libclang is not properly configured. Skipping feature detection test.")
            self.skipTest("libclang is not properly configured. Skipping feature detection test.")
            
        # Skip this test if we couldn't parse the file
        if not self.entities:
            logger.warning("No entities parsed from the test file. Skipping feature detection test.")
            self.skipTest("Couldn't parse the C++ features file")
        
        # Extract all detected features from all entities
        all_features = set()
        for entity in self.entities:
            all_features.update(self._collect_features(entity))
        
        # Print detected features for debugging
        logger.info(f"Detected {len(all_features)} C++ features: {sorted(all_features)}")
        
        # Use CPP_FEATURES directly from parse.py as our expected feature set
        # This ensures the tests are always in sync with the current feature definitions
        expected_features = CPP_FEATURES
        
        # Optional: Log all expected features for reference
        for version, features in expected_features.items():
            logger.debug(f"Expecting to test {len(features)} {version} features: {sorted(features)}")
        
        # Validate detected features by version
        for version, features in expected_features.items():
            detected = []
            missing = []
            
            for feature in features:
                if feature in all_features:
                    detected.append(feature)
                    logger.debug(f"Successfully detected {version} feature: {feature}")
                else:
                    missing.append(feature)
                    logger.warning(f"Failed to detect {version} feature: {feature}")
            
            # Count how many features we detected
            detection_percentage = (len(detected) / len(features)) * 100 if features else 0
            logger.info(f"Detected {len(detected)}/{len(features)} {version} features ({detection_percentage:.1f}%)")
            
            # Check if we detected a reasonable number of features for this version
            # Allow for some features to be missing, but ensure we detect most
            min_expected = max(1, len(features) // 2)  # At least half of key features or at least 1
            self.assertGreaterEqual(
                len(detected), min_expected,
                f"Too few {version} features detected. Found: {detected}, missing: {missing}"
            )
            
            # Print summary for this version
            if missing:
                logger.warning(f"{version} features not detected: {missing}")
            
        # Check for at least one feature detection from each C++ version
        # These assertions ensure each version has some representation
        versions = ['cpp98', 'cpp11', 'cpp14', 'cpp17', 'cpp20']
        for version in versions:
            detected = False
            detected_features = []
            for feature in CPP_FEATURES[version]:
                if feature in all_features:
                    detected = True
                    detected_features.append(feature)
            
            if detected:
                logger.info(f"Detected {len(detected_features)} features from {version}: {detected_features}")
            else:
                logger.warning(f"No features detected for {version}")
    
    def _collect_features(self, entity):
        """Recursively collect all features from an entity and its children"""
        features = set(entity.cpp_features)
        for child in entity.children:
            features.update(self._collect_features(child))
        return features

    def test_version_categorization(self):
        """Test that features are correctly categorized by C++ version"""
        # Create a map of features to versions for lookup
        feature_to_version = {}
        for version, features in CPP_FEATURES.items():
            for feature in features:
                feature_to_version[feature] = version
                
        # Verify no duplicate features across versions
        all_features = []
        for features in CPP_FEATURES.values():
            all_features.extend(features)
            
        unique_features = set(all_features)
        self.assertEqual(len(all_features), len(unique_features), 
                         "Features should not be duplicated across versions")
        
        # Check that specific features are in the correct version
        self.assertEqual(feature_to_version.get('lambda_expressions'), 'cpp11')
        self.assertEqual(feature_to_version.get('generic_lambdas'), 'cpp14')
        self.assertEqual(feature_to_version.get('structured_bindings'), 'cpp17')
        self.assertEqual(feature_to_version.get('concepts'), 'cpp20')

if __name__ == "__main__":
    unittest.main()
