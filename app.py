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
app.config['MAIL_USERNAME'] = 'smartinventorysystem3@gmail.com' 
app.config['MAIL_PASSWORD'] = 'hjrb tnfu mdzw jrer' 
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
                # --- SAFETY CHECK ADDED HERE ---
                user_email = user.get('email')
                if not user_email:
                    cursor.close()
                    db.close()
                    return "Error: No email address is registered for this username in the database. Please update the database."
                # -------------------------------

                otp = str(random.randint(1000, 9999))
                cursor.execute("UPDATE users SET otp = %s WHERE username = %s", (otp, username))
                db.commit()
                cursor.close()
                db.close()
                
                msg = Message('Your OTP', sender=app.config['MAIL_USERNAME'], recipients=[user_email])
                msg.body = f"Your OTP for Smart Inventory is: {otp}"
                mail.send(msg)
                
                return render_template('verify_otp.html', username=username)
            
            # If user is not found
            cursor.close()
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
        cursor.execute("SELECT name, current_stock, season_tag, base_price FROM products")
        all_prods = cursor.fetchall()
        
        # --- NEW LOGIC: Separate Stock Alerts from Marketing Offers ---
        stock_alerts = []
        marketing_offers = []
        
        for p in all_prods:
            # RULE 1: Unchanged Low Stock Alerts (Put in stock_alerts list)
            if p['current_stock'] < 10:
                stock_alerts.append(f"{p['name']} ({p['current_stock']} left)")
            
            # RULE 2: Seasonal Discount (Put in marketing_offers list)
            if p['season_tag'] == current_season:
                if p['current_stock'] > 20:
                    orig_price = float(p['base_price'])
                    disc_price = orig_price * 0.90 # 10% off
                    marketing_offers.append(f"🎁 {current_season.upper()} OFFER: 10% OFF {p['name']}! Now ₹{disc_price:.2f}")
                else:
                    marketing_offers.append(f"📈 High Demand: {p['name']} is selling fast this {current_season}!")

        # RULE 3: Clearance Sale (Put in marketing_offers list)
        clearance_query = """
            SELECT p.name, p.base_price 
            FROM products p
            LEFT JOIN transactions t ON p.product_id = t.product_id AND t.txn_type = 'OUT'
            WHERE p.season_tag = 'All' AND p.current_stock > 15
            GROUP BY p.product_id, p.name, p.base_price, p.current_stock
            ORDER BY COALESCE(SUM(t.quantity), 0) ASC, p.current_stock DESC
            LIMIT 2
        """
        cursor.execute(clearance_query)
        clearance_items = cursor.fetchall()
        
        for c in clearance_items:
            orig = float(c['base_price'])
            disc = orig * 0.85 # 15% off
            marketing_offers.append(f"🔥 EVERYDAY CLEARANCE: 15% OFF on {c['name']}! Now ₹{disc:.2f}")

        # --- COMBINE THEM INTELLIGENTLY ---
        final_marquee_parts = []
        
        # Only add the "RE-STOCK ALERTS:" text if there are actual items low on stock
        if stock_alerts:
            final_marquee_parts.append("⚠️ RE-STOCK ALERTS: " + ", ".join(stock_alerts))
        else:
            final_marquee_parts.append("✅ Inventory Healthy")
            
        if marketing_offers:
            final_marquee_parts.append(" | ".join(marketing_offers))

        low_stock_text = " || ".join(final_marquee_parts)

        # Trending Items (Unchanged)
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
        # 1. Main DataFrame Query (Added p.product_id so we can track clearance items)
        query = '''
            SELECT p.product_id, p.name, p.base_price, p.current_stock, p.season_tag, 
                   COALESCE(SUM(t.quantity), 0) as total_sold
            FROM products p
            LEFT JOIN transactions t ON p.product_id = t.product_id AND t.txn_type = 'OUT'
            GROUP BY p.product_id
        '''
        df = pd.read_sql(query, conn)
        
        # 2. Safe check for customers table
        customers = []
        try:
            cursor.execute("SELECT name, email FROM customers")
            customers = cursor.fetchall()
        except:
            pass
            
        # 3. Find exact Clearance Items to match the Dashboard Marquee
        cursor.execute("""
            SELECT p.product_id FROM products p
            LEFT JOIN transactions t ON p.product_id = t.product_id AND t.txn_type = 'OUT'
            WHERE p.season_tag = 'All' AND p.current_stock > 15
            GROUP BY p.product_id, p.current_stock
            ORDER BY COALESCE(SUM(t.quantity), 0) ASC, p.current_stock DESC LIMIT 2
        """)
        clearance_rows = cursor.fetchall()
        clearance_ids = [row['product_id'] for row in clearance_rows]
        
        conn.close()
        
        alerts = []
        
        # --- SEASON MAPPING ENGINE ---
        current_month = datetime.now().strftime("%B")
        if current_month in ['March', 'April', 'May']:
            current_season = 'Summer'
        elif current_month in ['June', 'July', 'August', 'September']:
            current_season = 'Monsoon'
        else:
            current_season = 'Winter'
        
        if not df.empty:
            # Prepare lists to add to our Pandas DataFrame
            suggested_prices = []
            statuses = []
            badges = []
            
            for index, row in df.iterrows():
                # --- UPDATE EXISTING ALERTS ---
                if row['season_tag'] == current_season and row['current_stock'] < 5:
                    alerts.append(f"CRITICAL: {row['name']} is seasonal ({current_season}) and stock is LOW!")
                
                if row['total_sold'] > 10:
                    alerts.append(f"OPPORTUNITY: {row['name']} is in high demand.")

                # --- NEW DYNAMIC PRICING ENGINE LOGIC ---
                base = float(row['base_price'])
                
                # Rule 1: Clearance Sale (15% OFF)
                if row['product_id'] in clearance_ids:
                    suggested_prices.append(base * 0.85)
                    statuses.append("Clearance 15% OFF ⬇")
                    badges.append("danger")
                
                # Rule 2: Seasonal Discount (10% OFF if Stock > 20)
                elif row['season_tag'] == current_season and row['current_stock'] > 20:
                    suggested_prices.append(base * 0.90)
                    statuses.append(f"{current_season} 10% OFF ⬇")
                    badges.append("warning")
                    
                # Rule 3: High Demand (Your original logic: increase by 10%)
                elif row['total_sold'] > 10:
                    suggested_prices.append(base * 1.10)
                    statuses.append("Increase Price ⬆")
                    badges.append("success")
                    
                # Rule 4: Stable Default
                else:
                    suggested_prices.append(base)
                    statuses.append("Stable")
                    badges.append("secondary")

            # Attach our calculated logic directly into the Pandas DataFrame
            df['suggested_price'] = suggested_prices
            df['status'] = statuses
            df['badge_color'] = badges

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
            c_phone = request.form.get('cust_phone', '')
            cursor.execute("INSERT IGNORE INTO customers (name, email, phone) VALUES (%s, %s, %s)", 
                           (c_name, c_email, c_phone))

        # --- Fetch product details ---
        cursor.execute("SELECT name, base_price FROM products WHERE product_id = %s", (p_id,))
        product = cursor.fetchone()
        p_name = product['name'] if product else "Item"
        base_price = float(product['base_price']) if product else 0.0
        total_amount = base_price * qty

        cursor.execute("UPDATE products SET current_stock = current_stock - %s WHERE product_id = %s", (qty, p_id))
        cursor.execute("INSERT INTO transactions (product_id, txn_type, quantity, txn_date) VALUES (%s, 'OUT', %s, NOW())", (p_id, qty))
        db.commit()

        # --- GENERATE ENTERPRISE PDF INVOICE ---
        if c_email:
            try:
                # 1. Setup Data for Invoice
                now = datetime.now()
                invoice_date = now.strftime("%B %d, %Y")
                invoice_no = now.strftime("INV-%Y%m%d-%H%M") # E.g., INV-20240428-1430
                
                pdf = FPDF()
                pdf.add_page()
                
                # --- HEADER SECTION ---
                # Left Side: Company Name, Right Side: "INVOICE"
                pdf.set_font("Arial", 'B', 20)
                pdf.set_text_color(0, 51, 102) # Dark corporate blue
                pdf.cell(100, 10, txt="SMART INVENTORY", ln=0, align='L')
                
                pdf.set_font("Arial", 'B', 14)
                pdf.set_text_color(0, 0, 0)
                pdf.cell(90, 10, txt="INVOICE", ln=1, align='R')
                
                # Left Side: Address/Contact, Right Side: Date & Inv No.
                pdf.set_font("Arial", '', 10)
                pdf.set_text_color(100, 100, 100) # Gray color for meta-text
                pdf.cell(100, 6, txt="123 Tech Park, Mysuru, Karnataka", ln=0, align='L')
                pdf.cell(90, 6, txt=f"Invoice No: {invoice_no}", ln=1, align='R')
                
                pdf.cell(100, 6, txt="support@smartinventory.com", ln=0, align='L')
                pdf.cell(90, 6, txt=f"Date: {invoice_date}", ln=1, align='R')
                pdf.ln(8)
                
                # Divider Line
                pdf.set_draw_color(200, 200, 200)
                pdf.line(10, pdf.get_y(), 200, pdf.get_y())
                pdf.ln(8)
                
                # --- BILL TO SECTION ---
                pdf.set_font("Arial", 'B', 11)
                pdf.set_text_color(0, 0, 0)
                pdf.cell(100, 6, txt="BILL TO:", ln=1)
                
                pdf.set_font("Arial", '', 11)
                pdf.cell(100, 6, txt=c_name, ln=1)
                pdf.cell(100, 6, txt=c_email, ln=1)
                if c_phone:
                    pdf.cell(100, 6, txt=c_phone, ln=1)
                pdf.ln(10)
                
                # --- ITEM TABLE HEADER ---
                pdf.set_font("Arial", 'B', 11)
                pdf.set_fill_color(230, 230, 230) # Light gray background for table header
                pdf.cell(90, 10, txt=" Description", border=1, ln=0, align='L', fill=True)
                pdf.cell(30, 10, txt=" Qty", border=1, ln=0, align='C', fill=True)
                pdf.cell(35, 10, txt=" Unit Price", border=1, ln=0, align='R', fill=True)
                pdf.cell(35, 10, txt=" Total", border=1, ln=1, align='R', fill=True)
                
                # --- ITEM TABLE ROW ---
                pdf.set_font("Arial", '', 11)
                pdf.cell(90, 10, txt=f" {p_name}", border=1, ln=0, align='L')
                pdf.cell(30, 10, txt=f" {qty}", border=1, ln=0, align='C')
                pdf.cell(35, 10, txt=f" Rs. {base_price:.2f}", border=1, ln=0, align='R')
                pdf.cell(35, 10, txt=f" Rs. {total_amount:.2f}", border=1, ln=1, align='R')
                pdf.ln(10)
                
                # --- TOTALS SECTION ---
                pdf.set_font("Arial", 'B', 12)
                pdf.cell(155, 10, txt="Grand Total: ", ln=0, align='R')
                pdf.set_text_color(0, 128, 0) # Green for final amount
                pdf.cell(35, 10, txt=f"Rs. {total_amount:.2f}", ln=1, align='R')
                
                # --- FOOTER SECTION ---
                pdf.ln(20)
                pdf.set_draw_color(200, 200, 200)
                pdf.line(10, pdf.get_y(), 200, pdf.get_y()) # Bottom Divider
                pdf.ln(5)
                
                pdf.set_font("Arial", 'I', 10)
                pdf.set_text_color(120, 120, 120)
                pdf.cell(190, 6, txt="Thank you for your business! You are now registered for exclusive discounts.", ln=1, align='C')
                
                # 2. Save to memory
# 2. Save to Vercel's temporary /tmp folder
                pdf_path = f"/tmp/{invoice_no}.pdf"
                pdf.output(pdf_path)

                # 3. Create Email and Attach PDF
                msg = Message(f'Invoice {invoice_no} from Smart Inventory', sender=app.config['MAIL_USERNAME'], recipients=[c_email])
                msg.body = f"Hi {c_name},\n\nThank you for your purchase!\n\nPlease find your official PDF invoice attached to this email.\n\nBest Regards,\nSmart Inventory Team"
                
                # Open the file from /tmp and attach it to the email
                with open(pdf_path, "rb") as fp:
                    msg.attach(filename=f"{invoice_no}.pdf", content_type="application/pdf", data=fp.read())
                
                mail.send(msg)
            except Exception as mail_err: 
                print(f"Mail failed to send: {mail_err}")

        cursor.close()
        db.close()
        return f"<h1>Success!</h1><p>Bill Generated and Professional PDF Invoice Sent.</p><a href='/dashboard'>Back to Dashboard</a>"
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
        # 1. Fetch Seasonal Items (MUST have stock > 20 to be discounted)
        cursor.execute("SELECT name, base_price FROM products WHERE season_tag = %s AND current_stock > 20", (current_season,))
        seasonal_items = cursor.fetchall()
        
        # 2. Fetch Clearance Items (Strictly 'All' category, stock > 15, lowest sales)
        clearance_query = """
            SELECT p.name, p.base_price 
            FROM products p
            LEFT JOIN transactions t ON p.product_id = t.product_id AND t.txn_type = 'OUT'
            WHERE p.season_tag = 'All' AND p.current_stock > 15
            GROUP BY p.product_id, p.name, p.base_price, p.current_stock
            ORDER BY COALESCE(SUM(t.quantity), 0) ASC, p.current_stock DESC
            LIMIT 2
        """
        cursor.execute(clearance_query)
        clearance_items = cursor.fetchall()

        if not seasonal_items and not clearance_items:
            return f"<h1>Inventory Optimized! No items currently meet the criteria for a discount.</h1><a href='/analytics'>Back</a>"

        cursor.execute("SELECT DISTINCT email FROM customers WHERE email IS NOT NULL AND email != ''")
        customers = cursor.fetchall()
        
        if not customers:
            return "<h1>No customers found!</h1><a href='/analytics'>Back</a>"

        # 3. Build the dynamic email
        email_body = f"Hello Valued Customer,\n\nDon't miss our exclusive deals this {current_month}!\n\n"
        
        if seasonal_items:
            email_body += f"🌿 {current_season.upper()} SPECIALS (10% OFF):\n"
            for item in seasonal_items:
                orig = float(item['base_price'])
                disc = orig * 0.90 
                email_body += f"⭐ {item['name']}: ₹{orig:.2f} --> ₹{disc:.2f}!\n"
            email_body += "\n"
            
        if clearance_items:
            email_body += f"🔥 EVERYDAY CLEARANCE DEALS (15% OFF):\n"
            for item in clearance_items:
                orig = float(item['base_price'])
                disc = orig * 0.85 
                email_body += f"⭐ {item['name']}: ₹{orig:.2f} --> ₹{disc:.2f}!\n"
            email_body += "\n"
            
        email_body += "Hurry up before stocks run out!\n\nBest Regards,\nThe Smart Inventory Team"

        with mail.connect() as conn:
            for customer in customers:
                msg = Message(f"🎁 Exclusive {current_month} Discounts Just For You!",
                              sender=app.config['MAIL_USERNAME'],
                              recipients=[customer['email']])
                msg.body = email_body
                conn.send(msg)
                
        cursor.close()
        db.close()
        return f"<h1>Success!</h1><p>Smart Discounts sent to {len(customers)} customers.</p><a href='/analytics'>Back to Analytics</a>"

    except Exception as e:
        return f"Error sending discounts: {e}"
@app.route('/delete-customer/<email>')
def delete_customer(email):
    # Security check to make sure admin is logged in
    if 'user' not in session: 
        return redirect(url_for('login_page'))
    
    db = get_db_connection()
    cursor = db.cursor()
    
    try:
        # Delete the customer from the database using their email
        cursor.execute("DELETE FROM customers WHERE email = %s", (email,))
        db.commit()
    except Exception as e:
        print(f"Error deleting customer: {e}")
    finally:
        cursor.close()
        db.close()
        
    # Redirect back to the page you were just on (e.g., the CRM/Customers page)
    return redirect(request.referrer or url_for('dashboard'))
