#!/bin/bash
echo "================================================"
echo "      نظام الأذان الآلي - Adhan System"
echo "================================================"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "[خطأ] Python3 غير مثبت"
    exit 1
fi

# Install dependencies
echo "[1/3] تثبيت المتطلبات..."
pip3 install -r requirements.txt -q

echo "[2/3] تهيئة قاعدة البيانات..."
echo "[3/3] تشغيل الخادم..."
echo ""
echo "================================================"
echo " الخادم يعمل على: http://localhost:5000"
echo " للإيقاف: اضغط Ctrl+C"
echo "================================================"

python3 app.py
