@echo off
:: Go to your project folder
cd /d C:\Users\ADMIN\Documents\files

:: OPTIONAL - Activate virtual environment if used
:: call venv\Scripts\activate

:: Start Flask server
python app.py

:: Keep window open (optional)
pause
