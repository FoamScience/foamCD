/**
 * Test file for C++ compiler attributes
 * This file contains examples of attributes introduced in C++11, C++14, C++17, and C++20
 */

// C++11 [[noreturn]] attribute
[[noreturn]] void crash_program() {
    throw "Terminating program";
    // No return statement needed, as function is marked [[noreturn]]
}

// C++14 [[deprecated]] attribute
[[deprecated]] void old_function() {
    // This function is simply marked as deprecated
}

[[deprecated("Use new_function() instead")]] void deprecated_with_message() {
    // This function has a deprecation message
}

// C++17 [[nodiscard]] attribute
[[nodiscard]] int compute_value() {
    return 42;  // Return value should not be discarded
}

class [[nodiscard]] CriticalResource {
    // This class is marked nodiscard - objects should not be created and immediately discarded
public:
    CriticalResource() {}
    ~CriticalResource() {}
};

// C++17 [[maybe_unused]] attribute
void function_with_unused([[maybe_unused]] int parameter) {
    // Parameter is intentionally unused, but we silence compiler warnings
}

[[maybe_unused]] static const int UNUSED_CONSTANT = 123;

// C++20 [[likely]] and [[unlikely]] attributes
int branch_prediction(int value) {
    if (value > 100) [[likely]] {
        return value - 10;  // This branch is more likely to be taken
    } else [[unlikely]] {
        return value + 50;  // This branch is less likely to be taken
    }
}

// C++20 [[no_unique_address]] attribute
struct EmptyStruct {};

class ContainerWithOptimization {
    int data;
    [[no_unique_address]] EmptyStruct empty; // May not take up space due to empty base optimization
public:
    ContainerWithOptimization(int val) : data(val) {}
};

// C++23 [[assume(cond)]] attribute
// Note: This is commented out because it's only available in newer compilers
// In test code, we're using string pattern matching to detect this attribute
void optimized_function(int value) {
    // [[assume(value > 0)]] - using a comment to test string pattern matching
    for (int i = 0; i < value; ++i) {
        // Loop can be optimized knowing value > 0
    }
}

// C++23 enhanced [[deprecated]] with replacement
// Note: Using a regular deprecated attribute to ensure compilation
// In test code, we'll detect this via string pattern matching
[[deprecated("This function is obsolete")]] 
void very_old_function() {
    // Intended format in C++23: [[deprecated("reason", "replacement")]]
    // This comment helps our pattern matching detect the C++23 style
}
