## 0.1.2 (2025-05-04)

### Feat

- support member type aliases
- parse class fields
- skip forward declarations in markdown generation
- handle enclosed types
- config generation reads existing configs first

### Fix

- skip forward declarations in class index pages
- bug with method/field access specifiers
- bug with reporting class children entities
- enclosed entities names and scopes
- markdown output for member fields
- better handling of scope-resolution notation in method/function definition

## 0.1.1 (2025-04-29)

### Feat

- add ODW unit-test report -> markdown file
- add plugin to extract information from self-reflecting OpenFOAM code
- tree-sitter parser forced for unit tests
- improved parsed docs and url pattern application
- overridable config entries on generation

### Fix

- update config structure + add option to skip entities
- repair plugin system
- source file handling as absolute path in compile_commmands
- handle relative include paths in compile_commands.json

## 0.1.0 (2025-04-27)

### BREAKING CHANGE

- a non-null column in inheritance table, for
access_level, is now required.

### Feat

- deprecation detection
- specialize method docs URI
- attach namespaces to entities + improved mapping file -> url
- better detection of defaulted/deleted methods
- contributers list from git
- markdown frontend to database entities
- basic git ops for author extraction
- most popular compiler attributes
- first implementation of a fallback tree-sitter parser
- static, return_type and few other new db fields
- update openfoam-plugin to adequetly parse RTS-features of OpenFOAM classes
- add openfoam RTS class fetching to db
- thorough function metadata extraction
- proper inheritance, declaration-definition links and namespace tracking
- first versions of openmp, openacc, and openfoam plugins
- plugin mechanism to add feature detectors dynamically
- add basic parsing and db exporting

### Fix

- prep plugins for publishing
- unknown cursor name
- signatures for class entities
- improve constructor parsing
- proper ctor/dtor signatures and (no) return types
- URI handling in declaration/definitionfile templating
- path normalization when generating markdown files
- improve handling of existing database
- logger bug in config generation
- update default config
- improve get_class_stats from codebase-wide database selections
- avoid circular dependency byadding common constants file
- detection of c++20 features
- detection of c++17 features
- detection of c++14 features
- detection of c++11 features

### Refactor

- prep for 1st published version + versionning
- parser feature detection to get rid of horrible if-else chains
