from flask import Flask, render_template, request, redirect,jsonify, url_for, flash, send_file, make_response
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import mysql.connector
from config import DB_CONFIG, SECRET_KEY
from fpdf import FPDF
from datetime import datetime
from io import BytesIO
import os
from waitress import serve

app = Flask(__name__)
app.secret_key = SECRET_KEY
login_manager = LoginManager(app)
login_manager.login_view = 'login'

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

class Admin(UserMixin):
    pass

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM admin WHERE id=%s", (user_id,))
    user = cursor.fetchone()
    db.close()
    if user:
        admin = Admin()
        admin.id = user['id']
        admin.username = user['username']
        return admin
    return None

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT * FROM admin WHERE username=%s", (username,))
        user = cursor.fetchone()
        db.close()
        if user and user['password_hash'] == password:
            admin = Admin()
            admin.id = user['id']
            admin.username = user['username']
            login_user(admin)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))
@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    cursor = db.cursor(dictionary=True)

    try:
        # Total students
        cursor.execute("SELECT COUNT(*) AS total_students FROM student")
        total_students = cursor.fetchone()['total_students']

        # Total expected fee before discount
        cursor.execute("""
            SELECT SUM(
                tuition_fee + practical_fee + university_fee +
                bus_fee + stationary_fee + internship_fee + viva_fee
            ) AS total_expected
            FROM fee
        """)
        total_expected = cursor.fetchone()['total_expected'] or 0

        # Total discount given
        cursor.execute("""
            SELECT SUM(
                tuition_discount + practical_discount + university_discount +
                bus_discount + stationary_discount + internship_discount + viva_discount
            ) AS total_discount
            FROM fee
        """)
        total_discount = cursor.fetchone()['total_discount'] or 0

        # Total fee payable after discount (net amount)
        net_payable = total_expected - total_discount

        # Total fee collected (sum of all payments)
        cursor.execute("SELECT SUM(paid_amount) AS total_collected FROM payment")
        total_collected = cursor.fetchone()['total_collected'] or 0

        # Total balance remaining (net payable - collected)
        total_balance = max(net_payable - total_collected, 0)  # Ensure balance doesn't go negative

        # Get recent payments (last 5)
        cursor.execute("""
            SELECT p.*, s.name as student_name 
            FROM payment p
            JOIN student s ON s.admission_no = p.admission_no
            ORDER BY p.payment_date DESC LIMIT 5
        """)
        recent_payments = cursor.fetchall()

        # Get students with outstanding balance
        cursor.execute("""
            SELECT s.id, s.name, s.admission_no,
                   (SUM(f.tuition_fee + f.practical_fee + f.university_fee + 
                        f.bus_fee + f.stationary_fee + f.internship_fee + f.viva_fee) -
                    SUM(f.tuition_discount + f.practical_discount + f.university_discount + 
                        f.bus_discount + f.stationary_discount + f.internship_discount + f.viva_discount) -
                    COALESCE(SUM(p.paid_amount), 0)) AS outstanding_balance
            FROM student s
            JOIN fee f ON f.student_id = s.id
            LEFT JOIN payment p ON p.fee_id = f.id
            GROUP BY s.id, s.name, s.admission_no
            HAVING outstanding_balance > 0
            ORDER BY outstanding_balance DESC
            LIMIT 5
        """)
        outstanding_students = cursor.fetchall()

    except Exception as e:
        flash(f"Error fetching dashboard data: {str(e)}", "danger")
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

    return render_template('dashboard.html',
                         total_students=total_students,
                         total_expected=total_expected,
                         total_discount=total_discount,
                         total_collected=total_collected,
                         total_balance=total_balance,
                         recent_payments=recent_payments,
                         outstanding_students=outstanding_students)
@app.route('/add_student', methods=['GET', 'POST'])
@login_required
def add_student():
    if request.method == 'POST':
        admission_no = request.form['admission_no']
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT id FROM student WHERE admission_no = %s", (admission_no,))
        existing = cursor.fetchone()

        if existing:
            flash(f"Admission number '{admission_no}' already exists!", "error")
            cursor.close()
            db.close()
            return redirect(url_for('add_student'))

        name = request.form['name']
        year = request.form['year']
        quota = request.form['quota']
        address = request.form['address']
        academic_year = request.form['academic_year']
        group = request.form['group']

        cursor.execute("""
            INSERT INTO student (name, admission_no, year, quota, address, academic_year, `group`)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (name, admission_no, year, quota, address, academic_year, group))
        db.commit()

        cursor.execute("SELECT id FROM student WHERE admission_no = %s", (admission_no,))
        new_student = cursor.fetchone()
        student_id = new_student['id'] if new_student else None

        cursor.close()
        db.close()

        if student_id:
            flash('Student added successfully!', 'success')
            return redirect(url_for('manual_fee_entry', student_id=student_id))
        else:
            flash("Error: Could not fetch new student ID.", "danger")
            return redirect(url_for('add_student'))

    return render_template('add_student.html')
@app.route("/fee/manual/<int:student_id>", methods=["GET", "POST"])
@login_required
def manual_fee_entry(student_id):
    db = get_db()
    cursor = db.cursor(dictionary=True)

    # Get student info
    cursor.execute("SELECT * FROM student WHERE id = %s", (student_id,))
    student = cursor.fetchone()

    # Get or create fee record
    cursor.execute("SELECT * FROM fee WHERE student_id = %s", (student_id,))
    fee = cursor.fetchone()

    if request.method == "POST":
        action = request.form.get("action")

        # Collect form inputs
        values = {
            "tuition_fee": request.form.get("tuition_fee", 0),
            "practical_fee": request.form.get("practical_fee", 0),
            "university_fee": request.form.get("university_fee", 0),
            "bus_fee": request.form.get("bus_fee", 0),
            "stationary_fee": request.form.get("stationary_fee", 0),
            "internship_fee": request.form.get("internship_fee", 0),
            "viva_fee": request.form.get("viva_fee", 0),
            "is_locked": 1 if action == "lock" else 0
        }

        if fee:
            # Update existing
            cursor.execute("""
                UPDATE fee SET tuition_fee=%s, practical_fee=%s, university_fee=%s,
                bus_fee=%s, stationary_fee=%s, internship_fee=%s, viva_fee=%s, is_locked=%s
                WHERE student_id = %s
            """, (*values.values(), student_id))
        else:
            # Insert new
            cursor.execute("""
                INSERT INTO fee (student_id, tuition_fee, practical_fee, university_fee,
                bus_fee, stationary_fee, internship_fee, viva_fee, is_locked)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (student_id, *values.values()))

        db.commit()
        flash("Fee details saved successfully.", "success")
        return redirect(url_for("manual_fee_entry", student_id=student_id))

    return render_template("manual_fee_entry.html", student=student, fee=fee)




@app.route('/fee_payment', methods=['GET', 'POST'])
@login_required
def fee_payment():
    student = None
    fee = None
    payments = []

    if request.method == 'POST':
        search = request.form.get('search', '').strip()

        # Check if this is a delete specific fee-type payment request
        if 'delete_fee_type' in request.form and 'fee_id' in request.form:
            fee_type = request.form['delete_fee_type']
            fee_id = int(request.form['fee_id'])

            db = get_db()
            cursor = db.cursor()
            try:
                cursor.execute("DELETE FROM payment WHERE fee_id = %s AND fee_type = %s", (fee_id, fee_type))
                db.commit()
            finally:
                cursor.close()
                db.close()
            return redirect(url_for('fee_payment'))

        # Check if this is a delete entire student request
        if 'delete_student_id' in request.form:
            student_id = int(request.form['delete_student_id'])

            db = get_db()
            cursor = db.cursor()
            try:
                # Delete payments
                cursor.execute("DELETE FROM payment WHERE fee_id IN (SELECT id FROM fee WHERE student_id = %s)", (student_id,))
                
                # Delete fee record
                cursor.execute("DELETE FROM fee WHERE student_id = %s", (student_id,))
                
                # Delete student
                cursor.execute("DELETE FROM student WHERE id = %s", (student_id,))
                
                db.commit()
            finally:
                cursor.close()
                db.close()

            flash("Student and all related fee/payment records deleted.", "success")
            return redirect(url_for('fee_payment'))

        # Normal student search
        db = get_db()
        cursor = db.cursor(dictionary=True, buffered=True)
        try:
            cursor.execute("""
                SELECT * FROM student 
                WHERE name LIKE %s OR admission_no LIKE %s
            """, (f"%{search}%", f"%{search}%"))  
            student = cursor.fetchone()

            if student:
                cursor.execute("SELECT * FROM fee WHERE student_id=%s", (student['id'],))
                fee = cursor.fetchone()

                if fee:
                    cursor.execute("""
                        SELECT * FROM payment 
                        WHERE fee_id=%s 
                        ORDER BY payment_date DESC
                    """, (fee['id'],))
                    payments = cursor.fetchall()
        finally:
            cursor.close()
            db.close()

    return render_template('fee_payment.html', student=student, fee=fee, payments=payments)


@app.route('/make_payment/<int:fee_id>/<fee_type>', methods=['GET', 'POST'])
@login_required
def make_payment(fee_id, fee_type):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM fee WHERE id=%s", (fee_id,))
    fee = cursor.fetchone()
    cursor.execute("SELECT * FROM student WHERE id=%s", (fee['student_id'],))
    student = cursor.fetchone()
    cursor.execute("SELECT SUM(paid_amount) as total_paid FROM payment WHERE fee_id=%s AND fee_type=%s",
                 (fee_id, fee_type))
    paid = cursor.fetchone()['total_paid'] or 0.0
    fixed_amount = float(fee[fee_type + '_fee']) if fee_type+'_fee' in fee else 0.0
    discount = float(fee[fee_type + '_discount']) if fee_type+'_discount' in fee else 0.0
    net_amount = fixed_amount - discount
    balance = net_amount - float(paid)

    if request.method == 'POST':
        admission_no = student['admission_no']
        student_name = student['name']
        bill_no = request.form['bill_no']
        discount_entered = float(request.form.get('discount', discount))
        paid_amount = float(request.form['paid_amount'])
        payment_date = request.form['payment_date']
        cursor.execute(f"UPDATE fee SET {fee_type}_discount=%s WHERE id=%s", (discount_entered, fee_id))
        db.commit()
        net_amount = fixed_amount - discount_entered
        balance = net_amount - float(paid)
        if paid_amount > balance:
            flash('Paid amount cannot exceed remaining balance.', 'danger')
            db.close()
            return render_template('make_payment.html', student=student, fee=fee, fee_type=fee_type, discount=discount_entered, balance=balance, paid_amount=paid_amount)

        cursor.execute("""
            INSERT INTO payment (fee_id, admission_no, student_name, bill_no, fee_type, paid_amount, payment_date, admin_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (fee_id, admission_no, student_name, bill_no, fee_type, paid_amount, payment_date, current_user.username))
        db.commit()
        flash('Payment added!', 'success')
        db.close()
        return redirect(url_for('fee_payment'))
    db.close()
    return render_template('make_payment.html', student=student, fee=fee, fee_type=fee_type, discount=discount, balance=balance)

@app.route('/payment_history', methods=['GET', 'POST'])
@login_required
def payment_history():
    db = get_db()
    cursor = db.cursor(dictionary=True)
    payments = []
    search = ''

    if request.method == 'POST' and 'search' in request.form:
        search = request.form.get('search', '').strip()

    query = """
        SELECT p.*, 
               s.name AS student_name, 
               s.admission_no, 
               s.academic_year, 
               s.year, 
               s.group 
        FROM payment p 
        JOIN student s ON p.admission_no = s.admission_no
    """

    if search:
        query += " WHERE s.name LIKE %s OR s.admission_no LIKE %s"
        cursor.execute(query, (f"%{search}%", f"%{search}%"))
    else:
        cursor.execute(query)

    payments = cursor.fetchall()
    return render_template("payment_history.html", payments=payments)


# ========================
# ROUTE: Delete Payment
# ========================
@app.route('/delete_payment/<int:payment_id>', methods=['POST'])
@login_required
def delete_payment(payment_id):
    try:
        db = get_db()
        cursor = db.cursor()

        # Check existence
        cursor.execute("SELECT * FROM payment WHERE id = %s", (payment_id,))
        if not cursor.fetchone():
            return jsonify({"success": False, "error": "Payment not found"}), 404

        # Delete payment
        cursor.execute("DELETE FROM payment WHERE id = %s", (payment_id,))
        db.commit()
        return jsonify({"success": True}), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# Handle AJAX delete request

@app.route('/download_payment_pdf/<int:payment_id>')
@login_required
def download_payment_pdf(payment_id):
    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT p.*, s.name as student_name, s.admission_no, s.academic_year,
                f.tuition_fee, f.practical_fee, f.university_fee, f.bus_fee, 
                f.tuition_discount, f.practical_discount, f.university_discount, f.bus_discount
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
        balance = max(net_amount - paid_amount, 0.0)

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, "ADC Payment Receipt", 0, 1, 'C')
        pdf.ln(5)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, f"Student Name: {payment['student_name']}", 0, 1)
        pdf.cell(0, 10, f"Admission No: {payment['admission_no']}", 0, 1)
        pdf.ln(5)
        pdf.set_font("Arial", '', 12)
        pdf.cell(0, 10, f"Fee Type: {fee_type.title()}", 0, 1)
        pdf.cell(0, 10, f"Fixed Fee: {fixed_fee:.2f}", 0, 1)
        pdf.cell(0, 10, f"Discount: {discount:.2f}", 0, 1)
        pdf.cell(0, 10, f"Net Amount: {net_amount:.2f}", 0, 1)
        pdf.cell(0, 10, f"Paid Amount: {paid_amount:.2f}", 0, 1)
        pdf.cell(0, 10, f"Balance Remaining: {balance:.2f}", 0, 1)
        pdf.cell(0, 10, f"Bill Number: {payment['bill_no']}", 0, 1)
        pdf.cell(0, 10, f"Payment Date: {payment['payment_date'].strftime('%Y-%m-%d')}", 0, 1)
        pdf.ln(10)
        pdf.set_font("Arial", 'I', 10)
        pdf.cell(0, 10, "Thank you for your payment!", 0, 1, 'C')

        pdf_bytes = pdf.output(dest='S').encode('latin1')
        response = make_response(pdf_bytes)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=receipt_{payment["admission_no"]}_{payment_id}.pdf'
        return response
    except Exception as e:
        flash(f'Error generating PDF: {str(e)}', 'danger')
        return redirect(url_for('payment_history'))
    finally:
        db.close()
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
    year_group = request.args.get('year_group', '')

    db = get_db()
    cursor = db.cursor(dictionary=True)

    # Fetch student, fee, and payment info
    query = """
        SELECT
            s.id as student_id,
            s.name,
            s.admission_no,
            s.year,
            s.group AS `group`,
            s.academic_year,
            f.id as fee_id,
            f.tuition_fee, f.internship_fee, f.practical_fee,
            f.university_fee, f.stationary_fee, f.bus_fee, f.viva_fee,
            f.tuition_discount, f.internship_discount, f.practical_discount,
            f.university_discount, f.stationary_discount, f.bus_discount, f.viva_discount
        FROM student s
        JOIN fee f ON s.id = f.student_id
        WHERE 1=1
    """

    filters = []
    params = []

    if search_query:
        filters.append("(s.name LIKE %s OR s.admission_no LIKE %s)")
        params.extend([f"%{search_query}%", f"%{search_query}%"])
    
    if selected_year:
        filters.append("s.academic_year = %s")
        params.append(selected_year)
    
    if selected_group:
        filters.append("s.group = %s")
        params.append(selected_group)
    
    if year_group:
        filters.append("s.year = %s")
        params.append(int(year_group))

    if filters:
        query += " AND " + " AND ".join(filters)

    query += " ORDER BY s.academic_year DESC, s.group, s.year, s.name"

    cursor.execute(query, params)
    students = cursor.fetchall()

    # Prepare a mapping from fee_id + type to paid_amount
    cursor.execute("""
        SELECT fee_id, fee_type, SUM(paid_amount) AS paid
        FROM payment
        GROUP BY fee_id, fee_type
    """)
    payments = cursor.fetchall()
    paid_map = {(p['fee_id'], p['fee_type']): p['paid'] for p in payments}

    report_data = []
    yearly_totals = {}
    grand_totals = {'fee': 0.0, 'paid': 0.0, 'balance': 0.0}

    for s in students:
        fee_id = s['fee_id']

        def calc_balance(fee_type):
            fee_val = float(s.get(fee_type + '_fee') or 0)
            discount = float(s.get(fee_type + '_discount') or 0)
            paid = float(paid_map.get((fee_id, fee_type), 0))
            return max(fee_val - discount - paid, 0)

        # Calculate balances per fee type
        balances = {
            'tuition': calc_balance('tuition'),
            'internship': calc_balance('internship'),
            'practical': calc_balance('practical'),
            'university': calc_balance('university'),
            'stationary': calc_balance('stationary'),
            'bus': calc_balance('bus'),
            'viva': calc_balance('viva')
        }

        total_balance = sum(balances.values())
        total_paid = sum([float(paid_map.get((fee_id, t), 0)) for t in balances.keys()])
        total_fee = sum([float(s.get(t + '_fee') or 0) for t in balances.keys()])

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
            yearly_totals[year] = {'fee': 0.0, 'paid': 0.0, 'balance': 0.0}
        yearly_totals[year]['fee'] += total_fee
        yearly_totals[year]['paid'] += total_paid
        yearly_totals[year]['balance'] += total_balance

        grand_totals['fee'] += total_fee
        grand_totals['paid'] += total_paid
        grand_totals['balance'] += total_balance

    cursor.close()
    db.close()

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

if __name__ == "__main__":
    serve(app, host="127.0.0.1", port=5000)