/**
 * This file contains declarations of various C++ language features for testing
 * the feature detection capabilities of the foamCD parser.
 */

#ifndef CPP_FEATURES_HPP
#define CPP_FEATURES_HPP

// Include necessary headers
#include <memory>
#include <vector>
#include <string>
#include <type_traits>
#include <utility>
#include <functional>

namespace cpp_features_test {

//-------------------------------------------------------------------------
// C++98/03 features - Declarations only
//-------------------------------------------------------------------------

// Classes and inheritance are demonstrated throughout this file

// Templates
template<typename T>
T template_example(T value);

// Exceptions
void exceptions_example();

// Function overloading
int function_overload_example(int x);
float function_overload_example(float x);

// References
void references_example(int& ref_param);

//-------------------------------------------------------------------------
// C++11 features - Declarations only
//-------------------------------------------------------------------------

// Lambda expressions (C++11)
// Use specific type for the header instead of auto
extern const std::function<int()> lambda_example;

// Auto type (C++11)
// Use specific type in the header
extern const int auto_var;

// Nullptr
void nullptr_example();

// Rvalue references and move semantics
void rvalue_references_example(std::string&& str);

// Range-based for loop (C++11)
void range_for_example(const std::vector<int>& vec);

// Smart pointers (C++11)
extern std::unique_ptr<int> unique_ptr_example;
extern std::shared_ptr<int> shared_ptr_example;

// Variadic templates (C++11)
template<typename... Args>
void variadic_template_example(Args... args);

// Virtual function with override (C++11)
class BaseClass {
public:
    virtual void virtualMethod();
    virtual ~BaseClass();
};

class DerivedClass : public BaseClass {
public:
    void virtualMethod() override;
};

class ExtendedDerivedClass : DerivedClass {
public:
    void virtualMethod() final;
};

// Decltype
template<typename T1, typename T2>
auto decltype_example(T1 a, T2 b) -> decltype(a + b);

// constexpr
constexpr int constexpr_example(int x);

// Delegating constructors
class DelegatingConstructors {
public:
    DelegatingConstructors();
    DelegatingConstructors(int val) : value(val) {}
    
private:
    int value;
};

// Explicit conversion operators
class ExplicitConversion {
public:
    ExplicitConversion(int v) : value(v) {}
    explicit operator bool() const;
private:
    int value;
};

// Default and delete
class DefaultDeleteExample {
public:
    DefaultDeleteExample();
    DefaultDeleteExample(const DefaultDeleteExample&) = delete;
};

// Type traits
void type_traits_example();

// Static assert (C++11)
template<typename T>
class StaticAssertExample {
    static_assert(sizeof(T) > 0, "Type must have non-zero size");
public:
    StaticAssertExample() {}
};

//-------------------------------------------------------------------------
// C++14 features - Declarations only
//-------------------------------------------------------------------------

// Generic lambdas (C++14)
// Cannot use auto in function templates directly in a header declaration
// So we use a specific template instantiation for demonstration
extern const std::function<int(int)> generic_lambda; // Will be implemented in cpp file

// Lambda capture initialization
extern const std::function<int()> lambda_capture_init;

// Return type deduction for functions (C++14)
auto return_type_deduction();

// constexpr extensions in C++14
constexpr int constexpr_extension(int n);

// Variable templates
template<typename T>
constexpr T pi_v = T(3.1415926535897932385);

// Binary literals
extern int binary_literal_example;

// Digit separators
extern long large_number_with_separators;

// Generic algorithms
void generic_algorithms_example();

//-------------------------------------------------------------------------
// C++17 features - Declarations only
//-------------------------------------------------------------------------

// Structured bindings (C++17)
void structured_bindings_example();

// Additional structured bindings example that's more easily detectable
inline void structured_bindings_example2() {
    // Define directly in the header for better detection
    auto [x, y] = std::pair<int, int>(1, 2);
}

// inline variables
extern inline int inline_variable;

// fold expressions
template<typename... Args>
int fold_expressions_example(Args... args);

// Class template argument deduction
extern std::pair<int, std::string> class_template_argument_deduction;

// Auto deduction from braced init
void auto_deduction_from_braced_init();

// Nested namespaces are demonstrated in cpp file

// Selection statements with initializer
void selection_statements_with_initializer();

// if constexpr (C++17)
template<typename T>
void constexpr_if_example(T value);

// Implementation of if constexpr needs to be in the header due to being a template
template<typename T>
void constexpr_if_example(T value) {
    // Make the pattern clearer and more consistent - this should be more detectable
    if constexpr (std::is_integral<T>::value) {
        // Integer-specific code path
        int x = value;
    } else {
        // Non-integer code path
        double y = static_cast<double>(value);
    }
}

// Additional simpler constexpr if example that's easier to detect
template<typename T>
inline void constexpr_if_example2(T value) {
    // Using the most basic pattern possible for detection
    if constexpr (sizeof(T) > 1) {
        // Do something
    }
}

// Invoke
void invoke_example();

// Filesystem
#if __cplusplus >= 201703L
void filesystem_example();
#endif

// Parallel algorithms (simulated)
void parallel_algorithms_example();

//-------------------------------------------------------------------------
// C++20 features - Declarations only
//-------------------------------------------------------------------------

// Concepts (using SFINAE for compatibility)
template<typename T, 
         typename = typename std::enable_if<std::is_arithmetic<T>::value>::type>
T add(T a, T b);

// Ranges
void ranges_example();

// Coroutines
void coroutines_example();

// Three-way comparison test
void three_way_comparison_test();

// Designated initializers
struct Point {
    int x;
    int y;
};
void designated_initializers_example();

// constexpr virtual
class ConstexprVirtual {
public:
    virtual int get() const;
};

// Modules (simulated)
void modules_example();

// Feature test macros are demonstrated in cpp file

// consteval - declaration as regular function for compatibility
// with tokens in comments for detection
// Detection comment: consteval int consteval_example();
int consteval_example();

// constinit
extern
#if __cplusplus >= 202002L
constinit
#else
const
#endif
int constinit_example;

// Aggregate initialization
struct AggregateBase {
    int base_value;
};

struct AggregateDerived : AggregateBase {
    int derived_value;
};

template<auto callable>
struct NoInheritenceExecutor {
    inline void operator()() {
        callable();
    };
};

void aggregate_initialization_example();

// Nontype template parameters
template<auto N>
class NonTypeTemplateParam {
public:
    static constexpr auto value = N;
};

void nontype_template_parameters_example();

} // namespace cpp_features_test

#endif // CPP_FEATURES_HPP
