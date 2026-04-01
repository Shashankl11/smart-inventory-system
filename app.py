import os
import io
import random
import base64
from datetime import datetime

import pandas as pd
import matplotlib.pyplot as plt
import mysql.connector
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_mail import Mail, Message

app = Flask(__name__)
app.secret_key = 'your_smart_inventory_secret'

# --- 1. CONFIGURATION ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'shashankl2005@gmail.com' 
app.config['MAIL_PASSWORD'] = 'lkal osgl zrjn nsqs' 
mail = Mail(app)

# --- 2. DATABASE HELPER ---
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="inventory_user",
        password="1234", 
        database="smart_inventory_db"
    )

# --- 3. AUTHENTICATION & FORGOT PASSWORD ---

@app.route('/', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username = %s AND password = %s", (username, password))
        user = cursor.fetchone()
        cursor.close()
        db.close()
        if user:
            session['user'] = username 
            return redirect(url_for('dashboard'))
        return "Invalid Login! <a href='/'>Try again</a>"
    return render_template('login.html')

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form['username']
        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        if user:
            otp = str(random.randint(1000, 9999))
            cursor.execute("UPDATE users SET otp = %s WHERE username = %s", (otp, username))
            db.commit()
            cursor.close()
            db.close()
            msg = Message('Your OTP', sender=app.config['MAIL_USERNAME'], recipients=[user['email']])
            msg.body = f"Your OTP for Smart Inventory is: {otp}"
            mail.send(msg)
            return render_template('verify_otp.html', username=username)
        db.close()
        return "User not found!"
    return render_template('forgot_password.html')

@app.route('/verify-otp', methods=['POST'])
def verify_otp():
    username = request.form['username']
    user_otp = request.form['otp']
    new_password = request.form['new_password']
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT otp FROM users WHERE username = %s", (username,))
    res = cursor.fetchone()
    if res and res['otp'] == user_otp:
        cursor.execute("UPDATE users SET password = %s, otp = NULL WHERE username = %s", (new_password, username))
        db.commit()
        cursor.close()
        db.close()
        return f"Success! <a href='{url_for('login_page')}'>Login Now</a>"
    return "Invalid OTP"

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login_page'))

# --- 4. DASHBOARD & ANALYTICS ---

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login_page'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT COUNT(*) as count FROM products")
    p_count = cursor.fetchone()['count']
    
    cursor.execute("SELECT SUM(quantity) as total FROM transactions WHERE txn_type='OUT'")
    res_sales = cursor.fetchone()
    s_count = res_sales['total'] if res_sales['total'] else 0
    
    cursor.execute("SELECT SUM(current_stock) as total_stock FROM products")
    res_stock = cursor.fetchone()
    st_count = res_stock['total_stock'] if res_stock['total_stock'] else 0
    
    low_stock_text = ""
    current_month = datetime.now().strftime("%B") 
    
    try:
        cursor.execute("SELECT name, current_stock, season_tag FROM products")
        all_prods = cursor.fetchall()
        
        alerts = []
        for p in all_prods:
            if p['current_stock'] < 10:
                alerts.append(f"Low Stock: {p['name']} ({p['current_stock']})")
            
            if p['season_tag'] == current_month or p['season_tag'] == 'All':
                if p['current_stock'] < 20: 
                    alerts.append(f"Seasonal Demand: {p['name']} is trending in {current_month}!")

        low_stock_text = " | ".join(alerts) if alerts else "Inventory Healthy ✅"

        cursor.execute("""
            SELECT p.name, SUM(t.quantity) as total_sold FROM transactions t
            JOIN products p ON t.product_id = p.product_id WHERE t.txn_type = 'OUT'
            GROUP BY t.product_id ORDER BY total_sold DESC LIMIT 3
        """)
        top_items = cursor.fetchall()
        trending_text = " | ".join([f"{item['name']} ({item['total_sold']} sold)" for item in top_items]) if top_items else "Waiting for sales..."
            
    except Exception as e:
        low_stock_text = "System Monitoring Active"
        trending_text = "Data Syncing..."

    cursor.close()
    conn.close()

    return render_template('dashboard.html', 
                           p_count=p_count, 
                           s_count=s_count, 
                           st_count=st_count, 
                           low_stock=low_stock_text, 
                           trending_text=trending_text)

@app.route('/analytics')
def analytics():
    if 'user' not in session:
        return redirect(url_for('login_page'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # 1. Fetch Products for Analytics
    query = '''
        SELECT p.name, p.base_price, p.current_stock, p.season_tag, 
               COALESCE(SUM(t.quantity), 0) as total_sold
        FROM products p
        LEFT JOIN transactions t ON p.product_id = t.product_id AND t.txn_type = 'OUT'
        GROUP BY p.product_id
    '''
    df = pd.read_sql(query, conn)
    
    # 2. Fetch Customer List for the Marketing Table
    cursor.execute("SELECT name, email FROM customers")
    customers = cursor.fetchall()
    
    conn.close()
    
    alerts = []
    current_month = datetime.now().strftime("%B")
    df['suggested_price'] = df.apply(lambda x: x['base_price'] * 1.10 if x['total_sold'] > 10 else x['base_price'], axis=1)
    
    for index, row in df.iterrows():
        if row['season_tag'] in current_month or row['season_tag'] == 'All':
            if row['current_stock'] < 5:
                alerts.append(f"CRITICAL: {row['name']} is seasonal ({row['season_tag']}) and stock is LOW!")
        
        if row['total_sold'] > 10:
             alerts.append(f"OPPORTUNITY: {row['name']} is in high demand. Suggested price: ₹{row['suggested_price']:.2f}")

    # Charts
    plt.switch_backend('Agg')
    img = io.BytesIO()
    plt.figure(figsize=(10,6))
    plt.bar(df['name'], df['total_sold'], color='skyblue')
    plt.xlabel('Products')
    plt.ylabel('Units Sold')
    plt.title('Sales Performance')
    plt.savefig(img, format='png')
    plt.close() 
    img.seek(0)
    plot_url = base64.b64encode(img.getvalue()).decode()
    
    return render_template('analytics.html', 
                           alerts=alerts, 
                           plot_url=plot_url, 
                           data=df.to_dict(orient='records'),
                           customers=customers)

# --- 5. PRODUCTS & TRANSACTIONS ---

@app.route('/products', methods=['GET', 'POST'])
def products():
    if 'user' not in session: 
        return redirect(url_for('login_page'))
    
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    if request.method == 'POST':
        name = request.form['name']
        price = request.form['price']
        stock = request.form['stock']
        season = request.form['season']
        
        query = "INSERT INTO products (name, base_price, current_stock, season_tag) VALUES (%s, %s, %s, %s)"
        cursor.execute(query, (name, price, stock, season))
        db.commit()
        flash("Product Added Successfully!")
        return redirect(url_for('products'))

    cursor.execute("SELECT * FROM products")
    items = cursor.fetchall()
    cursor.close()
    db.close()
    return render_template('products.html', items=items)

@app.route('/transactions', methods=['GET', 'POST'])
def transactions():
    if 'user' not in session: return redirect(url_for('login_page'))
    
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    if request.method == 'POST':
        p_id = request.form['product_id']
        t_type = request.form['type']
        qty = int(request.form['quantity'])
        
        cursor.execute("INSERT INTO transactions (product_id, txn_type, quantity, txn_date) VALUES (%s, %s, %s, NOW())", (p_id, t_type, qty))
        
        if t_type == 'OUT':
            cursor.execute("UPDATE products SET current_stock = current_stock - %s WHERE product_id = %s", (qty, p_id))
        else:
            cursor.execute("UPDATE products SET current_stock = current_stock + %s WHERE product_id = %s", (qty, p_id))
            
        db.commit()

    cursor.execute("SELECT product_id, name, current_stock FROM products")
    products = cursor.fetchall()
    
    cursor.execute("""
        SELECT t.*, p.name 
        FROM transactions t 
        JOIN products p ON t.product_id = p.product_id 
        ORDER BY t.txn_date DESC
    """)
    history = cursor.fetchall()
    
    cursor.close()
    db.close()
    
    return render_template('transactions.html', products=products, history=history)

@app.route('/billing')
def billing():
    if 'user' not in session: return redirect(url_for('login_page'))
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT product_id, name, base_price, current_stock FROM products WHERE current_stock > 0")
    products = cursor.fetchall()
    cursor.close()
    db.close()
    return render_template('billing.html', products=products)

@app.route('/process-bill', methods=['POST'])
def process_bill():
    p_id = request.form['product_id']
    qty = int(request.form['quantity'])
    c_name = request.form['cust_name']
    c_email = request.form['cust_email']
    
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    if c_email:
        cursor.execute("INSERT IGNORE INTO customers (name, email, phone) VALUES (%s, %s, %s)", 
                       (c_name, c_email, request.form['cust_phone']))

    cursor.execute("UPDATE products SET current_stock = current_stock - %s WHERE product_id = %s", (qty, p_id))
    cursor.execute("INSERT INTO transactions (product_id, txn_type, quantity, txn_date) VALUES (%s, 'OUT', %s, NOW())", (p_id, qty))
    db.commit()

    if c_email:
        try:
            msg = Message('Receipt & Welcome to Our Store! 🎉', sender=app.config['MAIL_USERNAME'], recipients=[c_email])
            msg.body = f"Hi {c_name},\n\nThank you for your purchase! You are now registered for exclusive discounts.\n\nSmart Inventory Team"
            mail.send(msg)
        except: pass

    cursor.close()
    db.close()
    return f"<h1>Success!</h1><p>Bill Generated and Customer Notified.</p><a href='/dashboard'>Back</a>"

# --- 6. SELECTIVE MARKETING LOGIC ---

@app.route('/notify-selected-customers', methods=['POST'])
def notify_selected():
    if 'user' not in session: return redirect(url_for('login_page'))
    
    selected_emails = request.form.getlist('selected_emails')
    if not selected_emails:
        return "No customers selected! <a href='/analytics'>Go back</a>"

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    cursor.execute("SELECT name, base_price FROM products ORDER BY product_id DESC LIMIT 3")
    new_items = cursor.fetchall()
    
    item_details = "".join([f"• {item['name']} (₹{item['base_price']})\n" for item in new_items])

    try:
        with mail.connect() as conn:
            for email in selected_emails:
                msg = Message("✨ New Arrivals Just For You! ✨",
                              sender=app.config['MAIL_USERNAME'],
                              recipients=[email])
                msg.body = f"Hello,\n\nWe've just added some fresh items to our stock:\n\n{item_details}\n\nVisit us soon!"
                conn.send(msg)
    except Exception as e:
        print(f"Error: {e}")

    cursor.close()
    db.close()
    return redirect(url_for('analytics'))

if __name__ == '__main__':
    app.run()