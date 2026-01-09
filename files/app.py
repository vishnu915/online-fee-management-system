from flask import Flask, render_template, request, redirect, jsonify, url_for, flash, make_response
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import mysql.connector
from config import DB_CONFIG, SECRET_KEY
from fpdf import FPDF
from datetime import datetime
from io import BytesIO
import os
from waitress import serve
from werkzeug.security import generate_password_hash, check_password_hash
from ai_qa_engine import fetch_ai_data, generate_answer
from decimal import Decimal

app = Flask(__name__)
app.secret_key = SECRET_KEY
login_manager = LoginManager(app)
login_manager.login_view = 'login'

def get_db():
    """Establishes a new database connection."""
    return mysql.connector.connect(**DB_CONFIG)

class Admin(UserMixin):
    """User class for Flask-Login."""
    pass

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM admin WHERE id=%s", (user_id,))
        user = cursor.fetchone()
        if user:
            admin = Admin()
            admin.id = user['id']
            admin.username = user['username']
            return admin
        return None
    finally:
        cursor.close()
        db.close()

# -----------------------
# ADMIN SIGNUP ROUTE
# -----------------------
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect(url_for('signup'))

        db = get_db()
        cursor = db.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM admin WHERE username=%s OR email=%s", (username, email))
            existing = cursor.fetchone()
            if existing:
                flash("Username or email already exists.", "danger")
                return redirect(url_for('signup'))

            password_hash = generate_password_hash(password)
            cursor.execute("INSERT INTO admin (username, email, password_hash) VALUES (%s, %s, %s)",
                           (username, email, password_hash))
            db.commit()
            flash("Signup successful! Please login.", "success")
            return redirect(url_for('login'))
        finally:
            cursor.close()
            db.close()

    return render_template('signup.html')

# -----------------------
# LOGIN ROUTE
# -----------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        db = get_db()
        cursor = db.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM admin WHERE username=%s", (username,))
            user = cursor.fetchone()
            if user and check_password_hash(user['password_hash'], password):
                admin = Admin()
                admin.id = user['id']
                admin.username = user['username']
                login_user(admin)
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid credentials', 'danger')
        finally:
            cursor.close()
            db.close()
            
    return render_template('login.html')

# -----------------------
# LOGOUT
# -----------------------
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for('login'))

# -----------------------
# DASHBOARD
# -----------------------
@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    try:
        # -----------------------
        # TOTAL STUDENTS (ADMIN-WISE)
        # -----------------------
        cursor.execute("""
            SELECT COUNT(*) AS total_students
            FROM student
            WHERE admin_id = %s
        """, (current_user.id,))
        total_students = cursor.fetchone()['total_students']

        # -----------------------
        # TOTAL EXPECTED FEE (ADMIN-WISE)
        # -----------------------
        cursor.execute("""
            SELECT COALESCE(SUM(
                tuition_fee + practical_fee + university_fee +
                bus_fee + stationary_fee + internship_fee + viva_fee
            ), 0) AS total_expected
            FROM fee
            WHERE admin_id = %s
        """, (current_user.id,))
        total_expected = cursor.fetchone()['total_expected']

        # -----------------------
        # TOTAL DISCOUNT (ADMIN-WISE)
        # -----------------------
        cursor.execute("""
            SELECT COALESCE(SUM(
                tuition_discount + practical_discount + university_discount +
                bus_discount + stationary_discount +
                internship_discount + viva_discount
            ), 0) AS total_discount
            FROM fee
            WHERE admin_id = %s
        """, (current_user.id,))
        total_discount = cursor.fetchone()['total_discount']

        # -----------------------
        # NET PAYABLE
        # -----------------------
        net_payable = total_expected - total_discount

        # -----------------------
        # TOTAL COLLECTED (ADMIN-WISE)
        # -----------------------
        cursor.execute("""
            SELECT COALESCE(SUM(paid_amount), 0) AS total_collected
            FROM payment
            WHERE admin_id = %s
        """, (current_user.id,))
        total_collected = cursor.fetchone()['total_collected']

        # -----------------------
        # TOTAL BALANCE
        # -----------------------
        total_balance = max(net_payable - total_collected, 0)

        # -----------------------
        # RECENT PAYMENTS (LAST 5 – ADMIN-WISE)
        # -----------------------
        cursor.execute("""
            SELECT p.*, s.name AS student_name
            FROM payment p
            JOIN student s ON s.id = p.fee_id
            WHERE p.admin_id = %s
            ORDER BY p.payment_date DESC
            LIMIT 5
        """, (current_user.id,))
        recent_payments = cursor.fetchall()

        # -----------------------
        # OUTSTANDING STUDENTS (TOP 5 – ADMIN-WISE)
        # -----------------------
        cursor.execute("""
            WITH StudentPayable AS (
                SELECT
                    s.id,
                    s.name,
                    s.admission_no,
                    f.id AS fee_id,
                    (
                        f.tuition_fee + f.practical_fee + f.university_fee +
                        f.bus_fee + f.stationary_fee +
                        f.internship_fee + f.viva_fee
                    ) -
                    (
                        f.tuition_discount + f.practical_discount +
                        f.university_discount + f.bus_discount +
                        f.stationary_discount +
                        f.internship_discount + f.viva_discount
                    ) AS total_payable
                FROM student s
                JOIN fee f ON s.id = f.student_id
                WHERE s.admin_id = %s
            ),
            StudentPaid AS (
                SELECT
                    fee_id,
                    COALESCE(SUM(paid_amount), 0) AS total_paid
                FROM payment
                WHERE admin_id = %s
                GROUP BY fee_id
            )
            SELECT
                sp.name,
                sp.admission_no,
                (sp.total_payable - COALESCE(spd.total_paid, 0)) AS outstanding_balance
            FROM StudentPayable sp
            LEFT JOIN StudentPaid spd ON sp.fee_id = spd.fee_id
            WHERE (sp.total_payable - COALESCE(spd.total_paid, 0)) > 0
            ORDER BY outstanding_balance DESC
            LIMIT 5
        """, (current_user.id, current_user.id))
        outstanding_students = cursor.fetchall()

    except Exception as e:
        flash(f"Dashboard error: {str(e)}", "danger")
        total_students = 0
        total_expected = 0
        total_discount = 0
        total_collected = 0
        total_balance = 0
        recent_payments = []
        outstanding_students = []

    finally:
        cursor.close()
        db.close()

    return render_template(
        'dashboard.html',
        total_students=total_students,
        total_expected=total_expected,
        total_discount=total_discount,
        total_collected=total_collected,
        total_balance=total_balance,
        recent_payments=recent_payments,
        outstanding_students=outstanding_students
    )


# -----------------------
# ADD STUDENT
# -----------------------
@app.route('/add_student', methods=['GET', 'POST'])
@login_required
def add_student():
    if request.method == 'POST':
        admission_no = request.form['admission_no'].strip()

        db = get_db()
        cursor = db.cursor(dictionary=True)
        try:
            # 🔒 Check admission number ONLY for current admin
            cursor.execute("""
                SELECT id 
                FROM student 
                WHERE admission_no = %s AND admin_id = %s
            """, (admission_no, current_user.id))
            existing = cursor.fetchone()

            if existing:
                flash(f"Admission number '{admission_no}' already exists!", "danger")
                return redirect(url_for('add_student'))

            # Collect form data
            name = request.form['name']
            year = request.form['year']
            quota = request.form['quota']
            address = request.form['address']
            academic_year = request.form['academic_year']
            group = request.form['group']

            # ✅ INSERT student WITH admin_id
            cursor.execute("""
                INSERT INTO student (
                    name, admission_no, year, quota,
                    address, academic_year, `group`, admin_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                name, admission_no, year, quota,
                address, academic_year, group,
                current_user.id
            ))
            db.commit()

            new_student_id = cursor.lastrowid

            flash(
                'Student added successfully! Now, please set their fee structure.',
                'success'
            )
            return redirect(url_for('manual_fee_entry', student_id=new_student_id))

        finally:
            cursor.close()
            db.close()

    return render_template('add_student.html')

# -----------------------
# MANUAL FEE ENTRY
# -----------------------
@app.route("/fee/manual/<int:student_id>", methods=["GET", "POST"])
@login_required
def manual_fee_entry(student_id):
    db = get_db()
    cursor = db.cursor(dictionary=True)

    try:
        # 🔒 Fetch student ONLY for current admin
        cursor.execute("""
            SELECT *
            FROM student
            WHERE id = %s AND admin_id = %s
        """, (student_id, current_user.id))
        student = cursor.fetchone()

        if not student:
            flash("Student not found or unauthorized access.", "danger")
            return redirect(url_for('dashboard'))

        # 🔒 Fetch fee ONLY for this admin
        cursor.execute("""
            SELECT *
            FROM fee
            WHERE student_id = %s AND admin_id = %s
        """, (student_id, current_user.id))
        fee = cursor.fetchone()

        if request.method == "POST":

            # 🚫 Block editing if fee is locked
            if fee and fee.get('is_locked'):
                flash("Fee structure is locked and cannot be modified.", "danger")
                return redirect(url_for("manual_fee_entry", student_id=student_id))

            action = request.form.get("action")

            # Collect form inputs (default = 0)
            tuition_fee = float(request.form.get("tuition_fee") or 0)
            practical_fee = float(request.form.get("practical_fee") or 0)
            university_fee = float(request.form.get("university_fee") or 0)
            bus_fee = float(request.form.get("bus_fee") or 0)
            stationary_fee = float(request.form.get("stationary_fee") or 0)
            internship_fee = float(request.form.get("internship_fee") or 0)
            viva_fee = float(request.form.get("viva_fee") or 0)

            is_locked = 1 if action == "lock" else 0

            if fee:
                # ✅ Update existing fee
                cursor.execute("""
                    UPDATE fee
                    SET tuition_fee=%s,
                        practical_fee=%s,
                        university_fee=%s,
                        bus_fee=%s,
                        stationary_fee=%s,
                        internship_fee=%s,
                        viva_fee=%s,
                        is_locked=%s
                    WHERE student_id=%s AND admin_id=%s
                """, (
                    tuition_fee, practical_fee, university_fee,
                    bus_fee, stationary_fee, internship_fee,
                    viva_fee, is_locked,
                    student_id, current_user.id
                ))

            else:
                # ✅ Insert new fee WITH admin_id
                cursor.execute("""
                    INSERT INTO fee (
                        student_id,
                        tuition_fee, practical_fee, university_fee,
                        bus_fee, stationary_fee, internship_fee,
                        viva_fee, is_locked, admin_id
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    student_id,
                    tuition_fee, practical_fee, university_fee,
                    bus_fee, stationary_fee, internship_fee,
                    viva_fee, is_locked,
                    current_user.id
                ))

            db.commit()
            flash("Fee details saved successfully.", "success")
            return redirect(url_for("manual_fee_entry", student_id=student_id))

        return render_template("manual_fee_entry.html", student=student, fee=fee)

    finally:
        cursor.close()
        db.close()


# -----------------------
# FEE PAYMENT (Search & Delete Student)
@app.route('/fee_payment', methods=['GET', 'POST'])
@login_required
def fee_payment():
    student = None
    fee = None
    payments = []

    if request.method == 'POST':
        search = request.form.get('search', '').strip()

        # -----------------------
        # 🔴 DELETE ENTIRE STUDENT (ADMIN SAFE)
        # -----------------------
        if 'delete_student_id' in request.form:
            student_id = int(request.form['delete_student_id'])

            db = get_db()
            cursor = db.cursor()
            try:
                # 🔒 Verify ownership
                cursor.execute("""
                    SELECT id FROM student
                    WHERE id = %s AND admin_id = %s
                """, (student_id, current_user.id))

                if not cursor.fetchone():
                    flash("Unauthorized delete attempt.", "danger")
                    return redirect(url_for('fee_payment'))

                # Delete payments
                cursor.execute("""
                    DELETE FROM payment
                    WHERE fee_id IN (
                        SELECT id FROM fee
                        WHERE student_id = %s AND admin_id = %s
                    )
                """, (student_id, current_user.id))

                # Delete fee
                cursor.execute("""
                    DELETE FROM fee
                    WHERE student_id = %s AND admin_id = %s
                """, (student_id, current_user.id))

                # Delete student
                cursor.execute("""
                    DELETE FROM student
                    WHERE id = %s AND admin_id = %s
                """, (student_id, current_user.id))

                db.commit()
                flash("Student and all related records deleted.", "success")

            except Exception as e:
                db.rollback()
                flash(f"Error deleting student: {str(e)}", "danger")
            finally:
                cursor.close()
                db.close()

            return redirect(url_for('fee_payment'))

        # -----------------------
        # 🔍 SEARCH STUDENT (ADMIN-WISE)
        # -----------------------
        db = get_db()
        cursor = db.cursor(dictionary=True, buffered=True)
        try:
            cursor.execute("""
                SELECT *
                FROM student
                WHERE admin_id = %s
                AND (name LIKE %s OR admission_no LIKE %s)
            """, (
                current_user.id,
                f"%{search}%",
                f"%{search}%"
            ))
            student = cursor.fetchone()

            if not student:
                flash("No student found.", "danger")
                return redirect(url_for('fee_payment'))

            # Fetch fee (admin-wise)
            cursor.execute("""
                SELECT *
                FROM fee
                WHERE student_id = %s AND admin_id = %s
            """, (student['id'], current_user.id))
            fee = cursor.fetchone()

            if not fee:
                flash("Fee structure not found. Please create one.", "warning")
                return redirect(url_for('manual_fee_entry', student_id=student['id']))

            # Fetch payments (admin-wise)
            cursor.execute("""
                SELECT *
                FROM payment
                WHERE fee_id = %s AND admin_id = %s
                ORDER BY payment_date DESC
            """, (fee['id'], current_user.id))
            payments = cursor.fetchall()

        finally:
            cursor.close()
            db.close()

    return render_template(
        'fee_payment.html',
        student=student,
        fee=fee,
        payments=payments
    )

# -----------------------
# MAKE A PAYMENT

@app.route('/make_payment/<int:fee_id>/<fee_type>', methods=['GET', 'POST'])
@login_required
def make_payment(fee_id, fee_type):
    db = get_db()
    cursor = db.cursor(dictionary=True)

    try:
        # -----------------------
        # FETCH FEE (ADMIN-WISE)
        # -----------------------
        cursor.execute("""
            SELECT *
            FROM fee
            WHERE id = %s AND admin_id = %s
        """, (fee_id, current_user.id))
        fee = cursor.fetchone()

        if not fee:
            flash("Fee record not found or unauthorized access.", "danger")
            return redirect(url_for('fee_payment'))

        # -----------------------
        # FETCH STUDENT (ADMIN-WISE)
        # -----------------------
        cursor.execute("""
            SELECT *
            FROM student
            WHERE id = %s AND admin_id = %s
        """, (fee['student_id'], current_user.id))
        student = cursor.fetchone()

        if not student:
            flash("Student not found or unauthorized access.", "danger")
            return redirect(url_for('fee_payment'))

        # -----------------------
        # VALIDATE FEE TYPE
        # -----------------------
        fee_column = f"{fee_type}_fee"
        discount_column = f"{fee_type}_discount"

        if fee_column not in fee or discount_column not in fee:
            flash("Invalid fee type.", "danger")
            return redirect(url_for('fee_payment'))

        # -----------------------
        # TOTAL PAID (DECIMAL SAFE)
        # -----------------------
        cursor.execute("""
            SELECT COALESCE(SUM(paid_amount), 0) AS total_paid
            FROM payment
            WHERE fee_id = %s AND fee_type = %s AND admin_id = %s
        """, (fee_id, fee_type, current_user.id))

        paid = cursor.fetchone()['total_paid'] or Decimal('0.00')
        paid = float(paid)   # ✅ FIX: convert Decimal → float

        # -----------------------
        # AMOUNTS
        # -----------------------
        fixed_amount = float(fee.get(fee_column) or 0)
        discount = float(fee.get(discount_column) or 0)

        net_amount = fixed_amount - discount
        balance = max(net_amount - paid, 0)

        # -----------------------
        # POST: MAKE PAYMENT
        # -----------------------
        if request.method == 'POST':
            bill_no = request.form['bill_no'].strip()
            paid_amount = float(request.form['paid_amount'])
            discount_entered = float(request.form.get('discount', discount))
            payment_date = request.form['payment_date']

            # ❌ Invalid discount
            if discount_entered < 0:
                flash("Discount cannot be negative.", "danger")
                return redirect(request.url)

            # ❌ Invalid payment
            if paid_amount <= 0:
                flash("Paid amount must be greater than zero.", "danger")
                return redirect(request.url)

            # -----------------------
            # UPDATE DISCOUNT
            # -----------------------
            cursor.execute(f"""
                UPDATE fee
                SET {discount_column} = %s
                WHERE id = %s AND admin_id = %s
            """, (discount_entered, fee_id, current_user.id))
            db.commit()

            # -----------------------
            # RECALCULATE BALANCE
            # -----------------------
            net_amount = fixed_amount - discount_entered
            balance = max(net_amount - paid, 0)

            if paid_amount > balance:
                flash(
                    f"Paid amount (₹{paid_amount:,.2f}) "
                    f"cannot exceed remaining balance (₹{balance:,.2f}).",
                    "danger"
                )
                return redirect(request.url)

            # -----------------------
            # DUPLICATE BILL CHECK
            # -----------------------
            cursor.execute("""
                SELECT id FROM payment
                WHERE bill_no = %s AND admin_id = %s
            """, (bill_no, current_user.id))
            if cursor.fetchone():
                flash("Bill number already exists.", "danger")
                return redirect(request.url)

            # -----------------------
            # INSERT PAYMENT
            # -----------------------
            cursor.execute("""
                INSERT INTO payment (
                    fee_id,
                    admission_no,
                    student_name,
                    bill_no,
                    fee_type,
                    paid_amount,
                    payment_date,
                    admin_name,
                    admin_id
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                fee_id,
                student['admission_no'],
                student['name'],
                bill_no,
                fee_type,
                paid_amount,
                payment_date,
                current_user.username,
                current_user.id
            ))

            db.commit()
            flash("Payment added successfully!", "success")
            return redirect(url_for('fee_payment'))

        # -----------------------
        # GET: RENDER PAGE
        # -----------------------
        return render_template(
            'make_payment.html',
            student=student,
            fee=fee,
            fee_type=fee_type,
            discount=discount,
            balance=balance
        )

    finally:
        cursor.close()
        db.close()


# -----------------------
# PAYMENT HISTORY (All Payments)
@app.route('/payment_history', methods=['GET', 'POST'])
@login_required
def payment_history():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    payments = []
    search = ''

    try:
        if request.method == 'POST':
            search = request.form.get('search', '').strip()

        # -----------------------
        # 1. FETCH PAYMENTS + FEE DATA + STUDENT DATA
        # -----------------------
        # We join 'fee' to get the fee structure (amounts/discounts)
        # We join 'student' via 'fee' to get student details
        query = """
            SELECT 
                p.*,
                s.name AS student_name,
                s.admission_no,
                s.academic_year,
                s.year,
                s.group,
                -- Fetch Fee Structure columns to calculate balance
                f.tuition_fee, f.practical_fee, f.university_fee, f.bus_fee, 
                f.stationary_fee, f.internship_fee, f.viva_fee,
                f.tuition_discount, f.practical_discount, f.university_discount, 
                f.bus_discount, f.stationary_discount, f.internship_discount, f.viva_discount
            FROM payment p
            JOIN fee f ON p.fee_id = f.id
            JOIN student s ON f.student_id = s.id
            WHERE p.admin_id = %s
        """
        params = [current_user.id]

        # -----------------------
        # 2. APPLY SEARCH FILTER
        # -----------------------
        if search:
            query += """
                AND (
                    s.name LIKE %s OR 
                    s.admission_no LIKE %s OR 
                    p.bill_no LIKE %s
                )
            """
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

        query += " ORDER BY p.payment_date DESC"

        cursor.execute(query, tuple(params))
        payments = cursor.fetchall()

        # -----------------------
        # 3. CALCULATE TOTAL PAID MAP
        # -----------------------
        # To find the balance, we need the sum of ALL payments for a specific fee_id + fee_type
        cursor.execute("""
            SELECT fee_id, fee_type, SUM(paid_amount) as total_paid
            FROM payment
            WHERE admin_id = %s
            GROUP BY fee_id, fee_type
        """, (current_user.id,))
        
        # Create a dictionary for fast lookup: (fee_id, fee_type) -> total_paid
        paid_sums = cursor.fetchall()
        paid_map = {
            (row['fee_id'], row['fee_type']): float(row['total_paid']) 
            for row in paid_sums
        }

        # -----------------------
        # 4. CALCULATE REMAINING BALANCE PER ROW
        # -----------------------
        for row in payments:
            fee_type = row['fee_type'] # e.g., 'tuition'
            
            # Dynamically get the fee and discount based on the type
            # defaulting to 0.0 if None
            total_fee = float(row.get(f"{fee_type}_fee") or 0.0)
            total_discount = float(row.get(f"{fee_type}_discount") or 0.0)
            
            # Calculate Net Payable
            net_payable = total_fee - total_discount
            
            # Get total paid so far for this fee category
            total_paid_so_far = paid_map.get((row['fee_id'], fee_type), 0.0)
            
            # Current Outstanding Balance
            remaining_balance = max(net_payable - total_paid_so_far, 0.0)
            
            # Attach to the row object so HTML can use it
            row['remaining_balance'] = remaining_balance

        return render_template(
            "payment_history.html",
            payments=payments,
            search_query=search
        )

    except Exception as e:
        flash(f"Error loading history: {str(e)}", "danger")
        return render_template("payment_history.html", payments=[], search_query=search)

    finally:
        cursor.close()
        db.close()

# -----------------------
# DELETE PAYMENT (AJAX)
# -----------------------
@app.route('/delete_payment/<int:payment_id>', methods=['POST'])
@login_required
def delete_payment(payment_id):
    db = get_db()
    cursor = db.cursor()
    try:
        # Check existence
        cursor.execute("SELECT * FROM payment WHERE id = %s", (payment_id,))
        if not cursor.fetchone():
            return jsonify({"success": False, "error": "Payment not found"}), 404

        # Delete payment
        cursor.execute("DELETE FROM payment WHERE id = %s", (payment_id,))
        db.commit()
        return jsonify({"success": True}), 200

    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        db.close()

# -----------------------
# DOWNLOAD PDF RECEIPT
# -----------------------
@app.route('/download_payment_pdf/<int:payment_id>')
@login_required
def download_payment_pdf(payment_id):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        # *** CORRECTED QUERY (selects all fee/discount types) ***
        cursor.execute("""
            SELECT p.*, s.name as student_name, s.admission_no, s.academic_year,
                   f.tuition_fee, f.practical_fee, f.university_fee, f.bus_fee, 
                   f.stationary_fee, f.internship_fee, f.viva_fee,
                   f.tuition_discount, f.practical_discount, f.university_discount, f.bus_discount,
                   f.stationary_discount, f.internship_discount, f.viva_discount
            FROM payment p
            JOIN fee f ON f.id=p.fee_id
            JOIN student s ON s.id=f.student_id
            WHERE p.id=%s
        """, (payment_id,))
        payment = cursor.fetchone()
        
        if not payment:
            flash('Payment not found', 'danger')
            return redirect(url_for('payment_history'))

        fee_type = payment['fee_type']
        fee_field = fee_type + '_fee'
        discount_field = fee_type + '_discount'
        
        fixed_fee = float(payment[fee_field]) if fee_field in payment and payment[fee_field] else 0.0
        discount = float(payment[discount_field]) if discount_field in payment and payment[discount_field] else 0.0
        net_amount = fixed_fee - discount
        paid_amount = float(payment['paid_amount'])

        # Get total paid FOR THIS FEE TYPE up to this payment
        cursor.execute("""
            SELECT SUM(paid_amount) as total_paid
            FROM payment
            WHERE fee_id = %s AND fee_type = %s AND payment_date <= %s
        """, (payment['fee_id'], fee_type, payment['payment_date']))
        total_paid_so_far = cursor.fetchone()['total_paid'] or 0.0
        balance = max(net_amount - total_paid_so_far, 0.0)

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, "ADC Payment Receipt", 0, 1, 'C')
        pdf.ln(5)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(95, 8, f"Student Name: {payment['student_name']}", 0, 0)
        pdf.cell(95, 8, f"Bill Number: {payment['bill_no']}", 0, 1, 'R')
        pdf.cell(95, 8, f"Admission No: {payment['admission_no']}", 0, 0)
        pdf.cell(95, 8, f"Payment Date: {payment['payment_date'].strftime('%Y-%m-%d')}", 0, 1, 'R')
        pdf.cell(95, 8, f"Academic Year: {payment['academic_year']}", 0, 1)

        pdf.ln(10)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(100, 8, "Description", 1, 0, 'C')
        pdf.cell(90, 8, "Amount (INR)", 1, 1, 'C')
        
        pdf.set_font("Arial", '', 12)
        pdf.cell(100, 8, f"Fee Type: {fee_type.title()}", 1, 0)
        pdf.cell(90, 8, f"{paid_amount:.2f}", 1, 1, 'R')
        
        pdf.ln(5)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(100, 8, "Fee Summary for this Type", 0, 0)
        pdf.cell(90, 8, "", 0, 1) # dummy
        
        pdf.set_font("Arial", '', 12)
        pdf.cell(100, 8, "Total Fixed Fee:", 0, 0)
        pdf.cell(90, 8, f"{fixed_fee:.2f}", 0, 1, 'R')
        pdf.cell(100, 8, "Total Discount:", 0, 0)
        pdf.cell(90, 8, f"({discount:.2f})", 0, 1, 'R')
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(100, 8, "Net Amount Payable:", 0, 0)
        pdf.cell(90, 8, f"{net_amount:.2f}", 0, 1, 'R')
        pdf.set_font("Arial", '', 12)
        pdf.cell(100, 8, "Total Paid (to date):", 0, 0)
        pdf.cell(90, 8, f"{total_paid_so_far:.2f}", 0, 1, 'R')
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(100, 8, "Balance Remaining:", 0, 0)
        pdf.cell(90, 8, f"{balance:.2f}", 0, 1, 'R')

        pdf.ln(10)
        pdf.set_font("Arial", 'I', 10)
        pdf.cell(0, 10, "This is a computer-generated receipt.", 0, 1, 'C')
        pdf.cell(0, 10, f"Processed by: {payment['admin_name']}", 0, 1, 'R')

        pdf_bytes = pdf.output(dest='S').encode('latin1')
        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=receipt_{payment["admission_no"]}_{payment_id}.pdf'
        return response
    except Exception as e:
        flash(f'Error generating PDF: {str(e)}', 'danger')
        return redirect(url_for('payment_history'))
    finally:
        cursor.close()
        db.close()

# -----------------------
# REPORTING PAGE
# -----------------------
@app.route('/report')
@login_required
def report():
    group_data = {
        "2025-2026": ["B.Com", "B.Sc(CS)", "BCA", "B.Sc(Chemistry)"],
        "2024-2025": ["B.Com", "B.Sc(CS)", "BCA", "B.Sc(Chemistry)"],
        "2023-2024": ["B.Com", "B.Sc(CS)", "BCA", "B.Sc(Chemistry)"],
        "2022-2023": ["B.Com", "B.Sc(MSCS)"],
        "2021-2022": ["B.Com", "B.Sc(MPCS)", "B.Sc(MSCS)"],
        "2020-2021": ["B.Com", "B.Sc(MPCS)", "B.Sc(MSCS)"],
        "2019-2020": ["B.Com", "B.Sc(MPCS)", "B.Sc(MSCS)"],
    }

    search_query = request.args.get('search', '').strip()
    selected_year = request.args.get('year', '')
    selected_group = request.args.get('group', '')
    year_group = request.args.get('year_group', '')  # 1, 2, or 3

    db = get_db()
    cursor = db.cursor(dictionary=True)

    try:
        # -----------------------
        # STUDENT + FEE DATA (ADMIN-WISE)
        # -----------------------
        query = """
            SELECT
                s.id AS student_id,
                s.name,
                s.admission_no,
                s.year,
                s.`group`,
                s.academic_year,
                f.id AS fee_id,
                f.tuition_fee, f.internship_fee, f.practical_fee,
                f.university_fee, f.stationary_fee, f.bus_fee, f.viva_fee,
                f.tuition_discount, f.internship_discount, f.practical_discount,
                f.university_discount, f.stationary_discount, f.bus_discount, f.viva_discount
            FROM student s
            JOIN fee f ON s.id = f.student_id
            WHERE s.admin_id = %s
        """
        params = [current_user.id]

        if search_query:
            query += " AND (s.name LIKE %s OR s.admission_no LIKE %s)"
            params.extend([f"%{search_query}%", f"%{search_query}%"])

        if selected_year:
            query += " AND s.academic_year = %s"
            params.append(selected_year)

        if selected_group:
            query += " AND s.`group` = %s"
            params.append(selected_group)

        if year_group:
            query += " AND s.year = %s"
            params.append(int(year_group))

        query += " ORDER BY s.academic_year DESC, s.`group`, s.year, s.name"

        cursor.execute(query, tuple(params))
        students = cursor.fetchall()

        # -----------------------
        # PAYMENTS MAP (ADMIN-WISE)
        # -----------------------
        cursor.execute("""
            SELECT fee_id, fee_type, SUM(paid_amount) AS paid
            FROM payment
            WHERE admin_id = %s
            GROUP BY fee_id, fee_type
        """, (current_user.id,))
        payments = cursor.fetchall()

        paid_map = {
            (p['fee_id'], p['fee_type']): float(p['paid'])
            for p in payments
        }

        report_data = []
        yearly_totals = {}

        grand_totals = {
            'fee': 0.0,
            'paid': 0.0,
            'balance': 0.0,
            'tuition': 0.0,
            'internship': 0.0,
            'practical': 0.0,
            'university': 0.0,
            'stationary': 0.0,
            'bus': 0.0,
            'viva': 0.0
        }

        fee_types = [
            'tuition', 'internship', 'practical',
            'university', 'stationary', 'bus', 'viva'
        ]

        # -----------------------
        # BALANCE CALCULATOR
        # -----------------------
        def calc_balance(student, fee_type, fee_id):
            fee_val = float(student.get(fee_type + '_fee') or 0)
            discount = float(student.get(fee_type + '_discount') or 0)
            paid = float(paid_map.get((fee_id, fee_type), 0))
            return max(fee_val - discount - paid, 0)

        # -----------------------
        # BUILD REPORT
        # -----------------------
        for s in students:
            fee_id = s['fee_id']

            balances = {
                ft: calc_balance(s, ft, fee_id)
                for ft in fee_types
            }

            total_fee = sum(float(s.get(ft + '_fee') or 0) for ft in fee_types)
            total_paid = sum(float(paid_map.get((fee_id, ft), 0)) for ft in fee_types)
            total_balance = sum(balances.values())

            report_data.append({
                'name': s['name'],
                'admission_no': s['admission_no'],
                'year': s['year'],
                'group': s['group'],
                'academic_year': s['academic_year'],
                **balances,
                'total_fee': total_fee,
                'total_paid': total_paid,
                'balance': total_balance
            })

            year = s['academic_year']
            if year not in yearly_totals:
                yearly_totals[year] = {
                    'fee': 0.0,
                    'paid': 0.0,
                    'balance': 0.0
                }

            yearly_totals[year]['fee'] += total_fee
            yearly_totals[year]['paid'] += total_paid
            yearly_totals[year]['balance'] += total_balance

            grand_totals['fee'] += total_fee
            grand_totals['paid'] += total_paid
            grand_totals['balance'] += total_balance

            for ft in fee_types:
                grand_totals[ft] += balances[ft]

        return render_template(
            'report.html',
            report_data=report_data,
            group_data=group_data,
            yearly_totals=yearly_totals,
            grand_totals=grand_totals,
            search_query=search_query,
            selected_year=selected_year,
            selected_group=selected_group,
            year_group=year_group
        )

    finally:
        cursor.close()
        db.close()

@app.route("/ai-qa", methods=["POST"])
@login_required
def ai_qa():
    question = request.json.get("question", "")

    db = get_db()
    cursor = db.cursor(dictionary=True)

    try:
        data = fetch_ai_data(cursor)
        answer = generate_answer(question, data)
        return jsonify({"answer": answer})
    finally:
        cursor.close()
        db.close()

if __name__ == "__main__":
    print("Starting server on http://127.0.0.1:5000")
    serve(app, host="127.0.0.1", port=5000)