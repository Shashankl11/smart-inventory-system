import os
import io
import random
import base64
from datetime import datetime
from fpdf import FPDF
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
        host="gateway01.ap-southeast-1.prod.aws.tidbcloud.com",
        port=4000,
        user="3PjPePMAuQ4PBWV.root",
        password="0TZTpeBYQ304T84q",
        database="test",
        ssl_verify_cert=True 
    )

# --- 3. AUTHENTICATION & FORGOT PASSWORD ---

@app.route('/', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        try:
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
        except Exception as e:
            return f"Database Error: {e}"
    return render_template('login.html')

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form['username']
        try:
            db = get_db_connection()
            cursor = db.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if user:
                otp = str(random.randint(1000, 9999))
                # Check if 'otp' column exists, otherwise this might fail
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
        except Exception as e:
            return f"Error: {e}. Make sure 'otp' and 'email' columns exist in users table."
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
    
    # --- SEASON MAPPING ENGINE ---
    current_month = datetime.now().strftime("%B") 
    if current_month in ['March', 'April', 'May']:
        current_season = 'Summer'
    elif current_month in ['June', 'July', 'August', 'September']:
        current_season = 'Monsoon'
    else:
        current_season = 'Winter'
    
    low_stock_text = ""
    
    try:
        # 1. Fetch all products for basic alerts & seasonal discounts
        cursor.execute("SELECT name, current_stock, season_tag, base_price FROM products")
        all_prods = cursor.fetchall()
        
       alerts = []
        for p in all_prods:
            if p['current_stock'] < 10:
                alerts.append(f"⚠️ Low Stock: {p['name']} ({p['current_stock']} left)")
            
            # FIXED: Only strict seasonal items get the 10% discount! No 'All' items.
            if p['season_tag'] == current_season:
                orig_price = float(p['base_price'])
                disc_price = orig_price * 0.90 # 10% off
                alerts.append(f"🎁 {current_season.upper()} OFFER: 10% OFF on {p['name']}! Now ₹{disc_price:.2f}")
                
                if p['current_stock'] < 20: 
                    alerts.append(f"📈 Seasonal Demand: {p['name']} is trending this {current_season}!")

        # FIXED: Ensure 'All' items are NOT put on clearance!
        clearance_query = """
            SELECT p.name, p.base_price 
            FROM products p
            LEFT JOIN transactions t ON p.product_id = t.product_id AND t.txn_type = 'OUT'
            WHERE p.season_tag != %s AND p.season_tag != 'All' AND p.current_stock > 10
            GROUP BY p.product_id, p.name, p.base_price, p.current_stock
            ORDER BY COALESCE(SUM(t.quantity), 0) ASC, p.current_stock DESC
            LIMIT 2
        """
        cursor.execute(clearance_query, (current_season,))
        clearance_items = cursor.fetchall()        cursor.execute(clearance_query, (current_season,))
        clearance_items = cursor.fetchall()
        
        # Append the 15% Clearance deals to the Marquee alerts
        for c in clearance_items:
            orig = float(c['base_price'])
            disc = orig * 0.85 # 15% off
            alerts.append(f"🔥 SPECIAL CLEARANCE: 15% OFF on {c['name']}! Now ₹{disc:.2f}")

        # Combine all alerts into the scrolling marquee text
        low_stock_text = " | ".join(alerts) if alerts else "Inventory Healthy ✅"

        # 3. Fetch Top Trending items
        cursor.execute("""
            SELECT p.name, SUM(t.quantity) as total_sold FROM transactions t
            JOIN products p ON t.product_id = p.product_id WHERE t.txn_type = 'OUT'
            GROUP BY t.product_id ORDER BY total_sold DESC LIMIT 3
        """)
        top_items = cursor.fetchall()
        trending_text = " | ".join([f"{item['name']} ({item['total_sold']} sold)" for item in top_items]) if top_items else "Waiting for sales..."
            
    except Exception as e:
        low_stock_text = f"System Monitoring Active (Error: {e})"
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
    
    try:
        query = '''
            SELECT p.name, p.base_price, p.current_stock, p.season_tag, 
                   COALESCE(SUM(t.quantity), 0) as total_sold
            FROM products p
            LEFT JOIN transactions t ON p.product_id = t.product_id AND t.txn_type = 'OUT'
            GROUP BY p.product_id
        '''
        df = pd.read_sql(query, conn)
        
        # Safe check for customers table
        customers = []
        try:
            cursor.execute("SELECT name, email FROM customers")
            customers = cursor.fetchall()
        except:
            pass
        
        conn.close()
        
        alerts = []
        current_month = datetime.now().strftime("%B")
        
        if not df.empty:
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
        else:
            return "No data available for analytics. Add products first!"
    except Exception as e:
        return f"Analytics Error: {e}"

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

    try:
        if c_email:
            # Added phone handling to match your schema logic
            c_phone = request.form.get('cust_phone', '')
            cursor.execute("INSERT IGNORE INTO customers (name, email, phone) VALUES (%s, %s, %s)", 
                           (c_name, c_email, c_phone))

        # --- Fetch product details to calculate bill total ---
        cursor.execute("SELECT name, base_price FROM products WHERE product_id = %s", (p_id,))
        product = cursor.fetchone()
        p_name = product['name'] if product else "Item"
        total_amount = float(product['base_price']) * qty if product else 0

        cursor.execute("UPDATE products SET current_stock = current_stock - %s WHERE product_id = %s", (qty, p_id))
        cursor.execute("INSERT INTO transactions (product_id, txn_type, quantity, txn_date) VALUES (%s, 'OUT', %s, NOW())", (p_id, qty))
        db.commit()

        # --- SEND PDF INVOICE ---
        if c_email:
            try:
                # 1. Create the PDF
                pdf = FPDF()
                pdf.add_page()
                
                # Title
                pdf.set_font("Arial", 'B', 16)
                pdf.cell(200, 10, txt="SMART INVENTORY - INVOICE", ln=True, align='C')
                pdf.ln(10)
                
                # Customer Info
                pdf.set_font("Arial", size=12)
                pdf.cell(200, 10, txt=f"Customer Name: {c_name}", ln=True)
                pdf.cell(200, 10, txt=f"Email: {c_email}", ln=True)
                pdf.ln(5)
                
                # Bill Details
                pdf.cell(200, 10, txt="--------------------------------------------------", ln=True)
                pdf.cell(200, 10, txt=f"Item: {p_name} (Qty: {qty})", ln=True)
                pdf.cell(200, 10, txt=f"Total Amount Paid: Rs. {total_amount}", ln=True)
                pdf.cell(200, 10, txt="--------------------------------------------------", ln=True)
                
                pdf.ln(10)
                pdf.cell(200, 10, txt="Thank you for shopping with us! You are now registered for exclusive discounts.", ln=True)
                
                # 2. Save to memory for Vercel
                pdf_bytes = pdf.output(dest='S').encode('latin-1')

                # 3. Create Email and Attach PDF
                msg = Message('Your Invoice from Smart Inventory', sender=app.config['MAIL_USERNAME'], recipients=[c_email])
                msg.body = f"Hi {c_name},\n\nThank you for your purchase! Please find your PDF invoice attached.\n\nBest Regards,\nSmart Inventory Team"
                
                msg.attach(filename="Invoice.pdf", content_type="application/pdf", data=pdf_bytes)
                
                mail.send(msg)
            except Exception as mail_err: 
                print(f"Mail failed to send: {mail_err}")

        cursor.close()
        db.close()
        return f"<h1>Success!</h1><p>Bill Generated and PDF Invoice Sent.</p><a href='/dashboard'>Back to Dashboard</a>"
    except Exception as e:
        return f"Billing Error: {e}. Make sure 'customers' table exists."
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

@app.route('/send-seasonal-discounts', methods=['POST'])
def send_seasonal_discounts():
    if 'user' not in session: return redirect(url_for('login_page'))
    
    # --- SEASON MAPPING ENGINE ---
    current_month = datetime.now().strftime("%B")
    if current_month in ['March', 'April', 'May']:
        current_season = 'Summer'
    elif current_month in ['June', 'July', 'August', 'September']:
        current_season = 'Monsoon'
    else:
        current_season = 'Winter'
    
    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    
    try:
        # 1. Fetch Seasonal Items
        cursor.execute("SELECT name, base_price FROM products WHERE season_tag = %s", (current_season,))
        seasonal_items = cursor.fetchall()
        
        # 2. Fetch "Dead Stock / Clearance" Items (Least Demand + High Stock)
        # We look for non-seasonal items with stock > 10, sort by lowest sales, then highest stock, limit to top 2.
        clearance_query = """
            SELECT p.name, p.base_price 
            FROM products p
            LEFT JOIN transactions t ON p.product_id = t.product_id AND t.txn_type = 'OUT'
            WHERE p.season_tag != %s AND p.current_stock > 10
            GROUP BY p.product_id, p.name, p.base_price, p.current_stock
            ORDER BY COALESCE(SUM(t.quantity), 0) ASC, p.current_stock DESC
            LIMIT 2
        """
        cursor.execute(clearance_query, (current_season,))
        clearance_items = cursor.fetchall()

        if not seasonal_items and not clearance_items:
            return f"<h1>No items fit the discount criteria right now!</h1><a href='/analytics'>Back</a>"

        cursor.execute("SELECT DISTINCT email FROM customers WHERE email IS NOT NULL AND email != ''")
        customers = cursor.fetchall()
        
        if not customers:
            return "<h1>No customers found!</h1><a href='/analytics'>Back</a>"

        # 3. Build the dynamic email
        email_body = f"Hello Valued Customer,\n\nCelebrate the month of {current_month} with our exclusive offers!\n\n"
        
        # Add Seasonal Section if items exist
        if seasonal_items:
            email_body += f"🌿 {current_season.upper()} COLLECTION (10% OFF):\n"
            for item in seasonal_items:
                orig = float(item['base_price'])
                disc = orig * 0.90  # 10% Discount
                email_body += f"⭐ {item['name']}: ₹{orig:.2f} --> ₹{disc:.2f}!\n"
            email_body += "\n"
            
        # Add Clearance Section if items exist
        if clearance_items:
            email_body += f"🔥 SPECIAL CLEARANCE OFFERS (15% OFF):\n"
            for item in clearance_items:
                orig = float(item['base_price'])
                disc = orig * 0.85  # 15% Discount for clearance
                email_body += f"⭐ {item['name']}: ₹{orig:.2f} --> ₹{disc:.2f}!\n"
            email_body += "\n"
            
        email_body += "Hurry up before stocks run out!\n\nBest Regards,\nThe Smart Inventory Team"

        # 4. Blast the Emails
        with mail.connect() as conn:
            for customer in customers:
                msg = Message(f"🎁 Exclusive {current_season} & Clearance Discounts Just For You!",
                              sender=app.config['MAIL_USERNAME'],
                              recipients=[customer['email']])
                msg.body = email_body
                conn.send(msg)
                
        cursor.close()
        db.close()
        return f"<h1>Success!</h1><p>Algorithmic Discounts sent to {len(customers)} customers.</p><a href='/analytics'>Back to Analytics</a>"

    except Exception as e:
        return f"Error sending discounts: {e}"
@app.route('/delete-customer/<email>')
def delete_customer(email):
    if 'user' not in session: 
        return redirect(url_for('login_page'))
    
    db = get_db_connection()
    cursor = db.cursor()
    
    try:
        # Delete the customer using the email caught from the URL
        cursor.execute("DELETE FROM customers WHERE email = %s", (email,))
        db.commit()
    except Exception as e:
        print(f"Error deleting customer: {e}")
    finally:
        cursor.close()
        db.close()
        
    return redirect(url_for('analytics'))
if __name__ == '__main__':
    app.run()
