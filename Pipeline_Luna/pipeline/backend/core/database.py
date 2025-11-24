"""
Database Foundation Module
==========================
Foundation for future MySQL database integration.
Currently provides interface structure and SQLite fallback.

When ready to deploy with MySQL:
1. Set DATABASE_CONFIG['enabled'] = True in config.py
2. Update MySQL credentials in config.py
3. Run: python -m pipeline.backend.core.database init
4. Test connection: python -m pipeline.backend.core.database test
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path
import json

logger = logging.getLogger(__name__)

# =============================================================================
# DATABASE INTERFACE (Abstract Base)
# =============================================================================

class DatabaseInterface:
    """Abstract interface for database operations."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.connected = False
    
    def connect(self):
        """Establish database connection."""
        raise NotImplementedError
    
    def disconnect(self):
        """Close database connection."""
        raise NotImplementedError
    
    def insert_violation(self, violation_data: Dict[str, Any]) -> str:
        """Insert a violation record. Returns report_id."""
        raise NotImplementedError
    
    def get_violation(self, report_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a violation by report_id."""
        raise NotImplementedError
    
    def get_violations_by_timeframe(self, start: datetime, end: datetime) -> List[Dict[str, Any]]:
        """Retrieve violations within a timeframe."""
        raise NotImplementedError
    
    def get_recent_violations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve most recent violations."""
        raise NotImplementedError
    
    def update_violation(self, report_id: str, updates: Dict[str, Any]) -> bool:
        """Update a violation record."""
        raise NotImplementedError
    
    def delete_violation(self, report_id: str) -> bool:
        """Delete a violation record."""
        raise NotImplementedError

# =============================================================================
# SQLITE IMPLEMENTATION (Fallback/Development)
# =============================================================================

class SQLiteDatabase(DatabaseInterface):
    """SQLite implementation for development and testing."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.db_path = config.get('database', 'violations.db')
        self.conn = None
        self.cursor = None
        logger.info(f"SQLite database path: {self.db_path}")
    
    def connect(self):
        """Establish SQLite connection."""
        try:
            import sqlite3
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row  # Enable column access by name
            self.cursor = self.conn.cursor()
            self.connected = True
            self._create_tables()
            logger.info("SQLite database connected successfully")
        except Exception as e:
            logger.error(f"Failed to connect to SQLite: {e}")
            raise
    
    def _create_tables(self):
        """Create tables if they don't exist."""
        # Violations table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS violations (
                report_id VARCHAR(50) PRIMARY KEY,
                timeframe DATETIME NOT NULL,
                violation_summary TEXT,
                person_count INTEGER,
                violation_count INTEGER,
                image_path VARCHAR(500),
                annotated_image_path VARCHAR(500),
                caption TEXT,
                nlp_analysis TEXT,
                report_html_path VARCHAR(500),
                report_pdf_path VARCHAR(500),
                detection_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create indexes
        self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_timeframe ON violations(timeframe)
        ''')
        self.cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_created_at ON violations(created_at)
        ''')
        
        self.conn.commit()
        logger.debug("SQLite tables created/verified")
    
    def disconnect(self):
        """Close SQLite connection."""
        if self.conn:
            self.conn.close()
            self.connected = False
            logger.info("SQLite database disconnected")
    
    def insert_violation(self, violation_data: Dict[str, Any]) -> str:
        """Insert a violation record."""
        report_id = violation_data.get('report_id')
        
        # Convert JSON fields to strings
        nlp_analysis = json.dumps(violation_data.get('nlp_analysis')) if violation_data.get('nlp_analysis') else None
        detection_data = json.dumps(violation_data.get('detection_data')) if violation_data.get('detection_data') else None
        
        self.cursor.execute('''
            INSERT INTO violations (
                report_id, timeframe, violation_summary, person_count, violation_count,
                image_path, annotated_image_path, caption, nlp_analysis,
                report_html_path, report_pdf_path, detection_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            report_id,
            violation_data.get('timeframe'),
            violation_data.get('violation_summary'),
            violation_data.get('person_count'),
            violation_data.get('violation_count'),
            violation_data.get('image_path'),
            violation_data.get('annotated_image_path'),
            violation_data.get('caption'),
            nlp_analysis,
            violation_data.get('report_html_path'),
            violation_data.get('report_pdf_path'),
            detection_data
        ))
        
        self.conn.commit()
        logger.info(f"Inserted violation: {report_id}")
        return report_id
    
    def get_violation(self, report_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a violation by report_id."""
        self.cursor.execute('SELECT * FROM violations WHERE report_id = ?', (report_id,))
        row = self.cursor.fetchone()
        
        if row:
            data = dict(row)
            # Parse JSON fields
            if data.get('nlp_analysis'):
                data['nlp_analysis'] = json.loads(data['nlp_analysis'])
            if data.get('detection_data'):
                data['detection_data'] = json.loads(data['detection_data'])
            return data
        return None
    
    def get_violations_by_timeframe(self, start: datetime, end: datetime) -> List[Dict[str, Any]]:
        """Retrieve violations within a timeframe."""
        self.cursor.execute('''
            SELECT * FROM violations 
            WHERE timeframe BETWEEN ? AND ?
            ORDER BY timeframe DESC
        ''', (start.isoformat(), end.isoformat()))
        
        rows = self.cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]
    
    def get_recent_violations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve most recent violations."""
        self.cursor.execute('''
            SELECT * FROM violations 
            ORDER BY created_at DESC 
            LIMIT ?
        ''', (limit,))
        
        rows = self.cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]
    
    def update_violation(self, report_id: str, updates: Dict[str, Any]) -> bool:
        """Update a violation record."""
        # Build UPDATE query dynamically
        set_clauses = []
        values = []
        
        for key, value in updates.items():
            if key in ['nlp_analysis', 'detection_data'] and value:
                value = json.dumps(value)
            set_clauses.append(f"{key} = ?")
            values.append(value)
        
        if not set_clauses:
            return False
        
        values.append(report_id)
        query = f"UPDATE violations SET {', '.join(set_clauses)}, updated_at = CURRENT_TIMESTAMP WHERE report_id = ?"
        
        self.cursor.execute(query, values)
        self.conn.commit()
        
        logger.info(f"Updated violation: {report_id}")
        return self.cursor.rowcount > 0
    
    def delete_violation(self, report_id: str) -> bool:
        """Delete a violation record."""
        self.cursor.execute('DELETE FROM violations WHERE report_id = ?', (report_id,))
        self.conn.commit()
        
        logger.info(f"Deleted violation: {report_id}")
        return self.cursor.rowcount > 0
    
    def _row_to_dict(self, row) -> Dict[str, Any]:
        """Convert SQLite row to dictionary."""
        data = dict(row)
        # Parse JSON fields
        if data.get('nlp_analysis'):
            try:
                data['nlp_analysis'] = json.loads(data['nlp_analysis'])
            except:
                pass
        if data.get('detection_data'):
            try:
                data['detection_data'] = json.loads(data['detection_data'])
            except:
                pass
        return data

# =============================================================================
# MYSQL IMPLEMENTATION (Foundation for future use)
# =============================================================================

class MySQLDatabase(DatabaseInterface):
    """MySQL implementation - foundation for production deployment."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.host = config.get('host', 'localhost')
        self.port = config.get('port', 3306)
        self.database = config.get('database', 'ppe_compliance')
        self.user = config.get('user', 'ppe_user')
        self.password = config.get('password', '')
        self.conn = None
        self.cursor = None
        logger.info(f"MySQL database configured: {self.user}@{self.host}:{self.port}/{self.database}")
    
    def connect(self):
        """Establish MySQL connection."""
        try:
            import mysql.connector
            from mysql.connector import pooling
            
            self.conn = mysql.connector.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                charset='utf8mb4',
                autocommit=False
            )
            
            self.cursor = self.conn.cursor(dictionary=True)
            self.connected = True
            self._create_tables()
            logger.info("MySQL database connected successfully")
            
        except ImportError:
            logger.error("mysql-connector-python not installed. Install with: pip install mysql-connector-python")
            raise
        except Exception as e:
            logger.error(f"Failed to connect to MySQL: {e}")
            raise
    
    def _create_tables(self):
        """Create MySQL tables if they don't exist."""
        # Violations table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS violations (
                report_id VARCHAR(50) PRIMARY KEY,
                timeframe DATETIME NOT NULL,
                violation_summary TEXT,
                person_count INT,
                violation_count INT,
                image_path VARCHAR(500),
                annotated_image_path VARCHAR(500),
                caption TEXT,
                nlp_analysis JSON,
                report_html_path VARCHAR(500),
                report_pdf_path VARCHAR(500),
                detection_data JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_timeframe (timeframe),
                INDEX idx_created_at (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        ''')
        
        self.conn.commit()
        logger.debug("MySQL tables created/verified")
    
    def disconnect(self):
        """Close MySQL connection."""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        self.connected = False
        logger.info("MySQL database disconnected")
    
    def insert_violation(self, violation_data: Dict[str, Any]) -> str:
        """Insert a violation record into MySQL."""
        report_id = violation_data.get('report_id')
        
        self.cursor.execute('''
            INSERT INTO violations (
                report_id, timeframe, violation_summary, person_count, violation_count,
                image_path, annotated_image_path, caption, nlp_analysis,
                report_html_path, report_pdf_path, detection_data
            ) VALUES (
                %(report_id)s, %(timeframe)s, %(violation_summary)s, %(person_count)s, %(violation_count)s,
                %(image_path)s, %(annotated_image_path)s, %(caption)s, %(nlp_analysis)s,
                %(report_html_path)s, %(report_pdf_path)s, %(detection_data)s
            )
        ''', violation_data)
        
        self.conn.commit()
        logger.info(f"Inserted violation: {report_id}")
        return report_id
    
    # ... (similar implementations for get, update, delete methods)
    # NOTE: Implementation follows same pattern as SQLite but with MySQL-specific syntax

# =============================================================================
# DATABASE FACTORY
# =============================================================================

def get_database(config: Dict[str, Any]) -> DatabaseInterface:
    """
    Factory function to create database instance based on configuration.
    
    Args:
        config: Database configuration dict
    
    Returns:
        DatabaseInterface instance (SQLite or MySQL)
    """
    db_type = config.get('type', 'sqlite').lower()
    
    if db_type == 'mysql':
        db_config = config.get('mysql', {})
        return MySQLDatabase(db_config)
    elif db_type == 'sqlite':
        db_config = config.get('sqlite', {})
        return SQLiteDatabase(db_config)
    else:
        raise ValueError(f"Unsupported database type: {db_type}")


# =============================================================================
# COMMAND LINE INTERFACE
# =============================================================================

if __name__ == '__main__':
    import sys
    from pathlib import Path
    
    # Add parent directory to path for imports
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.absolute()))
    from config import DATABASE_CONFIG
    
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == 'init':
            print("Initializing database...")
            db = get_database(DATABASE_CONFIG)
            db.connect()
            print("[OK] Database initialized successfully")
            db.disconnect()
        
        elif command == 'test':
            print("Testing database connection...")
            db = get_database(DATABASE_CONFIG)
            db.connect()
            
            # Test insert
            test_data = {
                'report_id': 'TEST_20251105_120000',
                'timeframe': datetime.now(),
                'violation_summary': 'Test violation',
                'person_count': 1,
                'violation_count': 1,
            }
            report_id = db.insert_violation(test_data)
            print(f"[OK] Inserted test violation: {report_id}")
            
            # Test retrieve
            violation = db.get_violation(report_id)
            print(f"[OK] Retrieved violation: {violation['report_id']}")
            
            # Test delete
            db.delete_violation(report_id)
            print(f"[OK] Deleted test violation")
            
            db.disconnect()
            print("[OK] All tests passed!")
        
        else:
            print(f"Unknown command: {command}")
            print("Available commands: init, test")
    else:
        print("Usage: python database.py [init|test]")
