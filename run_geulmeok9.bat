@echo off
chcp 65001 > nul
echo GeulMeok9 - Running Web Novel Writing Tool
echo.
REM Create virtual environment if it doesn't exist
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
    echo Virtual environment created.
) else (
    echo Using existing virtual environment.
)

REM Activate virtual environment and install required packages
echo Activating virtual environment and installing required packages...
call venv\Scripts\activate
pip install -r requirements.txt

REM Create .env file if it doesn't exist
if not exist .env (
    echo .env file not found. Creating a new one...
    echo GOOGLE_API_KEY=your_api_key_here > .env
    echo .env file created. Please set your API key.
    notepad .env
)

REM Run the application
echo.
echo WARNING: This will make the application accessible from your network.
echo Make sure your firewall allows incoming connections on port 5000.
echo.
echo Launching GeulMeok9...
echo Access the application at:
echo - Local: http://127.0.0.1:5000
echo - Network: http://<YOUR_IP>:5000
python app.py

pause
