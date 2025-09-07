# ADC College Fee Structure Management System

## Setup

1. **Clone** this repo and enter folder:
   ```bash
   git clone <repo-url>
   cd adc_fee_management
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Setup MySQL Database**:
   - Create database and tables using `database_schema.sql`.
   - Insert your admin user:
     ```sql
     INSERT INTO admin (username, password_hash) VALUES ('admin', '<hash>');
     ```
     Use Python to hash password:
     ```python
     from werkzeug.security import generate_password_hash
     print(generate_password_hash('your_password'))
     ```

4. **Edit config.py** with your DB credentials.

5. **Run the server**:
   ```bash
   python app.py
   ```

6. **Open** [http://127.0.0.1:5000/login](http://127.0.0.1:5000/login)

---

## Features

- Responsive UI (orange theme)
- Secure admin login
- Manual fee entry & lock per student
- Fee payment tracking, balance, bill number
- PDF download for fee structure
- Search, reporting, and analytics
- Data validation to prevent duplicates

---

## 🎉 Ready to use!