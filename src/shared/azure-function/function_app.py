import azure.functions as func
import json
import logging
import os
import sqlite3
import tempfile
import urllib.request
from typing import Optional, Dict, Any


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global database connection
db_path = None

def init():
    """Initialize the database when the function starts."""
    global db_path
    
    # Try to find the database file in the function package
    function_dir = os.path.dirname(os.path.abspath(__file__))
    packaged_db_path = os.path.join(function_dir, 'contoso-sales.db')
    
    if os.path.exists(packaged_db_path):
        logger.info(f"Using packaged database: {packaged_db_path}")
        db_path = packaged_db_path
        return db_path
    
    # Create a minimal sample database
    logger.warning("No database found, creating sample data")
    return create_sample_database()

def create_sample_database():
    """Create a minimal sample database for demonstration."""
    temp_dir = tempfile.gettempdir()
    sample_db_path = os.path.join(temp_dir, 'sample-sales.db')
    
    try:
        conn = sqlite3.connect(sample_db_path)
        cursor = conn.cursor()
        
        # Create a simple sales_data table with sample data
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sales_data (
                id INTEGER PRIMARY KEY,
                region TEXT,
                product_type TEXT,
                revenue REAL,
                year INTEGER
            )
        ''')
        
        # Insert sample data
        sample_data = [
            (1, 'NORTH AMERICA', 'Tent', 1500000.0, 2023),
            (2, 'EUROPE', 'Tent', 1200000.0, 2023),
            (3, 'ASIA', 'Tent', 900000.0, 2023),
            (4, 'NORTH AMERICA', 'Sleeping Bag', 800000.0, 2023),
            (5, 'EUROPE', 'Sleeping Bag', 600000.0, 2023),
        ]
        
        cursor.executemany(
            'INSERT OR REPLACE INTO sales_data (id, region, product_type, revenue, year) VALUES (?, ?, ?, ?, ?)',
            sample_data
        )
        conn.commit()
        conn.close()
        
        logger.info(f"Created sample database: {sample_db_path}")
        return sample_db_path
        
    except Exception as e:
        logger.error(f"Failed to create sample database: {e}")
        return None

def execute_query(query: str) -> Dict[str, Any]:
    """Execute a SQLite query and return results."""
    global db_path
    
    if not db_path:
        db_path = init()
    
    if not db_path or not os.path.exists(db_path):
        return {"error": "Database not available"}
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute(query)
        
        if query.strip().upper().startswith('SELECT'):
            rows = cursor.fetchall()
            columns = [description[0] for description in cursor.description]
            
            # Convert to list of dictionaries
            data = []
            for row in rows:
                data.append(dict(zip(columns, row)))
            
            result = {
                "data": data,
                "columns": columns,
                "row_count": len(rows)
            }
        else:
            conn.commit()
            result = {"message": "Query executed successfully", "rows_affected": cursor.rowcount}
        
        conn.close()
        return result
        
    except Exception as e:
        logger.error(f"Database query error: {e}")
        return {"error": str(e)}

def get_database_info() -> Dict[str, Any]:
    """Get information about the database."""
    global db_path
    
    if not db_path:
        db_path = init()
    
    if not db_path or not os.path.exists(db_path):
        return {"error": "Database not available"}
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get table names
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        table_info = {}
        for table in tables:
            cursor.execute(f"PRAGMA table_info({table})")
            columns = cursor.fetchall()
            
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            row_count = cursor.fetchone()[0]
            
            table_info[table] = {
                "columns": [{"name": col[1], "type": col[2]} for col in columns],
                "row_count": row_count
            }
        
        conn.close()
        
        return {
            "database_path": db_path,
            "tables": table_info,
            "total_tables": len(tables)
        }
        
    except Exception as e:
        logger.error(f"Database info error: {e}")
        return {"error": str(e)}

# Initialize the app
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    """Health check endpoint."""
    return func.HttpResponse(
        json.dumps({"status": "healthy", "message": "Contoso Sales API is running"}),
        status_code=200,
        headers={"Content-Type": "application/json"}
    )

@app.route(route="database-info", methods=["GET"])
def database_info(req: func.HttpRequest) -> func.HttpResponse:
    """Get database information."""
    try:
        info = get_database_info()
        return func.HttpResponse(
            json.dumps(info, indent=2),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )
    except Exception as e:
        logger.error(f"Database info endpoint error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )

@app.route(route="query-sales-data", methods=["POST"])
def query_sales_data(req: func.HttpRequest) -> func.HttpResponse:
    """Execute a SQLite query on the sales data."""
    try:
        # Parse request body
        try:
            req_body = req.get_json()
        except ValueError:
            return func.HttpResponse(
                json.dumps({"error": "Invalid JSON in request body"}),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )
        
        if not req_body or 'query' not in req_body:
            return func.HttpResponse(
                json.dumps({"error": "Missing 'query' field in request body"}),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )
        
        query = req_body['query']
        
        if not query or not query.strip():
            return func.HttpResponse(
                json.dumps({"error": "Query cannot be empty"}),
                status_code=400,
                headers={"Content-Type": "application/json"}
            )
        
        # Execute query
        result = execute_query(query)
        
        return func.HttpResponse(
            json.dumps(result, indent=2),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )
        
    except Exception as e:
        logger.error(f"Query endpoint error: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )
