# FoamCD - C++ Documentation Tool

> More often than not, C++-based libraries develop their own Domain-Specific Languages
> on top of standard C++ constructs. The C++ classes these libraries offer will
> represent runtime semantics, configuration hooks, and architectural patterns that
> are library-specific and hence difficult to automatically document, although these
> are probably the most important ones to document.

**FoamCD** is a C++ documentation system that focuses on parsing and documenting C++ code
with extensive coverage of language features up to C++20. It uses `libclang` as the main
parser for the Abstract Syntax Tree (AST) but offers `tree-sitter`-based parsing in contexts
where using `libclang` is not possible, or not efficient.

Naturally, it also picks up Doxygen, or docstrings comments surrounding code entities too.

## Features

- Produce productivity-focused documentation for OpenFOAM libraries
  - Sophisticated library Entry Points presentation in index pages, completely unattended
  - Classes are documented in two sections
    1. User-oriented section: for developers who just want to use the class in their code.
    1. Developer-oriented section: for developers who want to extend/modify the library code itself.
  - Used C++ features and patterns are clearly communicated.
  - OpenFOAM patterns, like the RunTime Selection Table, are taken into consideration
- Recognize C++ features by standard version.
- Maintain a SQLite database for all code entities.
- Read compilation arguments from a `compile_commands.json` database

## Installation

### Prerequisites

1. Install [uv], not strictly necessary but will make your life easier.
   - `curl -LsSf https://astral.sh/uv/install.sh | sh`
1. Get [Bear], so you can generate `compile_commands.json` files easily.
1. Install a recent version of `libclang`
   - On Debian-likes, `apt-get install -y libclang-dev` should be enough
1. Install SQLite
   - On Debian-likes, `apt-get install -y libsqlite3-dev` will do

## Usage

> A large portion of `foamCD` use cases are tightly connected to generating
> Hugo-based static sites for the documentation.

### The parser(s)

You can use the parser CLI to consolidate your code entities into an SQLite database.
```bash
# We'll use the fixture files at tests/fixtures/* for testing here, 
# So, first generate a compilation database
# !! It's alright if the following says missing reference to main,
#    but adapt include paths to your system !!
bear -- g++ --std=c++20 \
        -I/usr/include -I/usr/lib/gcc/x86_64-linux-gnu/13/include \
        -I/usr/include/x86_64-linux-gnu -I$(pwd)/tests/fixtures \
        $(pwd)/tests/fixtures/cpp_features.cpp
# then generate an example configuration file
uvx foamcd-parse --generate-config example.yaml
```

```bash
# Pick on the config as you wish, you can set parser.compile_commands_dir to your CWD
# or, just pass it on the command line
uvx foamcd-parse --config example.yaml  --compile-commands-dir=$(pwd) --output docs.db
```

If things go well, you will find a `docs.db` file in your CWD that you can inspect:
```bash
sqlite docs.md
```
```sqlite
sqlite> select e.name
   ...> from entities e
   ...> join custom_entity_fields cef on e.uuid = cef.entity_uuid
   ...> where cef.field_name = "openfoam_class_role"
   ...> and cef.text_value = 'base';
```
That's how `foamCD` fetches important "entry points" into your OpenFOAM library.

That may have been too advanced of a first SQL query, here let's try with a simpler one:
```sqlite
>sqlite select * from files;
```

This will show all (parsed) main library files. If you want to know what
all the pipe-separated tokens represent, run:
```sqlite
>sqlite .schema files
CREATE TABLE files (
                path TEXT PRIMARY KEY,
                last_modified INTEGER,
                hash TEXT
            );
```

To see all files references by entities in the database:
```sqlite
>sqlite select distinct file from entities;
```
These can help to craft `parser.prefixes_to_skip` and `markdown.dependencies` lists.

## Markdown docs generation

Generating the documentation in Markdown format for the project is then carried out as:
```bash
uvx foamcd-markdown --db docs.db --config example.yaml  --output <output_path>
```


Note that if you keep `docs.db` and the `<output_path>` between docs generations:
- The parser will not parse files that were not modified since processing them into `docs.db`
  - The database keeps a `last_modified` field for each source file, and it acts as a simple caching mechanism
- The "content" of Markdown files will be preserved. Only the `frontmatter` will be overridden.
  - This allows for customized documentation of specific entities.

## Testing

To run the python unit-tests:

```bash
uv run python -m unittest discover -v tests/unit
```


## Plugin system

`FoamCD` supports a simple plugin mechanism to hook into the parser and record entries into the
SQLite database. The previous complex SQL query that involved `custom_entity_fields` table
works only if you have the `openfoam` plugin turned on.

For details on how to create your own plugins, take a look at [plugins/README.md](plugins/README.md)

## License

[MIT License](LICENSE)

[uv]: https://github.com/astral-sh/uv
[Bear]: https://github.com/rizsotto/Bear
