#!/usr/bin/env python3

import os
import sqlite3
from typing import List, Dict, Any, Optional

from logs import setup_logging

logger = setup_logging()

class EntityDatabase:
    """SQLite database for storing C++ entities and their relationships"""
    
    def __init__(self, db_path: str, create_tables: bool = True):
        """Initialize the database
        
        Args:
            db_path: Path to the SQLite database file
            create_tables: Whether to create tables if they don't exist
        """
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
        self._connect()
        if create_tables:
            self._create_tables()
    
    def _connect(self):
        """Connect to the SQLite database"""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.row_factory = sqlite3.Row
            self.cursor = self.conn.cursor()
            logger.debug(f"Connected to database: {self.db_path}")
        except sqlite3.Error as e:
            logger.error(f"Error connecting to database: {e}")
            raise
    
    def _create_tables(self):
        """Create database tables if they don't exist"""
        try:
            # Entities table
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS entities (
                uuid TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                file TEXT,
                line INTEGER,
                column INTEGER,
                end_line INTEGER,
                end_column INTEGER,
                documentation TEXT,
                access_level TEXT,
                type_info TEXT,
                parent_uuid TEXT,
                FOREIGN KEY (parent_uuid) REFERENCES entities (uuid) ON DELETE CASCADE
            )
            ''')
            
            # Create index on parent_uuid for faster relationship queries
            self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_entities_parent_uuid ON entities (parent_uuid)
            ''')
            
            # Features table
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
            ''')
            
            # Entity features relationship table
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS entity_features (
                entity_uuid TEXT,
                feature_id INTEGER,
                PRIMARY KEY (entity_uuid, feature_id),
                FOREIGN KEY (entity_uuid) REFERENCES entities (uuid) ON DELETE CASCADE,
                FOREIGN KEY (feature_id) REFERENCES features (id) ON DELETE CASCADE
            )
            ''')
            
            # Create index on entity_uuid for faster feature lookup
            self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_entity_features_entity_uuid ON entity_features (entity_uuid)
            ''')
            
            # Custom entity fields table for DSL plugin data
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS custom_entity_fields (
                entity_uuid TEXT,
                field_name TEXT,
                field_type TEXT,
                text_value TEXT,
                int_value INTEGER,
                real_value REAL,
                bool_value BOOLEAN,
                json_value TEXT,
                plugin_name TEXT,
                PRIMARY KEY (entity_uuid, field_name),
                FOREIGN KEY (entity_uuid) REFERENCES entities (uuid) ON DELETE CASCADE
            )
            ''')
            
            # Create index on entity_uuid for faster custom field lookup
            self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_custom_entity_fields_entity_uuid 
            ON custom_entity_fields (entity_uuid)
            ''')
            
            # Method classification table
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS method_classification (
                entity_uuid TEXT PRIMARY KEY,
                is_virtual BOOLEAN,
                is_pure_virtual BOOLEAN,
                is_override BOOLEAN,
                is_final BOOLEAN,
                is_defaulted BOOLEAN,
                is_deleted BOOLEAN,
                FOREIGN KEY (entity_uuid) REFERENCES entities (uuid) ON DELETE CASCADE
            )
            ''')
            
            # Class classification table
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS class_classification (
                entity_uuid TEXT PRIMARY KEY,
                is_abstract BOOLEAN,
                is_final BOOLEAN,
                FOREIGN KEY (entity_uuid) REFERENCES entities (uuid) ON DELETE CASCADE
            )
            ''')
            
            # Inheritance relationships table
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS inheritance (
                class_uuid TEXT NOT NULL,
                base_uuid TEXT,
                base_name TEXT NOT NULL,
                access_level TEXT NOT NULL,
                is_virtual BOOLEAN NOT NULL,
                PRIMARY KEY (class_uuid, base_name),
                FOREIGN KEY (class_uuid) REFERENCES entities (uuid) ON DELETE CASCADE,
                FOREIGN KEY (base_uuid) REFERENCES entities (uuid) ON DELETE SET NULL
            )
            ''')
            
            # Create index for faster inheritance lookups
            self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_inheritance_class_uuid ON inheritance (class_uuid)
            ''')
            
            # Create tables for structured documentation
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS parsed_docs (
                entity_uuid TEXT PRIMARY KEY,
                description TEXT,
                returns TEXT,
                deprecated TEXT,
                since TEXT,
                FOREIGN KEY (entity_uuid) REFERENCES entities (uuid) ON DELETE CASCADE
            )
            ''')
            
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS doc_parameters (
                entity_uuid TEXT NOT NULL,
                param_name TEXT NOT NULL,
                description TEXT,
                PRIMARY KEY (entity_uuid, param_name),
                FOREIGN KEY (entity_uuid) REFERENCES entities (uuid) ON DELETE CASCADE
            )
            ''')
            
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS doc_throws (
                entity_uuid TEXT NOT NULL,
                description TEXT,
                PRIMARY KEY (entity_uuid, description),
                FOREIGN KEY (entity_uuid) REFERENCES entities (uuid) ON DELETE CASCADE
            )
            ''')
            
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS doc_see_also (
                entity_uuid TEXT NOT NULL,
                reference TEXT,
                PRIMARY KEY (entity_uuid, reference),
                FOREIGN KEY (entity_uuid) REFERENCES entities (uuid) ON DELETE CASCADE
            )
            ''')
            
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS doc_tags (
                entity_uuid TEXT NOT NULL,
                tag_name TEXT NOT NULL,
                content TEXT,
                PRIMARY KEY (entity_uuid, tag_name, content),
                FOREIGN KEY (entity_uuid) REFERENCES entities (uuid) ON DELETE CASCADE
            )
            ''')
            
            # Files table to track processed files
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                last_modified INTEGER,
                hash TEXT
            )
            ''')
            
            self.conn.commit()
            logger.debug("Database tables created successfully")
        except sqlite3.Error as e:
            logger.error(f"Error creating database tables: {e}")
            raise
    
    def close(self):
        """Close the database connection"""
        if self.conn:
            self.conn.close()
            logger.debug("Database connection closed")
    
    def store_entity(self, entity: Dict[str, Any]) -> str:
        """Store an entity in the database with enhanced features
        
        Args:
            entity: Entity dictionary
            
        Returns:
            The UUID of the stored entity
        """
        try:
            uuid = entity['uuid']
            name = entity['name']
            kind = entity['kind']
            location = entity.get('location', {})
            file_path = location.get('file') if location else entity.get('file')
            line = location.get('line') if location else entity.get('line')
            column = location.get('column') if location else entity.get('column')
            documentation = entity.get('doc_comment') or entity.get('documentation')
            parent_uuid = entity.get('parent_uuid')
            access_level = entity.get('access')
            type_info = entity.get('type_info')
            
            # Insert entity
            self.cursor.execute('''
            INSERT OR REPLACE INTO entities 
            (uuid, name, kind, file, line, column, documentation, access_level, type_info, parent_uuid)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (uuid, name, kind, file_path, line, column, documentation, 
                  access_level, type_info, parent_uuid))
            
            if 'cpp_features' in entity and entity['cpp_features']:
                self._store_entity_features(uuid, entity['cpp_features'])
            if 'method_info' in entity:
                self._store_method_classification(uuid, entity['method_info'])
            if 'class_info' in entity:
                self._store_class_classification(uuid, entity['class_info'])
            if 'base_classes' in entity and entity['base_classes']:
                self._store_inheritance(uuid, entity['base_classes'])
            if 'parsed_doc' in entity and entity['parsed_doc']:
                self._store_parsed_documentation(uuid, entity['parsed_doc'])
            if 'children' in entity and entity['children']:
                for child in entity['children']:
                    if 'parent_uuid' not in child:
                        child['parent_uuid'] = uuid
                    self.store_entity(child)
            if 'members' in entity:
                for access, members in entity['members'].items():
                    for member in members:
                        if 'parent_uuid' not in member:
                            member['parent_uuid'] = uuid
                        if 'access' not in member:
                            member['access'] = access.upper()
                        self.store_entity(member)
            
            self.conn.commit()
            return uuid
        except sqlite3.Error as e:
            logger.error(f"Error storing entity {entity.get('name')}: {e}")
            self.conn.rollback()
            raise
    
    def _store_method_classification(self, uuid: str, method_info: Dict[str, bool]) -> None:
        """Store method classification information
        
        Args:
            uuid: Entity UUID
            method_info: Dictionary with method classification flags
        """
        try:
            self.cursor.execute('''
            INSERT OR REPLACE INTO method_classification
            (entity_uuid, is_virtual, is_pure_virtual, is_override, is_final, is_defaulted, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                uuid,
                method_info.get('is_virtual', False),
                method_info.get('is_pure_virtual', False),
                method_info.get('is_override', False),
                method_info.get('is_final', False),
                method_info.get('is_defaulted', False),
                method_info.get('is_deleted', False)
            ))
        except sqlite3.Error as e:
            logger.error(f"Error storing method classification for {uuid}: {e}")
    
    def _store_class_classification(self, uuid: str, class_info: Dict[str, bool]) -> None:
        """Store class classification information
        
        Args:
            uuid: Entity UUID
            class_info: Dictionary with class classification flags
        """
        try:
            self.cursor.execute('''
            INSERT OR REPLACE INTO class_classification
            (entity_uuid, is_abstract, is_final)
            VALUES (?, ?, ?)
            ''', (
                uuid,
                class_info.get('is_abstract', False),
                class_info.get('is_final', False)
            ))
        except sqlite3.Error as e:
            logger.error(f"Error storing class classification for {uuid}: {e}")
    
    def _store_inheritance(self, class_uuid: str, base_classes: List[Dict[str, Any]]) -> None:
        """Store inheritance relationships
        
        Args:
            class_uuid: UUID of the derived class
            base_classes: List of base class dictionaries
        """
        try:
            for base in base_classes:
                base_uuid = base.get('uuid')
                base_name = base['name']
                if base_uuid:
                    self.cursor.execute('SELECT 1 FROM entities WHERE uuid = ?', (base_uuid,))
                    base_exists = self.cursor.fetchone() is not None
                    if not base_exists:
                        logger.warning(f"Base class with UUID {base_uuid} not found in database. "
                                      f"Creating placeholder entity for {base_name}")
                        self.cursor.execute('''
                        INSERT OR IGNORE INTO entities 
                        (uuid, name, kind, file, line, column, documentation, access_level, type_info, parent_uuid)
                        VALUES (?, ?, ?, NULL, NULL, NULL, NULL, 'PUBLIC', NULL, NULL)
                        ''', (base_uuid, base_name, 'CLASS_DECL'))
                self.cursor.execute('''
                INSERT OR REPLACE INTO inheritance
                (class_uuid, base_uuid, base_name, access_level, is_virtual)
                VALUES (?, ?, ?, ?, ?)
                ''', (
                    class_uuid,
                    base_uuid,
                    base_name,
                    base.get('access', 'PUBLIC'),
                    base.get('virtual', False)
                ))
                logger.debug(f"Stored inheritance relationship: {class_uuid} -> {base_name}")
        except sqlite3.Error as e:
            logger.error(f"Error storing inheritance for {class_uuid}: {e}")
    
    def _store_parsed_documentation(self, uuid: str, parsed_doc: Dict[str, Any]) -> None:
        """Store parsed documentation
        
        Args:
            uuid: Entity UUID
            parsed_doc: Dictionary with parsed documentation
        """
        try:
            description = parsed_doc.get('description')
            returns = parsed_doc.get('returns')
            deprecated = parsed_doc.get('deprecated')
            since = parsed_doc.get('since')
            
            self.cursor.execute('''
            INSERT OR REPLACE INTO parsed_docs
            (entity_uuid, description, returns, deprecated, since)
            VALUES (?, ?, ?, ?, ?)
            ''', (uuid, description, returns, deprecated, since))
            
            params = parsed_doc.get('params', {})
            for name, desc in params.items():
                self.cursor.execute('''
                INSERT OR REPLACE INTO doc_parameters
                (entity_uuid, param_name, description)
                VALUES (?, ?, ?)
                ''', (uuid, name, desc))
            for throw in parsed_doc.get('throws', []):
                self.cursor.execute('''
                INSERT OR REPLACE INTO doc_throws
                (entity_uuid, description)
                VALUES (?, ?)
                ''', (uuid, throw))
            for ref in parsed_doc.get('see', []):
                self.cursor.execute('''
                INSERT OR REPLACE INTO doc_see_also
                (entity_uuid, reference)
                VALUES (?, ?)
                ''', (uuid, ref))
            for tag, contents in parsed_doc.get('tags', {}).items():
                for content in contents:
                    self.cursor.execute('''
                    INSERT OR REPLACE INTO doc_tags
                    (entity_uuid, tag_name, content)
                    VALUES (?, ?, ?)
                    ''', (uuid, tag, content))
        except sqlite3.Error as e:
            logger.error(f"Error storing parsed documentation for {uuid}: {e}")
            raise
                    
    def _store_custom_entity_fields(self, uuid: str, custom_fields: Dict[str, Any]) -> None:
        """Store custom entity fields from DSL plugins
        
        Args:
            uuid: Entity UUID
            custom_fields: Dictionary with custom field values
        """
        try:
            # First, delete any existing custom fields for this entity
            self.cursor.execute('''
            DELETE FROM custom_entity_fields
            WHERE entity_uuid = ?
            ''', (uuid,))
            
            # Insert each custom field with appropriate type
            for field_name, value in custom_fields.items():
                if value is None:
                    continue
                    
                field_type = None
                text_value = None
                int_value = None
                real_value = None
                bool_value = None
                json_value = None
                plugin_name = None
                
                # Determine value type and store in appropriate column
                if isinstance(value, dict) and 'value' in value and 'type' in value:
                    # Extended format with metadata
                    field_type = value['type']
                    plugin_name = value.get('plugin', None)
                    actual_value = value['value']
                else:
                    # Simple format, just the value
                    actual_value = value
                    
                # Determine type if not explicitly specified
                if field_type is None:
                    if isinstance(actual_value, bool):
                        field_type = 'BOOLEAN'
                    elif isinstance(actual_value, int):
                        field_type = 'INTEGER'
                    elif isinstance(actual_value, float):
                        field_type = 'REAL'
                    elif isinstance(actual_value, (dict, list)):
                        field_type = 'JSON'
                    else:
                        field_type = 'TEXT'
                
                # Store value in appropriate column based on type
                if field_type == 'TEXT':
                    text_value = str(actual_value)
                elif field_type == 'INTEGER':
                    int_value = int(actual_value) if actual_value is not None else None
                elif field_type == 'REAL':
                    real_value = float(actual_value) if actual_value is not None else None
                elif field_type == 'BOOLEAN':
                    bool_value = bool(actual_value) if actual_value is not None else None
                elif field_type == 'JSON':
                    import json
                    json_value = json.dumps(actual_value)
                
                self.cursor.execute('''
                INSERT INTO custom_entity_fields
                (entity_uuid, field_name, field_type, text_value, int_value, real_value, bool_value, json_value, plugin_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (uuid, field_name, field_type, text_value, int_value, real_value, bool_value, json_value, plugin_name))
                
                logger.debug(f"Stored custom field '{field_name}' for entity {uuid}")
                
        except sqlite3.Error as e:
            logger.error(f"Error storing custom entity fields for {uuid}: {e}")
            raise

    def store_entity(self, entity: Dict[str, Any]) -> str:
        """Store an entity in the database with enhanced features
        
        Args:
            entity: Entity dictionary
            
        Returns:
            The UUID of the stored entity
        """
        try:
            uuid = entity['uuid']
            name = entity['name']
            kind = entity['kind']
            
            # Handle location information in nested dictionary format
            if 'location' in entity and isinstance(entity['location'], dict):
                location = entity['location']
                file_path = location.get('file', None)
                line = location.get('line', None)
                column = location.get('column', None)
                end_line = location.get('end_line', None)
                end_column = location.get('end_column', None)
            else:  # Fallback for direct field access
                file_path = entity.get('file', None)
                line = entity.get('line', None)
                column = entity.get('column', None)
                end_line = entity.get('end_line', None)
                end_column = entity.get('end_column', None)
            
            doc_comment = entity.get('doc_comment', None) or entity.get('documentation', None)
            access_level = entity.get('access_level', None) or entity.get('access', None)
            parent_uuid = entity.get('parent_uuid', None)
            type_info = entity.get('type_info', None)
            
            self.cursor.execute('''
            INSERT OR REPLACE INTO entities 
            (uuid, name, kind, file, line, column, end_line, end_column, documentation, access_level, type_info, parent_uuid)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (uuid, name, kind, file_path, line, column, end_line, end_column, doc_comment, access_level, type_info, parent_uuid))
            
            # Store method classification if present
            method_info = entity.get('method_info', {})
            if method_info:
                self._store_method_classification(uuid, method_info)
                
            # Store class classification if present
            class_info = entity.get('class_info', {})
            if class_info:
                self._store_class_classification(uuid, class_info)
                
            # Store inheritance relationships if present
            base_classes = entity.get('base_classes', [])
            if base_classes:
                self._store_inheritance(uuid, base_classes)
                
            # Store parsed documentation if present
            parsed_doc = entity.get('parsed_doc', {})
            if parsed_doc:
                self._store_parsed_documentation(uuid, parsed_doc)
                
            # Store features if present
            features = entity.get('cpp_features', [])
            if features:
                self._store_entity_features(uuid, features)
                
            # Store custom fields from DSL plugins if present
            custom_fields = entity.get('custom_fields', {})
            if custom_fields:
                self._store_custom_entity_fields(uuid, custom_fields)
            
            # Store children recursively
            children = entity.get('children', [])
            for child in children:
                self.store_entity(child)
                
            self.conn.commit()
            return uuid
            
        except sqlite3.Error as e:
            self.conn.rollback()
            logger.error(f"Error storing entity {entity.get('name', 'unknown')}: {e}")
            raise        
            
        except sqlite3.Error as e:
            logger.error(f"Error storing entity {entity.get('name')}: {e}")
            self.conn.rollback()
            raise
    
    def _store_entity_features(self, entity_uuid: str, features: List[str]):
        """Store features for an entity
        
        Args:
            entity_uuid: UUID of the entity
            features: List of feature names
        """
        try:
            # First, ensure all features exist in the features table
            for feature in features:
                self.cursor.execute('''
                INSERT OR IGNORE INTO features (name) VALUES (?)
                ''', (feature,))
            
            # Get feature IDs
            feature_ids = []
            for feature in features:
                self.cursor.execute('SELECT id FROM features WHERE name = ?', (feature,))
                row = self.cursor.fetchone()
                if row:
                    feature_ids.append(row[0])
            
            # Delete existing entity-feature relationships
            self.cursor.execute('''
            DELETE FROM entity_features WHERE entity_uuid = ?
            ''', (entity_uuid,))
            
            # Insert new entity-feature relationships
            for feature_id in feature_ids:
                self.cursor.execute('''
                INSERT INTO entity_features (entity_uuid, feature_id) VALUES (?, ?)
                ''', (entity_uuid, feature_id))
                
        except sqlite3.Error as e:
            logger.error(f"Error storing features for entity {entity_uuid}: {e}")
            raise
    
    def get_entity(self, uuid: str) -> Optional[Dict[str, Any]]:
        """Get an entity by UUID
        
        Args:
            uuid: UUID of the entity
            
        Returns:
            Entity dictionary or None if not found
        """
        try:
            self.cursor.execute('''
            SELECT * FROM entities WHERE uuid = ?
            ''', (uuid,))
            row = self.cursor.fetchone()
            
            if not row:
                return None
            
            # Convert row to dictionary
            entity = dict(row)
            
            # Get features
            self.cursor.execute('''
            SELECT f.name FROM features f
            JOIN entity_features ef ON f.id = ef.feature_id
            WHERE ef.entity_uuid = ?
            ''', (uuid,))
            features = [row[0] for row in self.cursor.fetchall()]
            entity['cpp_features'] = features
            
            # Get children
            self.cursor.execute('''
            SELECT uuid FROM entities WHERE parent_uuid = ?
            ''', (uuid,))
            child_uuids = [row[0] for row in self.cursor.fetchall()]
            
            # Recursively get children
            children = []
            for child_uuid in child_uuids:
                child = self.get_entity(child_uuid)
                if child:
                    children.append(child)
            
            entity['children'] = children
            
            # Get custom entity fields from DSL plugins
            custom_fields = self._get_custom_entity_fields(uuid)
            if custom_fields:
                entity['custom_fields'] = custom_fields
                
            return entity
        except sqlite3.Error as e:
            logger.error(f"Error getting entity {uuid}: {e}")
            raise
    
    def _get_custom_entity_fields(self, uuid: str) -> Dict[str, Any]:
        """Get custom entity fields for an entity
        
        Args:
            uuid: UUID of the entity
            
        Returns:
            Dictionary of custom fields with their values
        """
        try:
            self.cursor.execute('''
            SELECT field_name, field_type, text_value, int_value, real_value, bool_value, json_value, plugin_name
            FROM custom_entity_fields WHERE entity_uuid = ?
            ''', (uuid,))
            
            custom_fields = {}
            for row in self.cursor.fetchall():
                field_name = row[0]
                field_type = row[1]
                value = None
                
                # Get value based on type
                if field_type == 'TEXT':
                    value = row[2]  # text_value
                elif field_type == 'INTEGER':
                    value = row[3]  # int_value
                elif field_type == 'REAL':
                    value = row[4]  # real_value
                elif field_type == 'BOOLEAN':
                    value = bool(row[5])  # bool_value
                elif field_type == 'JSON':
                    import json
                    try:
                        value = json.loads(row[6]) if row[6] else None  # json_value
                    except json.JSONDecodeError:
                        logger.warning(f"Error parsing JSON value for field {field_name}")
                        value = None
                
                plugin_name = row[7]
                if plugin_name:
                    custom_fields[field_name] = {
                        'value': value,
                        'type': field_type,
                        'plugin': plugin_name
                    }
                else:
                    custom_fields[field_name] = value
                    
            return custom_fields
            
        except sqlite3.Error as e:
            logger.error(f"Error retrieving custom fields for entity {uuid}: {e}")
            return {}
    
    def get_entities_by_file(self, file_path: str) -> List[Dict[str, Any]]:
        """Get all top-level entities in a file
        
        Args:
            file_path: Path to the file
            
        Returns:
            List of entity dictionaries
        """
        try:
            self.cursor.execute('''
            SELECT uuid FROM entities 
            WHERE file = ? AND parent_uuid IS NULL
            ''', (file_path,))
            
            rows = self.cursor.fetchall()
            entities = []
            
            for row in rows:
                entity = self.get_entity(row[0])
                if entity:
                    entities.append(entity)
            
            return entities
        except sqlite3.Error as e:
            logger.error(f"Error getting entities for file {file_path}: {e}")
            raise
    
    def get_all_files(self) -> List[str]:
        """Get all tracked files
        
        Returns:
            List of file paths
        """
        try:
            self.cursor.execute('SELECT path FROM files')
            return [row[0] for row in self.cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Error getting all files: {e}")
            raise
    
    def track_file(self, file_path: str, last_modified: int, file_hash: str):
        """Track a file for change detection.
        Implements a simple caching mechanism to reduce runtime cost
        TODO: Maybe git-based filtering of touched files in commit?
        
        Args:
            file_path: Path to the file
            last_modified: Last modified timestamp
            file_hash: Hash of the file content
        """
        try:
            self.cursor.execute('''
            INSERT OR REPLACE INTO files (path, last_modified, hash)
            VALUES (?, ?, ?)
            ''', (file_path, last_modified, file_hash))
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error tracking file {file_path}: {e}")
            self.conn.rollback()
            raise
    
    def file_changed(self, file_path: str, last_modified: int, file_hash: str) -> bool:
        """Check if a file has changed since last tracking.
        TODO: Maybe git-based filtering of touched files in commit?
        
        Args:
            file_path: Path to the file
            last_modified: Current last modified timestamp
            file_hash: Current hash of the file content
            
        Returns:
            True if file changed or not tracked, False otherwise
        """
        try:
            self.cursor.execute('''
            SELECT last_modified, hash FROM files WHERE path = ?
            ''', (file_path,))
            
            row = self.cursor.fetchone()
            if not row:
                return True  # File not tracked yet
            
            stored_last_modified, stored_hash = row
            return stored_last_modified != last_modified or stored_hash != file_hash
        except sqlite3.Error as e:
            logger.error(f"Error checking file changes for {file_path}: {e}")
            raise
    
    def get_all_entities(self) -> List[Dict[str, Any]]:
        """Get all top-level entities (no parent)
        
        Returns:
            List of entity dictionaries
        """
        try:
            self.cursor.execute('SELECT uuid FROM entities WHERE parent_uuid IS NULL')
            rows = self.cursor.fetchall()
            
            entities = []
            for row in rows:
                entity = self.get_entity(row[0])
                if entity:
                    entities.append(entity)
            
            return entities
        except sqlite3.Error as e:
            logger.error(f"Error getting all entities: {e}")
            raise
    
    def clear_file_entities(self, file_path: str):
        """Remove all entities for a specific file
        
        Args:
            file_path: Path to the file
        """
        try:
            self.cursor.execute('''
            SELECT uuid FROM entities WHERE file = ? AND parent_uuid IS NULL
            ''', (file_path,))
            for row in self.cursor.fetchall():
                self.cursor.execute('DELETE FROM entities WHERE uuid = ?', (row[0],))
            self.conn.commit()
            logger.debug(f"Cleared entities for file: {file_path}")
        except sqlite3.Error as e:
            logger.error(f"Error clearing entities for file {file_path}: {e}")
            self.conn.rollback()
            raise
    
    def get_files_using_feature(self, feature_name: str) -> List[str]:
        """Get all files that use a specific feature
        
        Args:
            feature_name: Name of the C++ feature
            
        Returns:
            List of file paths
        """
        try:
            self.cursor.execute('''
            SELECT DISTINCT e.file FROM entities e
            JOIN entity_features ef ON e.uuid = ef.entity_uuid
            JOIN features f ON ef.feature_id = f.id
            WHERE f.name = ? AND e.file IS NOT NULL
            ''', (feature_name,))
            
            return [row[0] for row in self.cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Error getting files using feature {feature_name}: {e}")
            raise
    
    def get_feature_usage_counts(self) -> Dict[str, int]:
        """Get usage counts for all features
        
        Returns:
            Dictionary mapping feature names to usage counts
        """
        try:
            self.cursor.execute('''
            SELECT f.name, COUNT(ef.entity_uuid) as count
            FROM features f
            JOIN entity_features ef ON f.id = ef.feature_id
            GROUP BY f.name
            ORDER BY count DESC
            ''')
            
            return {row[0]: row[1] for row in self.cursor.fetchall()}
        except sqlite3.Error as e:
            logger.error(f"Error getting feature usage counts: {e}")
            raise
