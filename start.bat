@echo off
chcp 65001 >nul
title نظام الأذان الآلي
color 0A

echo ================================================
echo        نظام الأذان الآلي - Adhan System
echo ================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [خطأ] Python غير مثبت. يرجى تحميله من:
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Install dependencies if needed
echo [1/3] التحقق من المتطلبات...
pip install -r requirements.txt -q
if errorlevel 1 (
    echo [خطأ] فشل تثبيت المتطلبات
    pause
    exit /b 1
)

echo [2/3] تهيئة قاعدة البيانات...
echo [3/3] تشغيل الخادم...
echo.
echo ================================================
echo  الخادم يعمل على: http://localhost:5000
echo  لفتح الواجهة: http://localhost:5000
echo  للإيقاف: اضغط Ctrl+C
echo ================================================
echo.

:: Open browser after 2 seconds
start "" /b cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:5000"

:: Run server
python app.py

pause
