# foamCD Plugin System

This directory contains plugins for the foamCD code documentation system. Plugins extend foamCD functionality
by adding custom Domain-Specific Language (DSL) feature detectors.

## Creating a Plugin

To create a plugin:

1. Create a new Python file in any folder, e.g., `my_dsl_plugin.py`
1. Add the folder to `parser.plugin_dirs` list
1. In `my_dsl_plugin.py`, import the necessary classes from `foamCD`:
   ```python
   from foamcd.feature_detectors import FeatureDetector
   ```
1. Create one or more detector classes that inherit from `FeatureDetector`
1. Implement the `detect` method to identify your DSL features

## Plugin Detection Flow

When you add a plugin:

1. It will be automatically discovered by foamCD at startup
1. The plugin's detector will be registered in the feature detector registry
1. During code parsing, your detector will be run on each relevant code entity
1. Custom entity fields will be stored in the database

## Adding Custom Entity Fields

Your detector can define custom entity fields by adding an `entity_fields` class attribute:

```python
entity_fields = {
    "field_name": {
        "type": "TEXT",  # Supported types: TEXT, INTEGER, REAL, BOOLEAN, JSON
        "description": "Description of the field"
    },
    # More fields...
}
```

These fields will be automatically registered when your plugin is loaded.

## Advanced Detection Results

> [!IMPORTANT]
> If plugins are enabled, the clang parser exposes itself as the `CURRENT_PARSER`
> global variable:
> ```python
> from foamcd.parse import CURRENT_PARSER
> ```

Your detector's `detect` method can return:

1. A boolean value (simple detection)
2. A dictionary with detailed information:

```python
return {
    'detected': True,  # Whether the feature was detected
    'fields': {
        'field_name': value,  # Custom field values
        # More fields...
    }
}
```
