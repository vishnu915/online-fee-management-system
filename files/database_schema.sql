-- Create Database
CREATE DATABASE IF NOT EXISTS ad;
USE ad;

-- Admin Table
CREATE TABLE admin (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL
);

-- Student Table
CREATE TABLE student (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    admission_no VARCHAR(100) NOT NULL UNIQUE,
    year INT NOT NULL,
    quota VARCHAR(50),
    address TEXT,
    academic_year VARCHAR(20),
    `group` VARCHAR(50)
);

-- Fee Table
CREATE TABLE fee (
    id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    tuition_fee DECIMAL(10,2) DEFAULT 0,
    practical_fee DECIMAL(10,2) DEFAULT 0,
    university_fee DECIMAL(10,2) DEFAULT 0,
    bus_fee DECIMAL(10,2) DEFAULT 0,
    stationary_fee DECIMAL(10,2) DEFAULT 0,
    internship_fee DECIMAL(10,2) DEFAULT 0,
    viva_fee DECIMAL(10,2) DEFAULT 0,
    
    tuition_discount DECIMAL(10,2) DEFAULT 0,
    practical_discount DECIMAL(10,2) DEFAULT 0,
    university_discount DECIMAL(10,2) DEFAULT 0,
    bus_discount DECIMAL(10,2) DEFAULT 0,
    stationary_discount DECIMAL(10,2) DEFAULT 0,
    internship_discount DECIMAL(10,2) DEFAULT 0,
    viva_discount DECIMAL(10,2) DEFAULT 0,

    is_locked BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (student_id) REFERENCES student(id) ON DELETE CASCADE
);

-- Payment Table
CREATE TABLE payment (
    id INT AUTO_INCREMENT PRIMARY KEY,
    fee_id INT NOT NULL,
    admission_no VARCHAR(100),
    student_name VARCHAR(255),
    bill_no VARCHAR(100),
    fee_type VARCHAR(50),
    paid_amount DECIMAL(10,2) NOT NULL,
    payment_date DATE NOT NULL,
    admin_name VARCHAR(100),
    FOREIGN KEY (fee_id) REFERENCES fee(id) ON DELETE CASCADE
);
-- Sample Admin (password: admin123)
INSERT INTO admin (username, password_hash)
VALUES ('admin', 'admin123');
-- Note: Replace with hashed password for production
ALTER TABLE student MODIFY year VARCHAR(20);
