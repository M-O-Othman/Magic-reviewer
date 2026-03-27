@echo off
echo Installing Magic Reviewer dependencies...
pip install flask flask-cors google-generativeai google-cloud-aiplatform google-cloud-bigquery python-dotenv
echo.
echo Done! You can now run the app with: python app.py
pause
