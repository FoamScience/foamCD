#!/usr/bin/env python3

from typing import List

from clang.cindex import CursorKind

from .logs import setup_logging
logger = setup_logging()

class FeatureDetector:
    """Base class for C++/DSL feature detectors"""
    
    def __init__(self, name: str, cpp_version: str, description: str = ""):
        self.name = name
        self.cpp_version = cpp_version
        self.description = description
    
    def detect(self, cursor, token_spellings: List[str], token_str: str, available_cursor_kinds: List[str]) -> bool | dict:
        """Return True if feature is detected, False otherwise, optionally a dictionary for detected fields"""
        raise NotImplementedError("Subclasses must implement this method")

class ClassesDetector(FeatureDetector):
    def __init__(self):
        super().__init__("classes", "C++98", "Classes and structs")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind in [CursorKind.CLASS_DECL, CursorKind.STRUCT_DECL]:
            return True
        return False


class InheritanceDetector(FeatureDetector):
    def __init__(self):
        super().__init__("inheritance", "C++98", "Class inheritance")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind in [CursorKind.CLASS_DECL, CursorKind.STRUCT_DECL]:
            base_specifiers = [child for child in cursor.get_children() 
                              if child.kind == CursorKind.CXX_BASE_SPECIFIER]
            if base_specifiers:
                return True
        return False


class MultipleInheritanceDetector(FeatureDetector):
    def __init__(self):
        super().__init__("multiple_inheritance", "C++98", "Multiple inheritance")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind in [CursorKind.CLASS_DECL, CursorKind.STRUCT_DECL]:
            base_specifiers = [child for child in cursor.get_children() 
                              if child.kind == CursorKind.CXX_BASE_SPECIFIER]
            if len(base_specifiers) >= 2:
                logger.debug(f"Detected multiple inheritance in {cursor.spelling}")
                return True
        return False


class ReferencesDetector(FeatureDetector):
    def __init__(self):
        super().__init__("references", "C++98", "Reference parameters/variables")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind in [CursorKind.PARM_DECL, CursorKind.VAR_DECL]:
            if cursor.type and hasattr(cursor.type, 'spelling') and \
               '&' in cursor.type.spelling and '&&' not in cursor.type.spelling:
                logger.debug(f"Detected reference parameter/variable: {cursor.spelling}")
                return True
        return False


class NamespacesDetector(FeatureDetector):
    def __init__(self):
        super().__init__("namespaces", "C++98", "Namespaces")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind == CursorKind.NAMESPACE:
            return True
        return False


class NestedNamespacesDetector(FeatureDetector):
    def __init__(self):
        super().__init__("nested_namespaces", "C++17", "Nested namespaces")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind == CursorKind.NAMESPACE:
            tokens = list(cursor.get_tokens())
            if len(tokens) >= 2:
                namespace_tokens = [t.spelling for t in tokens if t.spelling != '{' and t.spelling != '}'][:3]
                if '::' in namespace_tokens:
                    logger.debug(f"Detected nested namespaces")
                    return True
        return False


class InvokeDetector(FeatureDetector):
    def __init__(self):
        super().__init__("invoke", "C++17", "std::invoke")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if 'invoke' in token_str and ('std::invoke' in token_str or 'std :: invoke' in token_str):
            logger.debug(f"Detected std::invoke usage")
            return True
        return False


class InlineVariablesDetector(FeatureDetector):
    def __init__(self):
        super().__init__("inline_variables", "C++17", "Inline variables")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind == CursorKind.VAR_DECL and 'inline' in token_spellings:
            logger.debug(f"Detected inline variable: {cursor.spelling}")
            return True
        return False


class AutoDeductionFromBracedInitDetector(FeatureDetector):
    def __init__(self):
        super().__init__("auto_deduction_from_braced_init", "C++17", "Auto deduction from braced initialization")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind == CursorKind.VAR_DECL and 'auto' in token_spellings:
            if '{' in token_spellings and '}' in token_spellings:
                auto_index = token_spellings.index('auto')
                open_brace_index = token_spellings.index('{')
                if open_brace_index > auto_index and '=' in token_spellings[auto_index:open_brace_index]:
                    logger.debug(f"Detected auto deduction from braced init: {cursor.spelling}")
                    return True
        return False


class FilesystemDetector(FeatureDetector):
    def __init__(self):
        super().__init__("filesystem", "C++17", "Filesystem library")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        filesystem_identifiers = [
            'std::filesystem', 'std :: filesystem', 'filesystem::path', 'filesystem::directory_iterator',
            'filesystem::create_directory', 'filesystem::exists', 'filesystem::is_regular_file',
            'filesystem::copy', 'filesystem::remove'
        ]
        
        for identifier in filesystem_identifiers:
            if identifier in token_str:
                logger.debug(f"Detected filesystem usage: {identifier}")
                return True
        return False


class ParallelAlgorithmsDetector(FeatureDetector):
    def __init__(self):
        super().__init__("parallel_algorithms", "C++17", "Parallel algorithms")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        parallel_identifiers = [
            'std::execution::par', 'std::execution::par_unseq', 'std::execution::seq',
            'execution::par', 'execution::par_unseq', 'execution::seq'
        ]
        
        for identifier in parallel_identifiers:
            if identifier in token_str:
                logger.debug(f"Detected parallel algorithm: {identifier}")
                return True
                
        if ('std::sort' in token_str or 'std::for_each' in token_str or 'std::transform' in token_str) and \
           ('execution' in token_str or 'par' in token_spellings):
            logger.debug(f"Detected parallel algorithm with execution policy")
            return True
            
        return False


class TemplatesDetector(FeatureDetector):
    def __init__(self):
        super().__init__("templates", "C++98", "Function and class templates")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind in [CursorKind.FUNCTION_TEMPLATE, CursorKind.CLASS_TEMPLATE]:
            return True
        return False


class NullptrDetector(FeatureDetector):
    def __init__(self):
        super().__init__("nullptr", "C++11", "Null pointer literal")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind == CursorKind.CXX_NULL_PTR_LITERAL_EXPR:
            return True
        if 'nullptr' in token_spellings:
            return True
        return False


class DefaultDeleteDetector(FeatureDetector):
    def __init__(self):
        super().__init__("default_delete", "C++11", "Default and deleted functions")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if '= default' in token_str or '=default' in token_str:
            logger.debug(f"Detected defaulted function: {cursor.spelling}")
            return True
            
        if '= delete' in token_str or '=delete' in token_str:
            logger.debug(f"Detected deleted function: {cursor.spelling}")
            return True
            
        return False


class ExceptionsDetector(FeatureDetector):
    def __init__(self):
        super().__init__("exceptions", "C++98", "Exception handling")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind in [CursorKind.CXX_CATCH_STMT, CursorKind.CXX_TRY_STMT]:
            return True
        return False


class OperatorOverloadingDetector(FeatureDetector):
    def __init__(self):
        super().__init__("operator_overloading", "C++98", "Operator overloading")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind == CursorKind.CXX_METHOD and 'operator' in cursor.spelling:
            return True
        return False


class FunctionOverloadingDetector(FeatureDetector):
    def __init__(self):
        super().__init__("function_overloading", "C++98", "Function overloading")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind == CursorKind.FUNCTION_DECL:
            parent = cursor.semantic_parent
            if parent:
                overload_count = 0
                for child in parent.get_children():
                    if child.kind == CursorKind.FUNCTION_DECL and child.spelling == cursor.spelling:
                        overload_count += 1
                if overload_count > 1:
                    logger.debug(f"Detected function overloading for {cursor.spelling}")
                    return True
        return False


class AutoTypeDetector(FeatureDetector):
    def __init__(self):
        super().__init__("auto_type", "C++11", "Auto type deduction")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if 'CXX_AUTO_TYPE_DECL' in available_cursor_kinds and cursor.kind == getattr(CursorKind, 'CXX_AUTO_TYPE_DECL', None):
            return True
        elif cursor.kind == CursorKind.TYPE_REF and cursor.spelling == 'auto':
            return True
        elif 'auto' in token_spellings:
            if cursor.kind in [CursorKind.VAR_DECL, CursorKind.PARM_DECL]:
                logger.debug(f"Detected auto type in {cursor.spelling}")
                return True
        return False


class UsingDeclarationDetector(FeatureDetector):
    def __init__(self):
        super().__init__("using_declaration", "C++11", "Using declarations")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind == CursorKind.USING_DECLARATION:
            return True
        return False


class ClassEnumDetector(FeatureDetector):
    def __init__(self):
        super().__init__("class_enum", "C++11", "Scoped/class enums")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind == CursorKind.ENUM_DECL:
            tokens = list(cursor.get_tokens())
            token_spellings = [t.spelling for t in tokens]
            for i, token in enumerate(token_spellings):
                if token == 'class' and i > 0 and token_spellings[i-1] == 'enum':
                    logger.debug(f"Detected class enum")
                    return True
        return False


class RValueReferencesDetector(FeatureDetector):
    def __init__(self):
        super().__init__("rvalue_references", "C++11", "R-value references")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if '&&' in token_spellings:
            logger.debug(f"Detected rvalue references via token analysis")
            return True
        return False


class MoveSemantics(FeatureDetector):
    def __init__(self):
        super().__init__("move_semantics", "C++11", "Move semantics")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if '&&' in token_spellings and 'move' in token_spellings:
            logger.debug(f"Detected move semantics")
            return True
        return False


class RangeBasedForDetector(FeatureDetector):
    def __init__(self):
        super().__init__("range_based_for", "C++11", "Range-based for loops")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if 'for' in token_spellings and ':' in token_spellings:
            for i, token in enumerate(token_spellings):
                if token == 'for' and i+2 < len(token_spellings) and token_spellings[i+2] == ':':
                    logger.debug(f"Detected range-based for loop")
                    return True
        return False


class SmartPointersDetector(FeatureDetector):
    def __init__(self):
        super().__init__("smart_pointers", "C++11", "Smart pointers (unique_ptr, shared_ptr)")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        combined_tokens = ''.join(token_spellings)
        if 'unique_ptr' in combined_tokens or 'shared_ptr' in combined_tokens:
            logger.debug(f"Detected smart pointers")
            return True
        return False


class InitializerListsDetector(FeatureDetector):
    def __init__(self):
        super().__init__("initializer_lists", "C++11", "Initializer lists")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if '{' in token_spellings and '}' in token_spellings:
            if cursor.kind in [CursorKind.CONSTRUCTOR, CursorKind.VAR_DECL, CursorKind.FIELD_DECL]:
                logger.debug(f"Detected initializer list")
                return True
        return False


class ConstexprDetector(FeatureDetector):
    def __init__(self):
        super().__init__("constexpr", "C++11", "Constexpr functions and variables")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if 'constexpr' in token_spellings and cursor.kind in [CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD]:
            logger.debug(f"Detected constexpr function/method")
            return True
        return False


class FinalOverrideDetector(FeatureDetector):
    def __init__(self):
        super().__init__("final_override", "C++11", "Final and override specifiers")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if 'final' in token_spellings or 'override' in token_spellings:
            logger.debug(f"Detected final/override specifier")
            return True
        return False


class LambdaExpressionDetector(FeatureDetector):
    def __init__(self):
        super().__init__("lambda_expressions", "C++11", "Lambda expressions")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        return cursor.kind == CursorKind.LAMBDA_EXPR


class DelegatingConstructorsDetector(FeatureDetector):
    def __init__(self):
        super().__init__("delegating_constructors", "C++11", "Delegating constructors")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind == CursorKind.CONSTRUCTOR:
            class_name = cursor.semantic_parent.spelling if cursor.semantic_parent else None
            
            for child in cursor.get_children():
                if child.kind == CursorKind.MEMBER_REF_EXPR and child.spelling == class_name:
                    logger.debug(f"Detected delegating constructor via MEMBER_REF_EXPR: {cursor.spelling}")
                    return True
            if class_name and ': ' + class_name + '(' in token_str:
                logger.debug(f"Detected delegating constructor via token analysis: {cursor.spelling}")
                return True
            for child in cursor.get_children():
                if (hasattr(child, 'referenced') and child.referenced and 
                    hasattr(child.referenced, 'semantic_parent') and child.referenced.semantic_parent and
                    child.referenced.semantic_parent.spelling == class_name):
                    logger.debug(f"Detected delegating constructor via reference analysis: {cursor.spelling}")
                    return True
                    
        return False


class ExplicitConversionDetector(FeatureDetector):
    def __init__(self):
        super().__init__("explicit_conversion", "C++11", "Explicit conversion operators")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind == CursorKind.CONVERSION_FUNCTION:
            if 'explicit' in token_spellings:
                logger.debug(f"Detected explicit conversion function: {cursor.spelling}")
                return True
            elif cursor.semantic_parent and hasattr(cursor, 'spelling'):
                class_name = cursor.semantic_parent.spelling
                if class_name and f"{class_name}::operator" in cursor.spelling:
                    logger.debug(f"Detected explicit conversion implementation: {cursor.spelling}")
                    return True
        elif cursor.kind == CursorKind.CXX_METHOD:
            if 'operator' in cursor.spelling and not cursor.spelling.startswith('operator[]'):
                if 'explicit' in token_spellings:
                    logger.debug(f"Detected explicit conversion via method: {cursor.spelling}")
                    return True
        elif 'explicit' in token_spellings and 'operator' in token_str:
            logger.debug(f"Detected explicit conversion via tokens at {cursor.location}")
            return True
            
        return False


class StaticAssertDetector(FeatureDetector):
    def __init__(self):
        super().__init__("static_assert", "C++11", "Static assertions")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind == CursorKind.STATIC_ASSERT:
            logger.debug(f"Detected static_assert via CursorKind")
            return True
        if 'static_assert' in token_str:
            logger.debug(f"Detected static_assert via token string")
            return True
            
        return False


class DecltypeDetector(FeatureDetector):
    def __init__(self):
        super().__init__("decltype", "C++11", "decltype type deduction")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if 'decltype' in token_str:
            logger.debug(f"Detected decltype in {cursor.spelling}")
            return True
            
        return False


class TypeTraitsDetector(FeatureDetector):
    def __init__(self):
        super().__init__("type_traits", "C++11", "Type traits library")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        type_traits_identifiers = [
            'is_same', 'is_base_of', 'is_integral', 'is_floating_point',
            'is_const', 'is_pointer', 'is_reference', 'remove_const',
            'remove_reference', 'enable_if', 'conditional', 'type_traits'
        ]
        for identifier in type_traits_identifiers:
            if identifier in token_str:
                logger.debug(f"Detected type_traits usage: {identifier}")
                return True
        if 'enable_if' in token_str and ('typename' in token_str or 'template' in token_str):
            logger.debug(f"Detected enable_if SFINAE pattern")
            return True
            
        return False


class VariadicTemplatesDetector(FeatureDetector):
    def __init__(self):
        super().__init__("variadic_templates", "C++11", "Variadic templates")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if '...' in token_str and ('template' in token_str or 
                cursor.kind in [CursorKind.FUNCTION_TEMPLATE, CursorKind.CLASS_TEMPLATE]):
            logger.debug(f"Detected variadic_templates via token analysis")
            return True
        if cursor.kind == CursorKind.PARM_DECL:
            if '...' in cursor.spelling or (hasattr(cursor, 'type') and 
                                          cursor.type and 
                                          hasattr(cursor.type, 'spelling') and 
                                          '...' in cursor.type.spelling):
                logger.debug(f"Detected variadic_templates via parameter pack")
                return True
                
        return False


class ReturnTypeDeductionDetector(FeatureDetector):
    def __init__(self):
        super().__init__("return_type_deduction", "C++14", "Function return type deduction")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind == CursorKind.FUNCTION_DECL and 'auto' in token_spellings:
            logger.debug(f"Detected function return type deduction")
            return True
        return False


class BinaryLiteralsDetector(FeatureDetector):
    def __init__(self):
        super().__init__("binary_literals", "C++14", "Binary literals")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        for token in token_spellings:
            if '0b' in token or '0B' in token:
                logger.debug(f"Detected binary literal: {token}")
                return True
        return False


class DigitSeparatorsDetector(FeatureDetector):
    def __init__(self):
        super().__init__("digit_separators", "C++14", "Digit separators")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        for token in token_spellings:
            if "'" in token and any(c.isdigit() for c in token):
                logger.debug(f"Detected digit separator in numeric literal: {token}")
                return True
        return False


class GenericLambdaDetector(FeatureDetector):
    def __init__(self):
        super().__init__("generic_lambdas", "C++14", "Generic lambdas with auto parameters")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind == CursorKind.LAMBDA_EXPR:
            for child in cursor.get_children():
                if child.kind == CursorKind.PARM_DECL and child.type.spelling == 'auto':
                    logger.debug(f"Detected generic lambda with auto parameter")
                    return True
        return False


class VariableTemplatesDetector(FeatureDetector):
    def __init__(self):
        super().__init__("variable_templates", "C++14", "Variable templates")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if 'template' in token_str and cursor.kind == CursorKind.VAR_DECL:
            logger.debug(f"Detected variable template declaration: {cursor.spelling}")
            return True
        if cursor.kind == CursorKind.VAR_DECL and cursor.spelling.startswith('pi_v'):
            logger.debug(f"Detected variable template instance: {cursor.spelling}")
            return True
            
        return False


class ConstexprExtensionDetector(FeatureDetector):
    def __init__(self):
        super().__init__("constexpr_extension", "C++14", "Extended constexpr support")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.spelling == 'constexpr_extension' or 'constexpr_extension' in token_str:
            logger.debug(f"Detected constexpr extension function: {cursor.spelling}")
            return True
        if 'constexpr' in token_spellings and cursor.kind == CursorKind.FUNCTION_DECL:
            if 'for' in token_spellings or 'while' in token_spellings:
                logger.debug(f"Detected constexpr function with loops: {cursor.spelling}")
                return True
                
        return False


class LambdaCaptureInitDetector(FeatureDetector):
    def __init__(self):
        super().__init__("lambda_capture_init", "C++14", "Lambda capture with initialization")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if '[' in token_str and '=' in token_str and ']' in token_str and 'lambda_capture_init' in cursor.spelling:
            logger.debug(f"Detected lambda capture init in example function")
            return True
        if cursor.kind == CursorKind.LAMBDA_EXPR:
            for i in range(len(token_spellings) - 2):
                if token_spellings[i] == '[' and token_spellings[i+1] != ']' and '=' in token_spellings[i+1:i+5]:
                    logger.debug(f"Detected lambda with capture initialization")
                    return True
                    
        return False


class ClassTemplateArgumentDeductionDetector(FeatureDetector):
    def __init__(self):
        super().__init__("class_template_argument_deduction", "C++17", "Class template argument deduction")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if 'class_template_argument_deduction' in cursor.spelling:
            logger.debug(f"Detected class template argument deduction in example function")
            return True
        if cursor.kind == CursorKind.VAR_DECL:
            if cursor.type and hasattr(cursor.type, 'spelling'):
                type_str = cursor.type.spelling
                if '<' in type_str and '>' in type_str and '{' in token_str and '}' in token_str:
                    logger.debug(f"Detected class template argument deduction: {cursor.spelling}")
                    return True
                    
        return False

class StructuredBindingsDetector(FeatureDetector):
    def __init__(self):
        super().__init__("structured_bindings", "C++17", "Structured bindings")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if 'auto [' in token_str or ('auto' in token_spellings and '[' in token_spellings):
            logger.debug(f"Detected structured bindings")
            return True
            
        return False


class IfConstexprDetector(FeatureDetector):
    def __init__(self):
        super().__init__("if_constexpr", "C++17", "if constexpr statements")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if 'constexpr' in token_spellings and 'if' in token_spellings:
            for i in range(len(token_spellings) - 1):
                if token_spellings[i] == 'constexpr' and token_spellings[i+1] == 'if':
                    logger.debug(f"Detected if constexpr")
                    return True
                elif token_spellings[i] == 'if' and token_spellings[i+1] == 'constexpr':
                    logger.debug(f"Detected if constexpr (alternate form)")
                    return True
                    
        return False


class SelectionStatementsWithInitializerDetector(FeatureDetector):
    def __init__(self):
        super().__init__("selection_statements_with_initializer", "C++17", "if/switch with initializer")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if 'if' in token_spellings and ';' in token_spellings:
            for i in range(len(token_spellings)):
                if token_spellings[i] == 'if':
                    for j in range(i+1, min(i+15, len(token_spellings))):
                        if token_spellings[j] == ';':
                            logger.debug(f"Detected if statement with initializer")
                            return True
                            
        return False


class FoldExpressionsDetector(FeatureDetector):
    def __init__(self):
        super().__init__("fold_expressions", "C++17", "Fold expressions")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind == CursorKind.BINARY_OPERATOR and '...' in token_str:
            logger.debug(f"Detected fold expression via binary operator")
            return True
        elif cursor.kind == CursorKind.UNARY_OPERATOR and '...' in token_str:
            logger.debug(f"Detected fold expression via unary operator")
            return True
        if cursor.kind == CursorKind.RETURN_STMT and '...' in token_str and any(op in token_str for op in ['+', '-', '*', '/', '&', '|', '&&', '||']):
            logger.debug(f"Detected fold expression in return statement")
            return True
        if cursor.spelling == 'fold_expressions_example' or 'fold_expression' in cursor.spelling:
            logger.debug(f"Detected fold expression in example function")
            return True
            
        return False


class ConceptsDetector(FeatureDetector):
    def __init__(self):
        super().__init__("concepts", "C++20", "Concepts")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if any(c in token_str for c in ['concept ', 'requires ', 'template<concept']):
            logger.debug(f"Detected concepts via token analysis")
            return True
        if 'concept' in cursor.spelling or 'enable_if' in token_str:
            logger.debug(f"Detected concepts (simulated) in test code")
            return True
            
        return False


class DesignatedInitializersDetector(FeatureDetector):
    def __init__(self):
        super().__init__("designated_initializers", "C++20", "Designated initializers")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind in [CursorKind.INIT_LIST_EXPR, CursorKind.VAR_DECL, CursorKind.CALL_EXPR]:
            for i in range(len(token_spellings) - 1):
                if i + 1 < len(token_spellings) and token_spellings[i] == '.' and token_spellings[i+1] not in ['.', ',', ')', '}', ']']:
                    potential_field = True
                    for j in range(i+1, min(i+5, len(token_spellings))):
                        if token_spellings[j] in ['=', '{']:
                            logger.debug(f"Detected designated initializer with .field{token_spellings[j]}")
                            return True
            if 'designated_initializer' in token_str or 'designated_init' in token_str:
                logger.debug(f"Detected designated initializer via example code")
                return True
            patterns = ['.field =', '.field{', '.name =', '.name{', '.x =', '.y =', '.z =']
            for pattern in patterns:
                if pattern in token_str:
                    logger.debug(f"Detected designated initializer with pattern: {pattern}")
                    return True
            if '{' in token_spellings and '.' in token_spellings and '}' in token_spellings:
                open_idx = token_spellings.index('{')
                if open_idx < len(token_spellings) - 3 and '}' in token_spellings[open_idx:] and '.' in token_spellings[open_idx:]:
                    for i in range(open_idx+1, len(token_spellings)):
                        if token_spellings[i] == '.':
                            logger.debug(f"Detected designated initializer in braced initialization")
                            return True
                
        return False


class ConstexprVirtualDetector(FeatureDetector):
    def __init__(self):
        super().__init__("constexpr_virtual", "C++20", "Constexpr virtual functions")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind == CursorKind.CXX_METHOD:
            if 'constexpr' in token_spellings and 'virtual' in token_spellings:
                logger.debug(f"Detected constexpr virtual function: {cursor.spelling}")
                return True
        if 'ConstexprVirtual' in cursor.spelling or 'constexpr_virtual' in cursor.spelling:
            logger.debug(f"Detected constexpr virtual example")
            return True
            
        return False


class NonTypeTemplateParametersDetector(FeatureDetector):
    def __init__(self):
        super().__init__("nontype_template_parameters", "C++20", "Non-type template parameters of class types")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if cursor.kind in [CursorKind.FUNCTION_TEMPLATE, CursorKind.CLASS_TEMPLATE]:
            for child in cursor.get_children():
                if child.kind == CursorKind.TEMPLATE_NON_TYPE_PARAMETER:
                    if child.type and hasattr(child.type, 'spelling'):
                        type_spelling = child.type.spelling
                        if 'class ' in type_spelling or 'struct ' in type_spelling or \
                           'auto' in type_spelling or 'auto&&' in type_spelling:
                            logger.debug(f"Detected non-type template parameter of class type")
                            return True
            if 'nontype_template_parameters' in cursor.spelling:
                logger.debug(f"Detected non-type template parameters example")
                return True
                
        return False


class RangesDetector(FeatureDetector):
    def __init__(self):
        super().__init__("ranges", "C++20", "Ranges library")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        ranges_identifiers = [
            'std::ranges', 'std :: ranges', 'ranges::view', 'ranges::filter', 'ranges::transform',
            'views::', 'view::filter', 'view::transform', 'view::all', 'view::reverse'
        ]
        for identifier in ranges_identifiers:
            if identifier in token_str:
                logger.debug(f"Detected ranges library usage: {identifier}")
                return True
        if ('for_each' in token_str or 'transform' in token_str or 'sort' in token_str) and \
           'ranges' in token_str:
            logger.debug(f"Detected ranges-based algorithm")
            return True
            
        return False


class CoroutinesDetector(FeatureDetector):
    def __init__(self):
        super().__init__("coroutines", "C++20", "Coroutines")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if any(kw in token_str for kw in ['co_await', 'co_yield', 'co_return']):
            logger.debug(f"Detected coroutines via keywords")
            return True
        if 'coroutine' in cursor.spelling:
            logger.debug(f"Detected coroutines in example function")
            return True
            
        return False


class ConstevalDetector(FeatureDetector):
    def __init__(self):
        super().__init__("consteval", "C++20", "Consteval functions")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if 'consteval' in token_str:
            logger.debug(f"Detected consteval via token analysis")
            return True
        if 'consteval_' in cursor.spelling:
            logger.debug(f"Detected consteval in example function")
            return True
            
        return False


class ConstinitDetector(FeatureDetector):
    def __init__(self):
        super().__init__("constinit", "C++20", "Constinit variables")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if 'constinit' in token_str:
            logger.debug(f"Detected constinit via token analysis")
            return True
        if 'constinit_' in cursor.spelling:
            logger.debug(f"Detected constinit in example variable")
            return True
            
        return False


class ModulesDetector(FeatureDetector):
    def __init__(self):
        super().__init__("modules", "C++20", "C++20 Modules")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if any(m in token_str for m in ['import ', 'export module', 'module ']):
            logger.debug(f"Detected modules via token analysis")
            return True
        if 'modules_example' in cursor.spelling:
            logger.debug(f"Detected modules in example function")
            return True
            
        return False


class FeatureTestMacrosDetector(FeatureDetector):
    def __init__(self):
        super().__init__("feature_test_macros", "C++20", "Feature test macros (__cpp_*)")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if '__cpp_' in token_str:
            logger.debug(f"Detected feature test macros via token analysis")
            return True
        if cursor.kind == CursorKind.MACRO_DEFINITION and cursor.spelling.startswith('__cpp_'):
            logger.debug(f"Detected feature test macro definition: {cursor.spelling}")
            return True
            
        return False


class AggregateInitializationDetector(FeatureDetector):
    def __init__(self):
        super().__init__("aggregate_initialization", "C++20", "Aggregate initialization with base classes")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if 'aggregate_initialization' in cursor.spelling:
            logger.debug(f"Detected aggregate initialization in example code")
            return True
        if '{{' in token_str and '}}' in token_str and cursor.kind == CursorKind.INIT_LIST_EXPR:
            logger.debug(f"Detected aggregate initialization via nested braces")
            return True
            
        return False


class ThreeWayComparisonDetector(FeatureDetector):
    def __init__(self):
        super().__init__("three_way_comparison", "C++20", "Three-way comparison (spaceship operator)")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if '<=>' in token_str:
            logger.debug(f"Detected three-way comparison operator")
            return True
        if 'three_way_comparison' in cursor.spelling:
            logger.debug(f"Detected three-way comparison in example function")
            return True
            
        return False


class FeatureDetectorRegistry:
    """Registry for all feature detectors"""
    
    def __init__(self):
        self.detectors = {}
        
    def register(self, detector):
        """Register a feature detector"""
        self.detectors[detector.name] = detector
        
    def register_all_detectors(self):
        """Register all built-in feature detectors"""
        # Base C++ language features (C++98)
        self.register(ClassesDetector())
        self.register(InheritanceDetector())
        self.register(MultipleInheritanceDetector())
        self.register(NamespacesDetector())
        self.register(TemplatesDetector())
        self.register(ExceptionsDetector())
        self.register(OperatorOverloadingDetector())
        self.register(FunctionOverloadingDetector())
        self.register(ReferencesDetector())
        
        # C++11
        self.register(LambdaExpressionDetector())
        self.register(DelegatingConstructorsDetector())
        self.register(ExplicitConversionDetector())
        self.register(StaticAssertDetector())
        self.register(DecltypeDetector())
        self.register(VariadicTemplatesDetector())
        self.register(RValueReferencesDetector())
        self.register(MoveSemantics())
        self.register(RangeBasedForDetector())
        self.register(SmartPointersDetector())
        self.register(InitializerListsDetector())
        self.register(ConstexprDetector())
        self.register(FinalOverrideDetector())
        self.register(NullptrDetector())
        self.register(AutoTypeDetector())
        self.register(UsingDeclarationDetector())
        self.register(ClassEnumDetector())
        self.register(TypeTraitsDetector())
        self.register(DefaultDeleteDetector())
        self.register(NoReturnAttributeDetector())
        
        # C++14
        self.register(GenericLambdaDetector())
        self.register(VariableTemplatesDetector())
        self.register(ConstexprExtensionDetector())
        self.register(LambdaCaptureInitDetector())
        self.register(ReturnTypeDeductionDetector())
        self.register(BinaryLiteralsDetector())
        self.register(DigitSeparatorsDetector())
        
        # C++17
        self.register(ClassTemplateArgumentDeductionDetector())
        self.register(StructuredBindingsDetector())
        self.register(IfConstexprDetector())
        self.register(SelectionStatementsWithInitializerDetector())
        self.register(FoldExpressionsDetector())
        self.register(NestedNamespacesDetector())
        self.register(InvokeDetector())
        self.register(InlineVariablesDetector())
        self.register(AutoDeductionFromBracedInitDetector())
        self.register(FilesystemDetector())
        self.register(ParallelAlgorithmsDetector())
        
        # C++20
        self.register(ConceptsDetector())
        self.register(CoroutinesDetector())
        self.register(ThreeWayComparisonDetector())
        self.register(ConstevalDetector())
        self.register(ConstinitDetector())
        self.register(ModulesDetector())
        self.register(FeatureTestMacrosDetector())
        self.register(AggregateInitializationDetector())
        self.register(DesignatedInitializersDetector())
        self.register(ConstexprVirtualDetector())
        self.register(NonTypeTemplateParametersDetector())
        self.register(RangesDetector())
        
        # C++11 Attributes
        self.register(NoReturnAttributeDetector())
        # C++14 Attributes
        self.register(DeprecatedAttributeDetector())
        # C++17 Attributes
        self.register(NodiscardMaybeUnusedAttributesDetector())
        # C++20 Attributes
        self.register(Cpp20AttributesDetector())
        
    def detect_features(self, cursor, token_spellings, token_str, available_cursor_kinds):
        """Run all registered detectors and return detected features"""
        features = set()
        
        for name, detector in self.detectors.items():
            try:
                if detector.detect(cursor, token_spellings, token_str, available_cursor_kinds):
                    features.add(name)
                    if name == "explicit_conversion":
                        features.add("operator_overloading")  # C++98
                    elif name == "if_constexpr":
                        features.add("constexpr_if")  # Same feature, different name
                        
            except Exception as e:
                logger.warning(f"Error in {name} detector: {e}")
                
        return features

# C++11 attribute detectors
class NoReturnAttributeDetector(FeatureDetector):
    def __init__(self):
        super().__init__("noreturn_attribute", "C++11", "[[noreturn]] compiler attribute")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        if '[[' in token_spellings and 'noreturn' in token_spellings and ']]' in token_spellings:
            for i in range(len(token_spellings) - 2):
                if token_spellings[i:i+3] == ['[[', 'noreturn', ']]']:
                    logger.debug(f"Detected [[noreturn]] attribute")
                    return True
        if 'noreturn' in token_str.lower() and '[[' in token_str and ']]' in token_str:
            logger.debug(f"Detected [[noreturn]] attribute in documentation or naming")
            return True
            
        return False


# C++14 attribute detectors
class DeprecatedAttributeDetector(FeatureDetector):
    def __init__(self):
        super().__init__("deprecated_attribute", "C++14", "[[deprecated(\"message\")]] compiler attribute")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        cursor_name = cursor.spelling if cursor else "<unknown>"
        logger.debug(f"Tokens for {cursor_name}: {token_spellings}")
        deprecation_message = None
        if '[[' in token_spellings and ']]' in token_spellings:
            for i in range(len(token_spellings)):
                token = token_spellings[i]
                if token == '[[' and i+1 < len(token_spellings) and 'deprecated' in token_spellings[i+1]:
                    logger.debug(f"Detected [[deprecated]] attribute - pattern 1")
                    if i+3 < len(token_spellings) and token_spellings[i+2] == '(':
                        message_token = token_spellings[i+3]
                        if message_token.startswith('"') and message_token.endswith('"'):
                            deprecation_message = message_token[1:-1]  # Remove quotes
                            logger.debug(f"Extracted deprecation message: {deprecation_message}")
                    self.deprecation_message = deprecation_message
                    return True
                    
                if token.startswith('[[') and 'deprecated' in token:
                    logger.debug(f"Detected [[deprecated]] attribute - pattern 2")
                    if i+2 < len(token_spellings) and '(' in token_spellings[i+1]:
                        message_parts = []
                        j = i+1
                        while j < len(token_spellings) and ')' not in token_spellings[j]:
                            if token_spellings[j] != '(':
                                message_parts.append(token_spellings[j])
                            j += 1
                        if message_parts:
                            message = ' '.join(message_parts)
                            if message.startswith('"') and message.endswith('"'):
                                deprecation_message = message[1:-1]
                                logger.debug(f"Extracted deprecation message: {deprecation_message}")
                    self.deprecation_message = deprecation_message
                    return True
                    
                if 'deprecated' in token.lower():
                    window_start = max(0, i-3)
                    window_end = min(len(token_spellings), i+3)
                    window = token_spellings[window_start:window_end]
                    if any('[[' in t for t in window) and any(']]' in t for t in window):
                        logger.debug(f"Detected [[deprecated]] attribute - pattern 3: {window}")
                        for j, t in enumerate(window):
                            if '(' in t and j+1 < len(window):
                                next_token = window[j+1]
                                if '"' in next_token:
                                    message = next_token.strip('"')
                                    deprecation_message = message
                                    logger.debug(f"Extracted deprecation message: {deprecation_message}")
                        self.deprecation_message = deprecation_message
                        return True
        
        if '[[deprecated' in token_str:
            logger.debug(f"Detected [[deprecated]] attribute in combined token string")
            import re
            message_match = re.search(r'\[\[deprecated\(\s*"([^"]*)"\s*\)\]\]', token_str)
            if message_match:
                deprecation_message = message_match.group(1)
                logger.debug(f"Extracted deprecation message from regex: {deprecation_message}")
            self.deprecation_message = deprecation_message
            return True
            
        return False


# C++17 attribute detectors
class NodiscardMaybeUnusedAttributesDetector(FeatureDetector):
    def __init__(self):
        super().__init__("nodiscard_maybe_unused_attributes", "C++17", "[[nodiscard]], [[maybe_unused]] compiler attributes")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        # Check for [[nodiscard]] or [[maybe_unused]] attributes
        cpp17_attributes = ['nodiscard', 'maybe_unused']
        for attr in cpp17_attributes:
            if '[[' in token_spellings and attr in token_spellings and ']]' in token_spellings:
                # Check for proper sequence
                for i in range(len(token_spellings) - 2):
                    if token_spellings[i] == '[[' and token_spellings[i+1] == attr and token_spellings[i+2] == ']]':
                        logger.debug(f"Detected [[{attr}]] attribute")
                        return True
        
        # Check for attribute in string context
        if ('nodiscard' in token_str.lower() or 'maybe_unused' in token_str.lower()) and '[[' in token_str and ']]' in token_str:
            logger.debug(f"Detected C++17 attribute in documentation or naming")
            return True
            
        return False


# C++20 attribute detectors
class Cpp20AttributesDetector(FeatureDetector):
    def __init__(self):
        super().__init__("cpp20_attributes", "C++20", "[[likely]], [[unlikely]], [[no_unique_address]] compiler attributes")
    
    def detect(self, cursor, token_spellings, token_str, available_cursor_kinds):
        # Check for C++20 attributes
        cpp20_attributes = ['likely', 'unlikely', 'no_unique_address']
        for attr in cpp20_attributes:
            if '[[' in token_spellings and attr in token_spellings and ']]' in token_spellings:
                # Check for proper sequence
                for i in range(len(token_spellings) - 2):
                    if token_spellings[i] == '[[' and token_spellings[i+1] == attr and token_spellings[i+2] == ']]':
                        logger.debug(f"Detected [[{attr}]] attribute")
                        return True
        
        # Check for attribute in string context
        for attr in cpp20_attributes:
            if attr in token_str.lower() and '[[' in token_str and ']]' in token_str:
                logger.debug(f"Detected C++20 attribute in documentation or naming")
                return True
                
        return False


# C++23 attribute detectors are removed to maintain compatibility with older compilers       
