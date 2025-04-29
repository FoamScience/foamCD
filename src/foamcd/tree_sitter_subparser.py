#!/usr/bin/env python3
"""
Tree-sitter based subparser for foamCD
Used as a fallback when libclang cannot parse a file,
or when fail-tolerant token-based parsing is preferable,
eg. for macro-heavy unit-testing frameworks

!!!ONLY for parsing unit tests for now      !!!
!!!This will remain true as long as ther is !!!
!!!a bunch of TODO: NOT fully implemented   !!!
"""

from typing import List, Dict, Any

from .logs import setup_logging

logger = setup_logging()

try:
    import tree_sitter_cpp as tscpp
    from tree_sitter import Language, Parser
    TREE_SITTER_AVAILABLE = True
    CPP_LANGUAGE = Language(tscpp.language())
    logger.info(f"Loaded tree-sitter c++ parser version {CPP_LANGUAGE.version}")
except ImportError:
    logger.warning("Tree-sitter module not found, fallback parsing will not be available")
    TREE_SITTER_AVAILABLE = False


class TreeSitterSubparser:
    """Tree-sitter based parser for extracting C++ information when libclang fails"""
    
    def __init__(self):
        """Initialize the Tree-sitter subparser"""
        if not TREE_SITTER_AVAILABLE:
            raise ImportError("Tree-sitter is not available. Fallback parsing is not possible.")
            
        if CPP_LANGUAGE is None:
            raise ImportError("Tree-sitter C++ language is not available. Fallback parsing is not possible.")
            
        self.parser = Parser(CPP_LANGUAGE)
        
    def parse_file(self, filepath: str) -> Dict[str, Any]:
        """Parse a file using Tree-sitter
        
        This method parses a C++ file using the Tree-sitter parser and returns a dict
        with the extracted information (classes, functions, test cases, etc.)
        
        Args:
            filepath: Path to the file to parse
            
        Returns:
            Dict with extracted information
        """
        logger.info(f"Tree-sitter parsing {filepath}")
        result = {
            "classes": [],
            "functions": [],
            "test_cases": []
        }
        
        try:
            with open(filepath, 'rb') as f:
                content = f.read()
                tree = self.parser.parse(content)
                root_node = tree.root_node
                current_index = 0
                while current_index < len(root_node.children):
                    if current_index + 1 < len(root_node.children):
                        expr_stmt = root_node.children[current_index]
                        next_node = root_node.children[current_index + 1]
                        if expr_stmt.type == "expression_statement" and next_node.type == "compound_statement":
                            call_expr = self._find_call_expression(expr_stmt)
                            if call_expr and self._is_test_case_call(call_expr):
                                test_case = self._extract_test_case(call_expr, next_node, filepath)
                                if test_case:
                                    result["test_cases"].append(test_case)
                                current_index += 2  # hard-coded assumption of 2 nodes, well...
                                continue
                    current_node = root_node.children[current_index]
                    if current_node.type == "ERROR":
                        template_test = self._extract_template_test_case_from_error(current_node)
                        if template_test:
                            if current_index + 1 < len(root_node.children) and root_node.children[current_index + 1].type == "compound_statement":
                                compound_stmt = root_node.children[current_index + 1]
                                template_test["references"] = self._extract_type_references(compound_stmt)
                                template_test["end_line"] = compound_stmt.end_point[0]
                                template_test["end_column"] = compound_stmt.end_point[1]
                                result["test_cases"].append(template_test)
                                current_index += 2
                            else:
                                result["test_cases"].append(template_test)
                                current_index += 1
                            continue
                    current_index += 1  # Move to next node if not a test case pattern
                for class_node in self._find_nodes_by_type(root_node, "class_specifier"):
                    class_info = self._extract_class_info(class_node)
                    if class_info:
                        result["classes"].append(class_info)
                        
        except Exception as e:
            logger.error(f"Error parsing {filepath} with Tree-sitter: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        logger.info(f"Tree-sitter extracted {len(result['classes'])} classes, {len(result['functions'])} functions, {len(result['test_cases'])} test cases")
        return result
        
    def _process_node(self, node, result: Dict[str, Any], content: bytes):
        """Process a tree-sitter node
        
        Args:
            node: Tree-sitter node
            result: Dictionary to store results
            content: Original file content as bytes
        """
        if node.type == "function_definition":
            func_info = self._extract_function_info(node, content)
            if func_info:
                result["functions"].append(func_info)
                if self._is_test_case(func_info, content):
                    result["test_cases"].append(func_info)
        elif node.type == "class_definition":
            class_info = self._extract_class_info(node, content)
            if class_info:
                result["classes"].append(class_info)
        elif node.type == "namespace_definition":
            namespace_info = self._extract_namespace_info(node, content)
            if namespace_info:
                result["namespaces"].append(namespace_info)
                
        for child in node.children:
            self._process_node(child, result, content)
    
    def _extract_function_info(self, node, content: bytes) -> Dict[str, Any]:
        """Extract information about a function
        
        Args:
            node: Tree-sitter node for the function
            content: Original file content as bytes
            
        Returns:
            Dictionary with function information
        """
        # TODO: NOT fully implemented... no parameter extraction and what not
        function_name_node = self._find_child_with_type(node, "function_declarator")
        if function_name_node:
            identifier_node = self._find_child_with_type(function_name_node, "identifier")
            if identifier_node:
                name = content[identifier_node.start_byte:identifier_node.end_byte].decode('utf-8')
                return {
                    "name": name,
                    "start_line": node.start_point[0],
                    "start_column": node.start_point[1],
                    "end_line": node.end_point[0],
                    "end_column": node.end_point[1],
                    "kind": "function",
                }
        return {}
        
    def _extract_class_info(self, node, content: bytes) -> Dict[str, Any]:
        """Extract information about a class
        
        Args:
            node: Tree-sitter node for the class
            content: Original file content as bytes
            
        Returns:
            Dictionary with class information
        """
        # TODO: NOT fully implemented... no methods extraction
        identifier_node = self._find_child_with_type(node, "identifier")
        if identifier_node:
            name = content[identifier_node.start_byte:identifier_node.end_byte].decode('utf-8')
            return {
                "name": name,
                "start_line": node.start_point[0],
                "start_column": node.start_point[1],
                "end_line": node.end_point[0],
                "end_column": node.end_point[1],
                "kind": "class",
            }
        return {}
        
    def _extract_namespace_info(self, node, content: bytes) -> Dict[str, Any]:
        """Extract information about a namespace
        
        Args:
            node: Tree-sitter node for the namespace
            content: Original file content as bytes
            
        Returns:
            Dictionary with namespace information
        """
        identifier_node = self._find_child_with_type(node, "identifier")
        if identifier_node:
            name = content[identifier_node.start_byte:identifier_node.end_byte].decode('utf-8')
            return {
                "name": name,
                "start_line": node.start_point[0],
                "start_column": node.start_point[1],
                "end_line": node.end_point[0],
                "end_column": node.end_point[1],
                "kind": "namespace",
            }
        return {}
        
    def _is_test_case(self, func_info: Dict[str, Any], content: bytes) -> bool:
        """Check if a function is a test case
        
        Args:
            func_info: Function information
            content: Original file content as bytes
            
        Returns:
            True if the function is a test case, False otherwise
        """
        name = func_info.get("name", "")
        return name.startswith("TEST_CASE") or name.startswith("TEST_") or "TEST_CASE" in name
        
    def _find_child_with_type(self, node, type_name: str):
        """Find a child node with a specific type
        
        Args:
            node: Parent node
            type_name: Type name to find
            
        Returns:
            Child node with the specified type, or None if not found
        """
        for child in node.children:
            if child.type == type_name:
                return child
            found = self._find_child_with_type(child, type_name)
            if found:
                return found
        return None
        
    def _find_call_expression(self, expr_stmt):
        """Find a call_expression within an expression_statement
        
        Structure to look for:
        (expression_statement
          (call_expression
            function: (identifier)
            arguments: (argument_list ...)))

        TODO: Awkward naming of this method
            
        Args:
            expr_stmt: An expression_statement node
            
        Returns:
            The call_expression node if found, None otherwise
        """
        for child in expr_stmt.children:
            if child.type == "call_expression":
                return child
        return self._find_node_by_type(expr_stmt, "call_expression")
    
    def _is_test_case_call(self, call_expr):
        """Check if a call_expression is a test case function call
        
        Structure to check:
        (call_expression
          function: (identifier)  <-- Should be 'TEST_CASE', 'TEMPLATE_TEST_CASE', etc.
          arguments: (argument_list ...))
          
        Args:
            call_expr: A call_expression node
            
        Returns:
            True if the call is a test case, False otherwise
        """
        function_node = None
        for child in call_expr.children:
            if child.type == "identifier":
                function_node = child
                break
        if not function_node:
            return False
        function_name = function_node.text.decode('utf8')
        return function_name in [
            "TEST_CASE", 
            "TEMPLATE_TEST_CASE",
            "SECTION",
            "SCENARIO",
            "GIVEN",
            "WHEN",
            "THEN"]
    
    def _extract_test_case(self, call_expr, compound_stmt, filepath):
        """Extract test case information from a call_expression and compound_statement
        
        Args:
            call_expr: The call_expression node (TEST_CASE(...))
            compound_stmt: The compound_statement node (the test body)
            filepath: Path to the file being parsed
            
        Returns:
            A dict with test case information or None if extraction fails
        """
        test_case = {
            "kind": None,
            "name": "",
            "tags": "",
            "start_line": call_expr.start_point[0],
            "start_column": call_expr.start_point[1],
            "end_line": compound_stmt.end_point[0],
            "end_column": compound_stmt.end_point[1],
            "references": []
        }
        for child in call_expr.children:
            if child.type == "identifier":
                test_case["kind"] = child.text.decode('utf8')
                break
        args_node = None
        for child in call_expr.children:
            if child.type == "argument_list":
                args_node = child
                break
                
        if args_node:
            description_parts = []
            tag_parts = []
            all_string_parts = []
            for child in args_node.children:
                if child.type == "string_literal":
                    for content_node in child.children:
                        if content_node.type == "string_content":
                            all_string_parts.append(content_node.text.decode('utf8'))
                            break
                elif child.type == "concatenated_string":
                    concatenated_parts = []
                    for string_node in child.children:
                        if string_node.type == "string_literal":
                            for content_node in string_node.children:
                                if content_node.type == "string_content":
                                    concatenated_parts.append(content_node.text.decode('utf8'))
                    if concatenated_parts:
                        all_string_parts.append(' '.join(concatenated_parts))
            
            if len(all_string_parts) >= 1:
                description_parts.append(all_string_parts[0])
                if len(all_string_parts) >= 2:
                    last_part = all_string_parts[-1].strip()
                    if last_part.startswith('['):
                        if len(all_string_parts) > 2:
                            description_parts.extend(all_string_parts[1:-1])
                        tag_parts.append(last_part)
                    else:
                        description_parts.extend(all_string_parts[1:])
            if description_parts:
                test_case["name"] = ' '.join(part.strip() for part in description_parts).strip()
            if tag_parts:
                test_case["tags"] = ' '.join(part.strip() for part in tag_parts).strip()
        test_case["references"] = self._extract_type_references(compound_stmt)
        
        return test_case
    
    def _extract_type_references(self, node):
        """Extract potential type references from a node and its children
        
        Identifies C++ types used in test cases by looking for:
        1. Template types in template instantiations
        2. Identifiers in type declarations (variable/param declarations)
        3. Qualified names that might be types (e.g., Namespace::Type)
        4. Constructor calls
        5. Named type specifiers
        
        Not sure It needs to be this thorough but AI agents wants to be,
        so why not

        Args:
            node: A Tree-sitter node to search within
            
        Returns:
            List of unique identifier strings that might be type references
        """
        references = set()
        if node.type in ["string_literal", "comment", "raw_string_literal", "number_literal"]:
            return list(references)

        # Case 1: Template instantiations
        if node.type == "template_instantiation":
            if len(node.children) > 0:
                template_name = node.children[0].text.decode('utf8')
                if template_name[0].isupper() or "::" in template_name:
                    references.add(template_name)
                for child in node.children:
                    if child.type == "template_argument_list":
                        for arg in child.children:
                            if arg.type == "type_descriptor" or arg.type == "identifier":
                                arg_text = arg.text.decode('utf8')
                                if arg_text and (arg_text[0].isupper() or "::" in arg_text):
                                    references.add(arg_text)
        
        # Case 2: Type declarations in variable declarations
        elif node.type in ["declaration", "parameter_declaration"]:
            for child in node.children:
                if child.type in ["type_identifier", "qualified_identifier"]:
                    type_name = child.text.decode('utf8')
                    if type_name and (type_name[0].isupper() or "::" in type_name):
                        references.add(type_name)
        
        # Case 3: Qualified identifiers (Namespace::Type)
        elif node.type == "qualified_identifier":
            qualified_name = node.text.decode('utf8')
            if "::" in qualified_name:
                parts = qualified_name.split("::") 
                last_part = parts[-1]
                if last_part and last_part[0].isupper():
                    references.add(qualified_name)
        
        # Case 4: Constructor calls (usually have a new_expression or call_expression parent)
        elif node.type == "identifier":
            identifier = node.text.decode('utf8')
            test_framework_functions = ["TEST_CASE", "REQUIRE", "CHECK", "GIVEN", "WHEN", "THEN", 
                                      "SECTION", "INFO", "WARN", "FAIL"]
            cpp_keywords = ["if", "else", "for", "while", "return", "break", "continue", 
                           "switch", "case", "default", "try", "catch", "throw", "using", 
                           "namespace", "public", "private", "protected", "friend", "class", 
                           "struct", "enum", "typedef", "typename", "const", "static", "volatile"]
            if (identifier and identifier[0].isupper() and 
                identifier not in test_framework_functions and 
                identifier not in cpp_keywords):
                parent = node.parent
                if parent and parent.type in ["call_expression", "new_expression", "type_identifier"]:
                    references.add(identifier)
                elif parent and parent.type in ["declaration", "parameter_declaration"]:
                    references.add(identifier)
        
        # Case 5: Named type specifiers (class/struct/enum names)
        elif node.type in ["type_identifier", "scoped_type_identifier"]:
            type_name = node.text.decode('utf8')
            if type_name and (type_name[0].isupper() or "::" in type_name):
                references.add(type_name)
        for child in node.children:
            child_refs = self._extract_type_references(child)
            references.update(child_refs)
        
        return list(references)
    
    def _find_nodes_by_type(self, root_node, node_type):
        """Find all nodes of a specific type in the tree

        Starting to feel tree-sitter should provide most
        of this functionality, but they change their API
        often...
        
        Args:
            root_node: Root node to start searching from
            node_type: Type of nodes to find
            
        Returns:
            List of nodes matching the type
        """
        result = []
        cursor = root_node.walk()
        if root_node.type == node_type:
            result.append(root_node)
        reached_end = False
        while not reached_end:
            if cursor.node.type == node_type:
                result.append(cursor.node)
            if cursor.goto_first_child():
                continue
            reached_end = not cursor.goto_next_sibling()
            if reached_end:
                while not reached_end and not cursor.goto_next_sibling():
                    reached_end = not cursor.goto_parent()
                    if reached_end:
                        break
                        
        return result
    
    def _extract_template_test_case_from_error(self, error_node):
        """Extract TEMPLATE_TEST_CASE information from an ERROR node
        
        Tree-sitter might parse complex template macro calls as ERROR nodes.
        This method tries to extract test information from such nodes.
        
        Args:
            error_node: An ERROR node from the Tree-sitter parse tree
            
        Returns:
            A dict with test case information if this is a TEMPLATE_TEST_CASE, None otherwise
        """
        first_identifier = None
        for child in error_node.children:
            if child.type == "identifier":
                first_identifier = child
                break
        if first_identifier and first_identifier.text.decode('utf8') == "TEMPLATE_TEST_CASE":
            test_name = ""
            for child in error_node.children:
                if child.type == "string_literal":
                    for content_node in child.children:
                        if content_node.type == "string_content":
                            test_name = content_node.text.decode('utf8')
                            break
                    if test_name:
                        break
            template_test_case = {
                "kind": "TEMPLATE_TEST_CASE",
                "name": test_name or "Template Test Case",
                "start_line": error_node.start_point[0],
                "start_column": error_node.start_point[1],
                "end_line": error_node.end_point[0],
                "end_column": error_node.end_point[1],
                "references": []  # Will be filled in by caller if compound statement is found
            }
            logger.info(f"Found TEMPLATE_TEST_CASE in ERROR node: {test_name}")
            return template_test_case
            
        return None
    
    def _find_node_by_type(self, root_node, node_type):
        """Find the first node of a specific type in the tree
        
        Args:
            root_node: Root node to start searching from
            node_type: Type of node to find
            
        Returns:
            The first node matching the type, or None if not found
        """
        if root_node.type == node_type:
            return root_node
        for child in root_node.children:
            result = self._find_node_by_type(child, node_type)
            if result:
                return result
        return None
        
    def find_test_cases(self, filepath: str) -> List[Dict[str, Any]]:
        """Find all test cases in a unit-test file with Tree-Sitter
        
        Args:
            filepath: Path to the file to parse
            
        Returns:
            List of test case information dictionaries
        """
        logger.info(f"Attempting test cases in {filepath} using Tree-sitter")
        
        try:
            with open(filepath, 'rb') as f:
                content = f.read()
                tree = self.parser.parse(content)
            test_cases = []
            root_node = tree.root_node
            current_index = 0
            while current_index < len(root_node.children):
                if current_index + 1 < len(root_node.children):
                    expr_stmt = root_node.children[current_index]
                    next_node = root_node.children[current_index + 1]
                    if expr_stmt.type == "expression_statement" and next_node.type == "compound_statement":
                        call_expr = self._find_call_expression(expr_stmt)
                        if call_expr and self._is_test_case_call(call_expr):
                            test_case = self._extract_test_case(call_expr, next_node, filepath)
                            if test_case:
                                test_cases.append(test_case)
                            current_index += 2  # Move past both nodes
                            continue
                current_index += 1
            logger.info(f"Found {len(test_cases)} test cases in {filepath}")
            return test_cases
        except Exception as e:
            logger.error(f"Error finding test cases in {filepath}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []


def is_tree_sitter_available() -> bool:
    """Check if Tree-sitter is available
    
    Returns:
        True if Tree-sitter is available, False otherwise
    """
    return TREE_SITTER_AVAILABLE


if __name__ == "__main__":
    if TREE_SITTER_AVAILABLE:
        parser = TreeSitterSubparser()
        import sys
        if len(sys.argv) > 1:
            filepath = sys.argv[1]
            result = parser.parse_file(filepath)
            print(f"Found {len(result['classes'])} classes, {len(result['functions'])} functions, and {len(result['test_cases'])} test cases in {filepath}")
        else:
            print("Usage: python tree_sitter_subparser.py filepath")
    else:
        print("Tree-sitter is not available.")
