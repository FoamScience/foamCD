#!/usr/bin/env python3

import unittest
import sys
import os
import sqlite3
import tempfile
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent / "src"))
from foamcd.logs import setup_logging

logger = setup_logging(verbose=True).getChild('test')

try:
    from foamcd.parse import ClangParser, get_source_files_from_compilation_database, LIBCLANG_CONFIGURED
    from foamcd.config import Config
    test_config = Config()
    
    SKIP_LIBCLANG_TESTS = not LIBCLANG_CONFIGURED
    logger.debug("Imported ClangParser successfully")
    if SKIP_LIBCLANG_TESTS:
        logger.warning("libclang is not properly configured. Parser tests will be skipped.")
except (ImportError, AttributeError) as e:
    SKIP_LIBCLANG_TESTS = True
    logger.error(f"Failed to import ClangParser: {e}")
    class DummyClangParser:
        def __init__(self, *args, **kwargs):
            pass
    ClangParser = DummyClangParser
    def get_source_files_from_compilation_database(*args, **kwargs):
        return []

class TestClangParser(unittest.TestCase):
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
        """Generate a portable compilation database for testing"""
        import json
        import subprocess
        
        cxx_std = "c++20"  # Default to C++20
        if config:
            cxx_std = config.get("parser.cpp_standard", "c++20")
        include_paths = []
        if config:
            paths = config.get("parser.include_paths", [])
            if paths:
                include_paths = paths
        else:
            try:
                clang_result = subprocess.run(
                    ["clang++", "-E", "-x", "c++", "-v", "/dev/null"],
                    stderr=subprocess.PIPE,
                    text=True,
                    check=False
                )
                in_include_section = False
                for line in clang_result.stderr.splitlines():
                    if "#include <...> search starts here:" in line:
                        in_include_section = True
                        continue
                    elif "End of search list." in line:
                        in_include_section = False
                        continue
                    if in_include_section:
                        path = line.strip()
                        include_paths.append(f"-I{path}")
                logger.debug(f"Detected system include paths: {include_paths}")
            except Exception as e:
                logger.warning(f"Failed to detect system include paths: {e}")
                include_paths = ["-I/usr/include", "-I/usr/local/include"]
        
        cpp_files = []
        for ext in [".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx"]:
            cpp_files.extend(list(fixtures_dir.glob(f"*{ext}")))
        
        entries = []
        for file_path in cpp_files:
            abs_path = file_path.absolute()
            file_flags = []
            if file_path.suffix in [".h", ".hpp", ".hxx"]:
                file_flags.append("-x")
                file_flags.append("c++")
            file_flags.append("-std=c++20")
            if cxx_std and cxx_std.lower() != "none" and cxx_std.lower() != "c++20":
                logger.warning(f"Overriding default C++20 standard with {cxx_std}")
                file_flags[-1] = f"-std={cxx_std}"
            formatted_include_paths = []
            for path in include_paths:
                formatted_include_paths.append(f"-I{path}")
            entry = {
                "directory": str(fixtures_dir),
                "command": f"clang++ {' '.join(file_flags)} {' '.join(formatted_include_paths)} -c {abs_path}",
                "file": str(abs_path)
            }
            entries.append(entry)
        
        compile_commands_path = fixtures_dir / "compile_commands.json"
        with open(compile_commands_path, "w") as f:
            json.dump(entries, f, indent=2)
            
        logger.debug(f"Generated commands for {len(entries)} files")
        
        return str(fixtures_dir)
    
    @classmethod
    def setUpClass(cls):
        if SKIP_LIBCLANG_TESTS:
            logger.warning("libclang is not properly configured. Skipping ClangParser tests.")
            raise unittest.SkipTest("libclang is not properly configured. Skipping ClangParser tests.")
        test_config = cls.get_test_config()
        cls.fixtures_dir = cls.get_fixtures_dir()
        
        try:
            cls.compile_commands_path = cls.generate_compile_commands(cls.fixtures_dir, test_config)
            compile_commands_file = Path(cls.compile_commands_path) / "compile_commands.json"
            if not compile_commands_file.exists():
                raise FileNotFoundError(f"Generated compilation database not found at: {compile_commands_file}")
            logger.info(f"Using dynamically generated compilation database from: {compile_commands_file}")
            
            cls.test_header_file = str(cls.fixtures_dir / "simple_class.hpp")
            logger.info(f"Using test header file: {cls.test_header_file}")
            logger.debug("Initializing ClangParser...")
            cls.parser = ClangParser(cls.compile_commands_path, config=test_config)
            logger.info("ClangParser initialized successfully")
        except Exception as e:
            logger.error(f"Failed to set up test: {e}")
            raise unittest.SkipTest(f"Failed to set up test: {e}")
    
    def setUp(self):
        # Reset the entities dictionary before each test to ensure isolation
        self.parser.entities = {}

    def test_parser_initialization(self):
        """Test that the parser initializes correctly with a compilation database"""
        self.assertIsNotNone(self.parser)
        self.assertIsNotNone(self.parser.compilation_database)
        self.assertEqual(len(self.parser.entities), 0)

    def test_get_compile_commands(self):
        """Test extraction of compilation commands"""
        args = self.parser.get_compile_commands(self.test_header_file)
        self.assertIsInstance(args, list)
        has_std_flag = any(arg.startswith("-std=c++") for arg in args)
        self.assertTrue(has_std_flag, "Should have -std=c++ flag in compile commands")

    def test_extract_doc_comment(self):
        """Test the extraction of documentation comments from a cursor"""
        entities = self.parser.parse_file(self.test_header_file)
        self.assertGreater(len(entities), 0, "Should parse at least one entity from test file")
        class_entity = next((e for e in entities if e.name == "SimpleClass"), None)
        self.assertIsNotNone(class_entity, "Should find SimpleClass entity")
        self.assertIn("simple class", class_entity.doc_comment.lower())
        get_value_method = next((e for e in class_entity.children if e.name == "getValue"), None)
        if get_value_method:
            self.assertIn("current value", get_value_method.doc_comment.lower())

    def test_parse_file(self):
        """Test parsing a C++ file with the parser"""
        entities = self.parser.parse_file(self.test_header_file)
        self.assertIsInstance(entities, list)
        self.assertGreater(len(entities), 0)
        self.assertIn(self.test_header_file, self.parser.entities)
        class_entity = next((e for e in entities if e.name == "SimpleClass"), None)
        self.assertIsNotNone(class_entity)
        self.assertEqual(class_entity.kind.name, "CLASS_DECL")
        methods = [e for e in class_entity.children if "METHOD" in e.kind.name]
        method_names = [m.name for m in methods]
        self.assertIn("getValue", method_names)
        self.assertIn("setValue", method_names)

    def test_export_to_database(self):
        """Test exporting parsed entities to SQLite database"""
        self.parser.parse_file(self.test_header_file)
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as temp_file:
            db_path = temp_file.name
        try:
            self.parser.export_to_database(db_path)
            self.assertTrue(os.path.exists(db_path))
            self.assertGreater(os.path.getsize(db_path), 0)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            required_tables = ['entities', 'features', 'entity_features', 'files']
            for table in required_tables:
                self.assertIn(table, tables, f"Database should have '{table}' table")
            cursor.execute("SELECT * FROM entities WHERE name = 'SimpleClass' AND kind = 'CLASS_DECL'")
            class_row = cursor.fetchone()
            self.assertIsNotNone(class_row, "SimpleClass should be in the database")
            class_uuid = class_row['uuid']
            self.assertTrue(class_uuid, "Class should have a UUID")
            cursor.execute("SELECT * FROM entities WHERE parent_uuid = ? AND kind = 'CXX_METHOD'", (class_uuid,))
            methods = cursor.fetchall()
            self.assertGreater(len(methods), 0, "Class should have methods")
            method_names = [m['name'] for m in methods]
            self.assertIn('getValue', method_names)
            self.assertIn('setValue', method_names)
            conn.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_source_files_from_compilation_database(self):
        """Test extracting source files from compilation database"""
        source_files = get_source_files_from_compilation_database(self.parser.compilation_database)
        
        self.assertIsInstance(source_files, list)
        self.assertGreaterEqual(len(source_files), 1)
        test_file_path = Path(self.test_header_file).absolute()
        test_file_name = test_file_path.name
        logger.debug(f"Looking for {test_file_name} in {source_files}")
        file_found = str(test_file_path) in source_files or any(src.endswith(test_file_name) for src in source_files)
        self.assertTrue(file_found, f"File {test_file_name} not found in source files list: {source_files}")


if __name__ == "__main__":
    unittest.main()
