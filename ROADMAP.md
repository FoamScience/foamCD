# ROADMAP

These are things I am **thinking** of implementing next. PRs towards these
are most welcome.

## Parser

- Basic C++ features
  - [x] Namespaces
   - [x] Classes and inheritance
    - [x] Basic class/struct declarations
    - [x] Single/multiple inheritance
    - [x] Access specifiers
    - [ ] Subclasses
    - [ ] class/struct member data
  - [x] Templates
    - [x] Function templates
    - [x] Class templates
    - [ ] SFINAE, (suggest to replace by if constexpr, concepts and constrained templates, and maybe reflection)
    - [ ] CRTP, (suggest to replace by concepts unless wanting compile-time polymorphism with injected behavior)
  - [x] Function/operator overloading
  - [x] Reference parameters/variables
  - [x] Exception handling
  - [ ] class typedefs/usings
  - [ ] rule-of-5, class copy/move/delete status
  - [ ] singleton? Depending on how hard it is to detect
  - [ ] RAII patterns, with very low priority for now
- C++ 11
  - [x] Lambda expressions
  - [x] Type system (auto, decltype, type traits)
  - [x] Memory management (nullptr, smart pointers, move semantics)
  - [x] Variadic templates
  - [x] Initializer lists
  - [x] Delegating ctors
  - [x] Range-based for loops 
  - [x] static assert
  - [x] Scoped enums
  - [x] final/override
  - [x] defaulted/deleted
  - [x] Explicit conversion operators
  - [x] constexpr functions
  - [x] User-defined literals
  - [x] Member initializers and non-static data member initializers
  - [x] [[noreturn]] compiler attribute
  - [ ] thread-local storage (TLS) mechanism
    - [ ] mutable members
    - [ ] static thread_local
- C++ 14 
  - [x] Generic lambdas
  - [x] Lambda capture initialization
  - [x] Function return type deduction
  - [x] extended constexpr (loops and whatnot)
  - [x] Variable templates 
  - [x] Binary literals, and digit separators
  - [x] [[deprecated("message")]] compiler attribute
- C++ 17
  - [x] Structured bindings
  - [x] Class template argument deduction 
  - [x] Inline variables
  - [x] Fold expressions 
  - [x] if constexpr
  - [x] Selection statements (eg. 'if') with initializers
  - [x] Type deduction from braced initialization
  - [x] Nested namespaces
  - [x] std::invoke
  - [x] filesystem library usage
  - [x] parallel algorithms
  - [x] constexpr lambdas
  - [x] [[nodiscard]], [[maybe_unused]] compiler attributes
- C++20
  - [x] Concepts
  - [x] Coroutines
  - [x] Three-way comparison operator
  - [x] Designated initializers
  - [x] Aggregate initialization with base classes
  - [x] Non-type template parameters of class types
  - [x] consteval functions
  - [x] constinit variables
  - [x] constexpr virtual functions
  - [x] modules
  - [x] Feature test macros (`__cpp_*`)
  - [x] [[likely]], [[unlikely]], [[no_unique_address]] compiler attributes
- C++23
  - [x] c++23: [[assume(cond)]], [[deprecated("reason", "replacement")]]

- OpenFOAM DSL
  - [ ] RTS
  - [ ] objectRegistry/regIOobject/IOobject
  - [ ] Serializable to Streams
  - [ ] Can Fatal Error-out
  - [x] `Foam::autoPtr` and `Foam::tmp` as extra smart pointers

- Reflection system recognition
  - [ ] support level for reflection system
  - [ ] Auto-generate example usage for classes

- custom injected DSL
  - [x] Plugin system for loading custom DSL feature detection
    - [x] simple openMP plugin for demonstration 
    - [x] simple openACC plugin for demonstration 
    - [x] all OpenFOAM-related parsing happens through a plugin

## Markdown Docs

Each of the following is toggle-able in index pages:

- [x] Namespaces index
- [ ] C++ modules index
- [x] Entry-Points highlighting in class index
  - [x] Manual choice of highlights by class name
  - [x] OpenFOAM RTS-based highlights
- [x] Class index, organized following inheritance relationships
- [x] Free functions index
- [x] Concepts functions index

For each class:

- [x] API usage section
  - [x] Focused creation section
    - [x] ctors/dtor
    - [x] Factory-like methods
    - [x] Examples of usage using the reflection system
  - [x] Abstractions, methods that need to be implemented in children if any
  - [x] Public Interface
    - [x] Public methods in class
    - [x] Public methods inherited from bases
  - [ ] Mention sibling classes, as a "Similar to this class" section
- [x] API dev/extend section
  - [x] Implementation details
    - [x] protected methods, and the ones inherited from bases
    - [x] private methods, and the ones inherited from bases
  - [ ] Complaints/self-rating
    - [ ] Level of extensibility (virtual/abstract functions?)
    - [ ] Level of configurability (objectRegistry passed to ctors? Dictionaries?)
    - [ ] Level of testability (Dependencies, unit-tests)
    - [ ] Compliance to rule of 5
    - [ ] Excessive SFINAE usage
    - [ ] Excessive CRTP usage
  - [ ] OpenFOAM-wrapped MPI level of support
  - [x] Knowledge requirements

For each method:

- [x] signature
- [x] Comment-driven docs
- [ ] Function specifiers
  - [x] virtual
  - [x] static
  - [x] inline
  - [x] constexpr / consteval / constinit
  - [x] explicit ctors
  - [ ] friendships
- [x] Function qualifiers 
  - [x] constness
  - [x] volatile
  - [x] noexcept
  - [x] override/final
- [x] Function attributes
  - [x] nodiscard
  - [x] deprecated
  - [x] likely and unlikely
