import mysql.connector

try:
    # Try connecting with your details
    conn = mysql.connector.connect(
        host='localhost',
        user='inventory_user', 
        password='1234',
        database='smart_inventory_db'
    )
    print("✅ SUCCESS! Connected to the database.")
    
    # Check if tables exist
    cursor = conn.cursor()
    cursor.execute("SHOW TABLES")
    tables = cursor.fetchall()
    print("📂 Found Tables:", tables)
    
    conn.close()

except Exception as e:
    print("❌ CONNECTION FAILED:", e)