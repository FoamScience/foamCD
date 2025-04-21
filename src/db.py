#!/usr/bin/env python3

import os
import sqlite3
from typing import List, Dict, Any, Optional

from logs import setup_logging

from parse import CPP_IMPLEM_EXTENSIONS, CPP_HEADER_EXTENSIONS

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
    
    def commit(self):
        """Commit the current transaction to the database"""
        self.conn.commit()
    
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
            
            # Declaration-definition linking table
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS decl_def_links (
                decl_uuid TEXT NOT NULL,
                def_uuid TEXT NOT NULL,
                PRIMARY KEY (decl_uuid, def_uuid),
                FOREIGN KEY (decl_uuid) REFERENCES entities (uuid) ON DELETE CASCADE,
                FOREIGN KEY (def_uuid) REFERENCES entities (uuid) ON DELETE CASCADE
            )
            ''')
            
            # Create indices for faster lookup of declarations and definitions
            self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_decl_def_links_decl_uuid 
            ON decl_def_links (decl_uuid)
            ''')
            
            self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_decl_def_links_def_uuid 
            ON decl_def_links (def_uuid)
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
                class_name TEXT NOT NULL,
                base_uuid TEXT,
                base_name TEXT NOT NULL,
                access_level TEXT NOT NULL,
                is_virtual BOOLEAN NOT NULL,
                PRIMARY KEY (class_uuid, base_name),
                FOREIGN KEY (class_uuid) REFERENCES entities (uuid) ON DELETE CASCADE,
                FOREIGN KEY (base_uuid) REFERENCES entities (uuid) ON DELETE SET NULL
            )
            ''')
            
            # Create indices for inheritance table
            self.cursor.execute('''
            CREATE INDEX idx_inheritance_class_name ON inheritance (class_name)
            ''')
            self.cursor.execute('''
            CREATE INDEX idx_inheritance_base_name ON inheritance (base_name)
            ''')
            self.cursor.execute('''
            CREATE INDEX idx_inheritance_class_uuid ON inheritance (class_uuid)
            ''')
            self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_inheritance_base_uuid ON inheritance (base_uuid)
            ''')
            
            # Base-child inheritance relationship table with direct and recursive links
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS base_child_links (
                base_uuid TEXT NOT NULL,
                child_uuid TEXT NOT NULL,
                direct BOOLEAN NOT NULL, -- TRUE for direct inheritance, FALSE for recursive parent-child
                depth INTEGER NOT NULL, -- 1 for direct parent, 2+ for grandparent, etc.
                access_level TEXT NOT NULL, -- PUBLIC, PROTECTED, PRIVATE; effective access level for this relationship
                PRIMARY KEY (base_uuid, child_uuid),
                FOREIGN KEY (base_uuid) REFERENCES entities (uuid) ON DELETE CASCADE,
                FOREIGN KEY (child_uuid) REFERENCES entities (uuid) ON DELETE CASCADE
            )
            ''')
            
            self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_base_child_links_base_uuid 
            ON base_child_links (base_uuid)
            ''')
            self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_base_child_links_child_uuid 
            ON base_child_links (child_uuid)
            ''')
            self._populate_base_child_links()
            
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
        """Store inheritance relationships and update base-child links
        
        Args:
            class_uuid: UUID of the derived class
            base_classes: List of base class dictionaries with base class information
        """
        try:
            logger.debug(f"Storing inheritance for class {class_uuid} with {len(base_classes)} base classes")
            
            # Clear inheritence records, this is important when loading existing databases
            # as inheritence hierarchies are suseptable to change
            self.cursor.execute('''
            DELETE FROM inheritance WHERE class_uuid = ?
            ''', (class_uuid,))
            
            self.cursor.execute('SELECT name FROM entities WHERE uuid = ?', (class_uuid,))
            class_name_row = self.cursor.fetchone()
            class_name = class_name_row[0] if class_name_row else 'UnknownClass'
            logger.debug(f"Found class name for {class_uuid}: {class_name}")
            for base_class in base_classes:
                base_uuid = base_class.get('uuid', None)
                self.cursor.execute('''
                INSERT INTO inheritance (class_uuid, class_name, base_uuid, base_name, access_level, is_virtual)
                VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    class_uuid,
                    class_name,
                    base_uuid,
                    base_class['name'],
                    base_class.get('access', 'PUBLIC'),
                    base_class.get('virtual', False)
                ))
                
                if base_uuid:
                    logger.debug(f"Stored inheritance relationship with UUID: {class_name} ({class_uuid}) inherits from {base_class['name']} ({base_uuid})")
                    access_level = base_class.get('access', 'PUBLIC')
                    self.cursor.execute('''
                    INSERT OR REPLACE INTO base_child_links (base_uuid, child_uuid, direct, depth, access_level)
                    VALUES (?, ?, ?, 1, ?)
                    ''', (base_uuid, class_uuid, True, access_level))
                    self.cursor.execute('''
                    SELECT base_uuid, depth, access_level FROM base_child_links 
                    WHERE child_uuid = ?
                    ''', (base_uuid,))
                    
                    for row in self.cursor.fetchall():
                        ancestor_uuid = row[0]
                        depth = row[1]
                        ancestor_access = row[2]
                        effective_access = access_level
                        if ancestor_access == 'PRIVATE' or access_level == 'PRIVATE':
                            effective_access = 'PRIVATE'
                        elif ancestor_access == 'PROTECTED' or access_level == 'PROTECTED':
                            effective_access = 'PROTECTED'
                        self.cursor.execute('''
                        INSERT OR REPLACE INTO base_child_links (base_uuid, child_uuid, direct, depth, access_level)
                        VALUES (?, ?, ?, ?, ?)
                        ''', (ancestor_uuid, class_uuid, False, depth + 1, effective_access))
                else:
                    logger.debug(f"Stored inheritance relationship without UUID: {class_name} ({class_uuid}) inherits from {base_class['name']}")
            self._update_recursive_base_child_links(class_uuid)
            self.conn.commit()

        except sqlite3.Error as e:
            logger.error(f"Error storing inheritance relationships: {e}")
            self.conn.rollback()
            
    def _update_recursive_base_child_links(self, class_uuid: str):
        """Update recursive base-child links for all children of a class
        
        This method ensures that when a class's inheritance is updated,
        all its children also get updated recursive relationships with the
        new ancestors.
        
        Args:
            class_uuid: UUID of the class whose children need updating
        """
        try:
            self.cursor.execute('''
            SELECT child_uuid FROM base_child_links
            WHERE base_uuid = ? AND direct = ?
            ''', (class_uuid, True))
            direct_children = [row[0] for row in self.cursor.fetchall()]
            for child_uuid in direct_children:
                self.cursor.execute('''
                SELECT base_uuid, depth FROM base_child_links 
                WHERE child_uuid = ? AND child_uuid != ?
                ''', (class_uuid, child_uuid))  # Avoid self-references
                for row in self.cursor.fetchall():
                    ancestor_uuid = row[0]
                    depth = row[1]
                    self.cursor.execute('''
                    INSERT OR REPLACE INTO base_child_links (base_uuid, child_uuid, direct, depth)
                    VALUES (?, ?, ?, ?)
                    ''', (ancestor_uuid, child_uuid, False, depth + 1))
                self._update_recursive_base_child_links(child_uuid)
                
        except sqlite3.Error as e:
            logger.error(f"Error updating recursive base-child links: {e}")

    def _populate_base_child_links(self):
        """Populate base_child_links table from existing inheritance data
        
        This method reads from the inheritance table and builds both direct and
        recursive inheritance relationships in the base_child_links table.
        """
        try:
            self.cursor.execute("SELECT COUNT(*) FROM base_child_links")
            count = self.cursor.fetchone()[0]
            if count == 0:
                logger.debug("Populating base_child_links table from existing inheritance data")
                self.cursor.execute("DELETE FROM base_child_links")
                self.cursor.execute("""
                SELECT i.base_uuid, i.class_uuid, i.base_name, e.name AS class_name
                FROM inheritance i
                LEFT JOIN entities e ON i.class_uuid = e.uuid
                """)
                inheritance_rows = self.cursor.fetchall()
                logger.info(f"Found {len(inheritance_rows)} inheritance relationships")
                for row in inheritance_rows:
                    base_uuid = row[0]
                    class_uuid = row[1]
                    base_name = row[2]
                    class_name = row[3]
                    logger.debug(f"Inheritance: {base_name} ({base_uuid}) <- {class_name} ({class_uuid})")
                
                self.cursor.execute("""
                SELECT base_uuid, class_uuid, base_name, access_level
                FROM inheritance 
                WHERE base_uuid IS NOT NULL
                """)
                
                direct_relations = []
                valid_relations = 0
                
                for row in self.cursor.fetchall():
                    base_uuid = row[0]
                    class_uuid = row[1]
                    base_name = row[2]
                    access_level = row[3]
                    if not base_uuid:
                        logger.warning(f"Inheritance record has NULL base_uuid for base class {base_name}")
                        self.cursor.execute(
                            "SELECT uuid FROM entities WHERE name = ? AND kind IN ('CLASS_DECL', 'CLASS_TEMPLATE', 'STRUCT_DECL')", 
                            (base_name,)
                        )
                        base_lookup = self.cursor.fetchone()
                        if base_lookup:
                            base_uuid = base_lookup[0]
                            logger.info(f"Resolved base_uuid for {base_name}: {base_uuid}")
                            self.cursor.execute(
                                "UPDATE inheritance SET base_uuid = ? WHERE class_uuid = ? AND base_name = ?", 
                                (base_uuid, class_uuid, base_name)
                            )
                        else:
                            logger.warning(f"Could not resolve base_uuid for {base_name}, skipping")
                            continue
                    if not class_uuid:
                        logger.warning(f"Skipping inheritance with NULL class_uuid for base {base_uuid}")
                        continue
                    
                    self.cursor.execute("SELECT 1 FROM entities WHERE uuid = ?", (base_uuid,))
                    if not self.cursor.fetchone():
                        logger.warning(f"Base class with UUID {base_uuid} ({base_name}) not found in entities table!")
                        continue
                    self.cursor.execute("SELECT 1 FROM entities WHERE uuid = ?", (class_uuid,))
                    if not self.cursor.fetchone():
                        logger.warning(f"Derived class with UUID {class_uuid} not found in entities table!")
                        continue
                    direct_relations.append((base_uuid, class_uuid, access_level))
                    valid_relations += 1
                    
                    try:
                        self.cursor.execute("""
                        INSERT OR REPLACE INTO base_child_links 
                        (base_uuid, child_uuid, direct, depth, access_level) 
                        VALUES (?, ?, ?, 1, ?)
                        """, (base_uuid, class_uuid, True, access_level))
                        logger.debug(f"Added direct relationship: {base_uuid} <- {class_uuid} ({access_level})")
                    except sqlite3.Error as e:
                        logger.error(f"Error inserting direct relationship: {e}")
                
                logger.debug(f"Found {valid_relations} valid inheritance relationships out of {len(inheritance_rows)}")

                recursive_count = 0
                for base_uuid, child_uuid, access_level in direct_relations:
                    self.cursor.execute("""
                    SELECT base_uuid, depth, access_level 
                    FROM base_child_links 
                    WHERE child_uuid = ?
                    """, (base_uuid,))
                    for row in self.cursor.fetchall():
                        ancestor_uuid = row[0]
                        ancestor_depth = row[1]
                        ancestor_access = row[2]
                        effective_access = access_level
                        if ancestor_access == 'PRIVATE' or access_level == 'PRIVATE':
                            effective_access = 'PRIVATE'
                        elif ancestor_access == 'PROTECTED' or access_level == 'PROTECTED':
                            effective_access = 'PROTECTED'
                        # else keep PUBLIC
                        try:
                            self.cursor.execute("""
                            INSERT OR REPLACE INTO base_child_links 
                            (base_uuid, child_uuid, direct, depth, access_level) 
                            VALUES (?, ?, ?, ?, ?)
                            """, (ancestor_uuid, child_uuid, False, ancestor_depth + 1, effective_access))
                            recursive_count += 1
                        except sqlite3.Error as e:
                            logger.error(f"Error inserting recursive relationship: {e}")
                logger.info(f"Added {recursive_count} recursive inheritance relationships")
                self.conn.commit()
                logger.info("Successfully populated base_child_links table")
                # Verify that important commit action
                self.cursor.execute("SELECT COUNT(*) FROM base_child_links")
                new_count = self.cursor.fetchone()[0]
                logger.info(f"Created {new_count} base-child links")
        except sqlite3.Error as e:
            logger.error(f"Error populating base_child_links: {e}")
            self.conn.rollback()
    
    def _update_recursive_base_child_links(self, class_uuid: str):
        """Update recursive base-child links for all children of a class
        
        This method ensures that when a class's inheritance is updated,
        all its children also get updated recursive relationships with the
        new ancestors.
        
        Args:
            class_uuid: UUID of the class whose children need updating
        """
        try:
            self.cursor.execute('''
            SELECT child_uuid, access_level FROM base_child_links
            WHERE base_uuid = ? AND direct = TRUE
            ''', (class_uuid,))
            child_rows = self.cursor.fetchall()
            for child_row in child_rows:
                child_uuid = child_row[0]
                child_access_level = child_row[1]
                self.cursor.execute('''
                SELECT base_uuid, depth, access_level FROM base_child_links
                WHERE child_uuid = ? AND child_uuid != ?
                ''', (class_uuid, child_uuid))
                for row in self.cursor.fetchall():
                    ancestor_uuid = row[0]
                    depth = row[1]
                    ancestor_access = row[2]
                    effective_access = child_access_level
                    if ancestor_access == 'PRIVATE' or child_access_level == 'PRIVATE':
                        effective_access = 'PRIVATE'
                    elif ancestor_access == 'PROTECTED' or child_access_level == 'PROTECTED':
                        effective_access = 'PROTECTED'
                    # else keep PUBLIC, code repeated here? time to refactor?
                    self.cursor.execute('''
                    INSERT OR REPLACE INTO base_child_links (base_uuid, child_uuid, direct, depth, access_level)
                    VALUES (?, ?, FALSE, ?, ?)
                    ''', (ancestor_uuid, child_uuid, depth + 1, effective_access))
                self._update_recursive_base_child_links(child_uuid)
                
        except sqlite3.Error as e:
            logger.error(f"Error updating recursive base-child links: {e}")

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
            
    def get_entity_by_uuid(self, uuid: str, include_children: bool = False) -> Optional[Dict[str, Any]]:
        """Get an entity by UUID with optional children
        
        Args:
            uuid: UUID of the entity
            include_children: Whether to include child entities
            
        Returns:
            Entity dictionary with children or None if not found
        """
        try:
            entity = self.get_entity(uuid)
            if not entity:
                return None
            if "METHOD" in entity.get("kind", ""):
                self.cursor.execute('''
                SELECT * FROM method_classification
                WHERE entity_uuid = ?
                ''', (uuid,))
                method_info = self.cursor.fetchone()
                if method_info:
                    entity["method_info"] = dict(method_info)
            if "CLASS" in entity.get("kind", "") or "STRUCT" in entity.get("kind", ""):
                self.cursor.execute('''
                SELECT * FROM class_classification
                WHERE entity_uuid = ?
                ''', (uuid,))
                class_info = self.cursor.fetchone()
                if class_info:
                    entity["class_info"] = dict(class_info)
                self.cursor.execute('''
                SELECT * FROM inheritance
                WHERE class_uuid = ?
                ''', (uuid,))
                base_classes = [dict(row) for row in self.cursor.fetchall()]
                if base_classes:
                    entity["base_classes"] = base_classes
            if include_children and 'children' not in entity:
                self.cursor.execute('''
                SELECT uuid FROM entities
                WHERE parent_uuid = ?
                ''', (uuid,))
                children = []
                for row in self.cursor.fetchall():
                    child = self.get_entity_by_uuid(row[0], include_children=True)
                    if child:
                        children.append(child)
                entity["children"] = children
                
            return entity
        except sqlite3.Error as e:
            logger.error(f"Error getting entity by UUID {uuid}: {e}")
            return None
            
    def get_entities_by_kind(self, kinds: List[str]) -> List[Dict[str, Any]]:
        """Get entities matching specific kinds
        
        Args:
            kinds: List of entity kinds to match
            
        Returns:
            List of entity dictionaries matching the kinds
        """
        try:
            placeholders = ', '.join(['?' for _ in kinds])
            query = f"SELECT uuid FROM entities WHERE kind IN ({placeholders}) AND parent_uuid IS NULL"
            self.cursor.execute(query, kinds)
            entities = []
            for row in self.cursor.fetchall():
                entity = self.get_entity_by_uuid(row[0])
                if entity:
                    entities.append(entity)
            return entities
        except Exception as e:
            logger.error(f"Error getting entities by kind: {e}")
            return []
    
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
                if field_type == 'TEXT':
                    value = row[2]  # text_value
                elif field_type == 'INTEGER':
                    value = row[3]  # int_value
                elif field_type == 'REAL':
                    value = row[4]  # real_value
                elif field_type == 'BOOLEAN':
                    value = bool(row[5])  # bool_value
                elif field_type == 'JSON': # not sure about usefullnes of JSON support here...
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
            return {}
            
    def get_class_stats(self, project_dir: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get detailed information about classes in the codebase
        
        Args:
            project_dir: Optional project directory to filter by (only include classes from files in this dir)
            
        Returns:
            List of class information dictionaries grouped by inheritance hierarchy
        """
        try:
            file_filter = ""
            file_filter_params = []
            if project_dir and project_dir.strip():
                project_dir = os.path.normpath(project_dir)
                logger.debug(f"Filtering classes by project directory: {project_dir}")
                file_filter = "AND file LIKE ? || '%'"
                file_filter_params = [project_dir]
            query = f"""
            SELECT uuid, name, file, line, end_line, parent_uuid
            FROM entities
            WHERE kind IN ('CLASS_DECL', 'CLASS_TEMPLATE', 'STRUCT_DECL', 'STRUCT_TEMPLATE')
            {file_filter}
            """
            
            self.cursor.execute(query, file_filter_params)
            class_dict = {}
            for row in self.cursor.fetchall():
                class_uuid = row[0]
                class_name = row[1]
                decl_file = row[2]
                start_line = row[3]
                end_line = row[4]
                parent_uuid = row[5]
                namespace = self._get_namespace_path(parent_uuid)
                def_files = self._get_definition_files(class_uuid)
                if decl_file and def_files:
                    def_files = [f for f in def_files if os.path.realpath(f) != os.path.realpath(decl_file)]
                uri = f"/api/{namespace.replace('::', '_')}_{class_name}"
                class_info = {
                    "uuid": class_uuid,
                    "name": class_name,
                    "namespace": namespace,
                    "uri": uri,
                    "declaration_file": f"{decl_file}#L{start_line}-L{end_line if end_line else start_line}" if decl_file else None,
                }
                if def_files:
                    class_info["definition_files"] = def_files
                class_dict[class_uuid] = class_info
            try:
                self.cursor.execute("SELECT COUNT(*) FROM base_child_links")
                has_base_child_links = self.cursor.fetchone()[0] > 0
                if has_base_child_links:
                    query = f"""
                    SELECT DISTINCT e.uuid 
                    FROM entities e
                    JOIN base_child_links bcl ON e.uuid = bcl.base_uuid
                    WHERE e.kind IN ('CLASS_DECL', 'CLASS_TEMPLATE', 'STRUCT_DECL', 'STRUCT_TEMPLATE')
                    AND e.uuid NOT IN (SELECT child_uuid FROM base_child_links WHERE direct = TRUE)
                    {file_filter}
                    """
                    self.cursor.execute(query, file_filter_params)
                    root_uuids = [row[0] for row in self.cursor.fetchall()]
                    if not root_uuids:
                        root_uuids = list(class_dict.keys())
                    result = []
                    root_uuids.sort(key=lambda uuid: class_dict.get(uuid, {}).get("name", ""))
                    
                    for i, root_uuid in enumerate(root_uuids):
                        if i > 0:
                            result.append({"name": "<<separator>>"})
                            
                        if root_uuid in class_dict:
                            root_info = class_dict[root_uuid].copy()
                            root_info.pop("uuid", None)
                            result.append(root_info)
                            query = f"""
                            SELECT e.uuid 
                            FROM entities e
                            JOIN base_child_links bcl ON e.uuid = bcl.child_uuid
                            WHERE bcl.base_uuid = ? AND bcl.direct = TRUE
                            {file_filter}
                            ORDER BY e.name
                            """
                            params = [root_uuid] + file_filter_params
                            self.cursor.execute(query, params)
                            for row in self.cursor.fetchall():
                                child_uuid = row[0]
                                if child_uuid in class_dict:
                                    child_info = class_dict[child_uuid].copy()
                                    child_info.pop("uuid", None)
                                    result.append(child_info)
                    return result
                    
            except (sqlite3.Error, Exception) as e:
                logger.debug(f"Using simple class listing due to: {e}")

            result = []
            for class_info in sorted(class_dict.values(), key=lambda c: c["name"]):
                clean_info = class_info.copy()
                clean_info.pop("uuid", None)
                result.append(clean_info)
                
            return result
        except sqlite3.Error as e:
            logger.error(f"Error getting class statistics: {e}")
            return []
    
    def _get_namespace_path(self, entity_uuid: str) -> str:
        """Get the fully qualified namespace path for an entity
        
        Args:
            entity_uuid: UUID of the entity
            
        Returns:
            Fully qualified namespace path (e.g. 'std::vector')
        """
        try:
            path = []
            current_uuid = entity_uuid
            while current_uuid:
                self.cursor.execute('''
                SELECT name, kind, parent_uuid FROM entities
                WHERE uuid = ?
                ''', (current_uuid,))
                row = self.cursor.fetchone()
                if not row:
                    break
                name, kind, parent_uuid = row
                if kind == 'NAMESPACE':
                    path.append(name)
                current_uuid = parent_uuid
            path.reverse()
            return '::'.join(path) if path else ""
        except sqlite3.Error as e:
            logger.error(f"Error getting namespace path: {e}")
            return ""
    
    def link_declaration_definition(self, decl_uuid: str, def_uuid: str) -> bool:
        """Link a declaration to its definition
        
        Args:
            decl_uuid: UUID of the declaration entity
            def_uuid: UUID of the definition entity
            
        Returns:
            True if link was successfully created, False otherwise
        """
        try:
            self.cursor.execute('''
            INSERT OR IGNORE INTO decl_def_links (decl_uuid, def_uuid)
            VALUES (?, ?)
            ''', (decl_uuid, def_uuid))
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Error linking declaration to definition: {e}")
            return False
    
    def get_entity_definitions(self, decl_uuid: str) -> List[Dict[str, Any]]:
        """Get all definitions of an entity
        
        Args:
            decl_uuid: UUID of the declaration entity
            
        Returns:
            List of definition entity dictionaries
        """
        try:
            self.cursor.execute('''
            SELECT def_uuid FROM decl_def_links
            WHERE decl_uuid = ?
            ''', (decl_uuid,))
            
            definitions = []
            for row in self.cursor.fetchall():
                definition = self.get_entity_by_uuid(row[0])
                if definition:
                    definitions.append(definition)
            
            return definitions
        except sqlite3.Error as e:
            logger.error(f"Error getting entity definitions: {e}")
            return []
    
    def get_entity_declaration(self, def_uuid: str) -> Optional[Dict[str, Any]]:
        """Get the declaration of an entity
        
        Args:
            def_uuid: UUID of the definition entity
            
        Returns:
            Declaration entity dictionary or None if not found
        """
        try:
            self.cursor.execute('''
            SELECT decl_uuid FROM decl_def_links
            WHERE def_uuid = ?
            ''', (def_uuid,))
            
            row = self.cursor.fetchone()
            if row:
                return self.get_entity_by_uuid(row[0])
            return None
        except sqlite3.Error as e:
            logger.error(f"Error getting entity declaration: {e}")
            return None
    
    def _get_definition_files(self, class_uuid: str) -> List[str]:
        """Get all definition files for a class
        
        Args:
            class_uuid: UUID of the class
            
        Returns:
            List of file paths where the class is defined
        """
        try:
            files = set()
            self.cursor.execute('''
            SELECT DISTINCT file FROM entities
            WHERE parent_uuid = ? AND kind LIKE '%METHOD%' AND file IS NOT NULL
            ''', (class_uuid,))
            
            for row in self.cursor.fetchall():
                files.add(row[0])
            self.cursor.execute('''
            SELECT e.file FROM entities e
            JOIN decl_def_links l ON e.uuid = l.def_uuid
            WHERE l.decl_uuid = ? AND e.file IS NOT NULL
            ''', (class_uuid,))
            
            for row in self.cursor.fetchall():
                files.add(row[0])
            self.cursor.execute('''
            SELECT e2.file FROM entities e1
            JOIN decl_def_links l ON e1.uuid = l.decl_uuid
            JOIN entities e2 ON e2.uuid = l.def_uuid
            WHERE e1.parent_uuid = ? AND e2.file IS NOT NULL
            ''', (class_uuid,))
            
            for row in self.cursor.fetchall():
                files.add(row[0])
            self.cursor.execute('''
            SELECT file FROM entities WHERE uuid = ?
            ''', (class_uuid,))
            
            decl_row = self.cursor.fetchone()
            if decl_row and decl_row[0]:
                decl_file = decl_row[0]
                if decl_file.endswith(tuple(CPP_HEADER_EXTENSIONS)):
                    base_name = os.path.splitext(decl_file)[0]
                    impl_extensions = tuple(CPP_IMPLEM_EXTENSIONS)
                    for ext in impl_extensions:
                        impl_file = base_name + ext
                        if os.path.exists(impl_file):
                            files.add(impl_file)
                
            return list(files)
        except sqlite3.Error as e:
            logger.error(f"Error getting definition files: {e}")
            return []
    
    def get_namespace_stats(self, project_dir: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get statistics about namespaces in the codebase
        
        Args:
            project_dir: Optional project directory to filter by (only include namespaces from files in this dir)
            
        Returns:
            List of namespace statistics with counts for different entity types
        """
        try:
            file_filter = ""
            file_filter_params = []
            if project_dir and project_dir.strip():
                project_dir = os.path.normpath(project_dir)
                logger.debug(f"Filtering namespaces by project directory: {project_dir}")
                file_filter = "AND file LIKE ? || '%'"
                file_filter_params = [project_dir]
            query = f"""
            SELECT DISTINCT e.name 
            FROM entities e
            WHERE e.kind = 'NAMESPACE'
            {file_filter}
            ORDER BY e.name
            """
            self.cursor.execute(query, file_filter_params)
            namespace_names = [row[0] for row in self.cursor.fetchall()]
            
            if not namespace_names:
                logger.warning(f"No namespaces found{' in project directory' if project_dir else ''}")
                return []
                
            logger.debug(f"Found {len(namespace_names)} unique namespaces: {', '.join(namespace_names)}")
            
            namespaces = []
            for ns_name in namespace_names:
                query = f"""
                SELECT uuid FROM entities 
                WHERE kind = 'NAMESPACE' AND name = ?
                {file_filter}
                """
                
                self.cursor.execute(query, [ns_name] + file_filter_params)
                ns_uuids = [row[0] for row in self.cursor.fetchall()]
                if not ns_uuids:
                    continue  # Skip if no instances in project files
                
                total_classes = 0
                total_functions = 0
                for ns_uuid in ns_uuids:
                    self.cursor.execute(f"""
                    SELECT COUNT(*) FROM entities 
                    WHERE parent_uuid = ? AND 
                          (kind LIKE '%CLASS%' OR kind LIKE '%STRUCT%')
                    {file_filter}
                    """, [ns_uuid] + file_filter_params)
                    total_classes += self.cursor.fetchone()[0]
                    self.cursor.execute(f"""
                    SELECT COUNT(*) FROM entities 
                    WHERE parent_uuid = ? AND 
                          (kind LIKE '%FUNCTION%' OR kind = 'CXX_METHOD')
                    {file_filter}
                    """, [ns_uuid] + file_filter_params)
                    total_functions += self.cursor.fetchone()[0]
                if total_classes > 0 or total_functions > 0:
                    namespaces.append({
                        "name": ns_name,
                        "n_classes": total_classes,
                        "n_functions": total_functions
                    })
            namespaces.sort(key=lambda x: x["name"])
            
            return namespaces
        except sqlite3.Error as e:
            logger.error(f"Error getting namespace statistics: {e}")
            return []
