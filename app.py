import os
import json
import sqlite3
import logging
import threading
import time
import requests
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for, Response
from werkzeug.utils import secure_filename
import pytz

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'adhan-system-secret-key-2024')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# Cloudinary config from environment
CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME', '')
CLOUDINARY_API_KEY = os.environ.get('CLOUDINARY_API_KEY', '')
CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET', '')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

DB_PATH = os.environ.get('DB_PATH', 'instance/adhan.db')
scheduler_thread = None
scheduler_running = False

# ─── Database ────────────────────────────────────────────────────────────────

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs('instance', exist_ok=True)
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS prayer_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prayer TEXT NOT NULL,
        type TEXT NOT NULL DEFAULT 'adhan',
        filename TEXT NOT NULL,
        original_name TEXT,
        cloudinary_url TEXT,
        uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS prayer_adjustments (
        prayer TEXT PRIMARY KEY,
        adjustment_minutes INTEGER DEFAULT 0,
        iqama_minutes INTEGER DEFAULT 20,
        enabled INTEGER DEFAULT 1
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT,
        message TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS prayer_times_cache (
        date TEXT PRIMARY KEY,
        times TEXT,
        cached_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    defaults = {
        'city': 'Riyadh', 'country': 'SA', 'timezone': 'Asia/Riyadh',
        'volume': '80', 'notification_before': '5', 'system_enabled': '1',
        'calculation_method': '4', 'school': '0',
    }
    for key, value in defaults.items():
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))
    prayers = ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']
    for prayer in prayers:
        c.execute('INSERT OR IGNORE INTO prayer_adjustments (prayer, adjustment_minutes, iqama_minutes, enabled) VALUES (?, 0, 20, 1)', (prayer,))
    conn.commit()
    conn.close()
    logger.info('Database initialized')

def get_setting(key, default=None):
    conn = get_db()
    row = conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    conn.close()
    return row['value'] if row else default

def set_setting(key, value):
    conn = get_db()
    conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

def add_log(event_type, message):
    conn = get_db()
    conn.execute('INSERT INTO logs (event_type, message) VALUES (?, ?)', (event_type, message))
    conn.commit()
    conn.close()

# ─── Cloudinary Upload ───────────────────────────────────────────────────────

def upload_to_cloudinary(file_data, filename):
    if not CLOUDINARY_CLOUD_NAME:
        return None
    try:
        import hashlib, hmac
        timestamp = str(int(time.time()))
        public_id = f'adhan/{filename.rsplit(".", 1)[0]}'
        params = f'public_id={public_id}&timestamp={timestamp}'
        signature = hashlib.sha1((params + CLOUDINARY_API_SECRET).encode()).hexdigest()
        files = {'file': (filename, file_data)}
        data = {
            'api_key': CLOUDINARY_API_KEY,
            'timestamp': timestamp,
            'public_id': public_id,
            'signature': signature,
        }
        resp = requests.post(
            f'https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/video/upload',
            files=files, data=data, timeout=60
        )
        result = resp.json()
        return result.get('secure_url')
    except Exception as e:
        logger.error(f'Cloudinary upload error: {e}')
        return None

# ─── Prayer Times ─────────────────────────────────────────────────────────────

PRAYER_NAMES = {
    'fajr': 'الفجر', 'dhuhr': 'الظهر', 'asr': 'العصر',
    'maghrib': 'المغرب', 'isha': 'العشاء'
}
PRAYER_ORDER = ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']

def fetch_prayer_times(date_str=None, city=None, country=None, method=None):
    if not date_str:
        date_str = datetime.now().strftime('%d-%m-%Y')
    if not city: city = get_setting('city', 'Riyadh')
    if not country: country = get_setting('country', 'SA')
    if not method: method = get_setting('calculation_method', '4')

    conn = get_db()
    cache_date = date_str.replace('-', '')
    cached = conn.execute('SELECT times FROM prayer_times_cache WHERE date=?', (cache_date,)).fetchone()
    conn.close()
    if cached:
        return json.loads(cached['times'])

    try:
        url = f'https://api.aladhan.com/v1/timingsByCity/{date_str}'
        params = {'city': city, 'country': country, 'method': method, 'school': get_setting('school', '0')}
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get('code') == 200:
            timings = data['data']['timings']
            hijri = data['data']['date']['hijri']
            gregorian = data['data']['date']['gregorian']
            result = {
                'fajr': timings['Fajr'], 'dhuhr': timings['Dhuhr'],
                'asr': timings['Asr'], 'maghrib': timings['Maghrib'],
                'isha': timings['Isha'],
                'hijri': f"{hijri['day']} {hijri['month']['ar']} {hijri['year']}هـ",
                'gregorian': gregorian['date'], 'date_str': date_str,
            }
            conn = get_db()
            conn.execute('INSERT OR REPLACE INTO prayer_times_cache (date, times) VALUES (?, ?)',
                        (cache_date, json.dumps(result, ensure_ascii=False)))
            conn.commit()
            conn.close()
            return result
    except Exception as e:
        logger.error(f'Failed to fetch prayer times: {e}')
    return None

def get_adjusted_times(times_dict):
    if not times_dict: return times_dict
    conn = get_db()
    adjustments = {row['prayer']: row['adjustment_minutes']
                   for row in conn.execute('SELECT prayer, adjustment_minutes FROM prayer_adjustments').fetchall()}
    conn.close()
    result = dict(times_dict)
    for prayer in PRAYER_ORDER:
        if prayer in result and prayer in adjustments and adjustments[prayer] != 0:
            t = datetime.strptime(result[prayer], '%H:%M')
            t += timedelta(minutes=adjustments[prayer])
            result[prayer] = t.strftime('%H:%M')
    return result

def get_next_prayer(times_dict):
    tz = pytz.timezone(get_setting('timezone', 'Asia/Riyadh'))
    now = datetime.now(tz)
    now_time = now.strftime('%H:%M')
    for prayer in PRAYER_ORDER:
        prayer_time = times_dict.get(prayer)
        if prayer_time and prayer_time > now_time:
            t = datetime.strptime(prayer_time, '%H:%M')
            full_dt = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            diff = full_dt - now
            total_seconds = int(diff.total_seconds())
            return {
                'prayer': prayer, 'name': PRAYER_NAMES[prayer], 'time': prayer_time,
                'remaining_hours': total_seconds // 3600,
                'remaining_minutes': (total_seconds % 3600) // 60,
                'remaining_seconds': total_seconds,
            }
    fajr_time = times_dict.get('fajr', '05:00')
    t = datetime.strptime(fajr_time, '%H:%M')
    tomorrow = now + timedelta(days=1)
    full_dt = tomorrow.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    diff = full_dt - now
    total_seconds = int(diff.total_seconds())
    return {
        'prayer': 'fajr', 'name': PRAYER_NAMES['fajr'], 'time': fajr_time,
        'remaining_hours': total_seconds // 3600,
        'remaining_minutes': (total_seconds % 3600) // 60,
        'remaining_seconds': total_seconds,
    }

# ─── Scheduler ───────────────────────────────────────────────────────────────

last_triggered = {}

def scheduler_loop():
    global scheduler_running
    logger.info('Scheduler started')
    while scheduler_running:
        try:
            if get_setting('system_enabled', '1') == '1':
                tz = pytz.timezone(get_setting('timezone', 'Asia/Riyadh'))
                now = datetime.now(tz)
                now_str = now.strftime('%H:%M')
                today = now.strftime('%d-%m-%Y')
                times = fetch_prayer_times(today)
                if times:
                    adj_times = get_adjusted_times(times)
                    conn = get_db()
                    adjustments = {row['prayer']: row for row in conn.execute('SELECT * FROM prayer_adjustments').fetchall()}
                    conn.close()
                    for prayer in PRAYER_ORDER:
                        prayer_time = adj_times.get(prayer)
                        if not prayer_time: continue
                        adj = adjustments.get(prayer)
                        if adj and not adj['enabled']: continue
                        trigger_key = f'{today}_{prayer}'
                        notif_before = int(get_setting('notification_before', '5'))
                        t = datetime.strptime(prayer_time, '%H:%M')
                        notif_time = (now.replace(hour=t.hour, minute=t.minute, second=0) - timedelta(minutes=notif_before)).strftime('%H:%M')
                        notif_key = f'{today}_{prayer}_notif'
                        if notif_time == now_str and notif_key not in last_triggered:
                            last_triggered[notif_key] = True
                            add_log('NOTIFICATION', f'تنبيه: سيحين وقت صلاة {PRAYER_NAMES[prayer]} بعد {notif_before} دقائق')
                        if prayer_time == now_str and trigger_key not in last_triggered:
                            last_triggered[trigger_key] = True
                            add_log('ADHAN', f'تشغيل أذان {PRAYER_NAMES[prayer]} - {prayer_time}')
                old_keys = [k for k in last_triggered if not k.startswith(today)]
                for k in old_keys: del last_triggered[k]
        except Exception as e:
            logger.error(f'Scheduler error: {e}')
        time.sleep(30)

def start_scheduler():
    global scheduler_thread, scheduler_running
    if scheduler_thread and scheduler_thread.is_alive(): return
    scheduler_running = True
    scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
    scheduler_thread.start()

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    today = datetime.now().strftime('%d-%m-%Y')
    times = fetch_prayer_times(today)
    adj_times = get_adjusted_times(times) if times else {}
    next_prayer = get_next_prayer(adj_times) if adj_times else None
    tz = pytz.timezone(get_setting('timezone', 'Asia/Riyadh'))
    now = datetime.now(tz)
    return render_template('index.html',
        times=adj_times, next_prayer=next_prayer,
        prayer_names=PRAYER_NAMES, prayer_order=PRAYER_ORDER,
        hijri=adj_times.get('hijri', ''), gregorian=adj_times.get('gregorian', ''),
        city=get_setting('city', 'الرياض'), system_enabled=get_setting('system_enabled', '1'),
        volume=get_setting('volume', '80'), current_time=now.strftime('%H:%M:%S'))

@app.route('/settings')
def settings():
    conn = get_db()
    all_settings = {row['key']: row['value'] for row in conn.execute('SELECT * FROM settings').fetchall()}
    adjustments = {row['prayer']: dict(row) for row in conn.execute('SELECT * FROM prayer_adjustments').fetchall()}
    files = {}
    for row in conn.execute('SELECT * FROM prayer_files ORDER BY uploaded_at DESC').fetchall():
        key = f"{row['prayer']}_{row['type']}"
        if key not in files: files[key] = dict(row)
    conn.close()
    return render_template('settings.html',
        settings=all_settings, adjustments=adjustments, files=files,
        prayer_names=PRAYER_NAMES, prayer_order=PRAYER_ORDER,
        cloudinary_configured=bool(CLOUDINARY_CLOUD_NAME))

@app.route('/logs')
def logs_page():
    conn = get_db()
    logs = conn.execute('SELECT * FROM logs ORDER BY created_at DESC LIMIT 200').fetchall()
    conn.close()
    return render_template('logs.html', logs=logs)

@app.route('/api/prayer-times')
def api_prayer_times():
    today = datetime.now().strftime('%d-%m-%Y')
    times = fetch_prayer_times(today)
    adj_times = get_adjusted_times(times)
    next_prayer = get_next_prayer(adj_times) if adj_times else None
    tz = pytz.timezone(get_setting('timezone', 'Asia/Riyadh'))
    now = datetime.now(tz)
    return jsonify({
        'times': adj_times, 'next_prayer': next_prayer,
        'current_time': now.strftime('%H:%M:%S'),
        'hijri': adj_times.get('hijri', ''),
        'system_enabled': get_setting('system_enabled', '1') == '1',
    })

@app.route('/api/upload-audio', methods=['POST'])
def upload_audio():
    prayer = request.form.get('prayer')
    audio_type = request.form.get('type', 'adhan')
    if not prayer or prayer not in PRAYER_ORDER:
        return jsonify({'success': False, 'error': 'صلاة غير صالحة'})
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'لم يتم اختيار ملف'})
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'لم يتم اختيار ملف'})

    filename = secure_filename(f'{prayer}_{audio_type}_{int(time.time())}.{file.filename.rsplit(".", 1)[1].lower()}')
    file_data = file.read()

    # Upload to Cloudinary
    cloudinary_url = upload_to_cloudinary(file_data, filename)

    if not cloudinary_url and not CLOUDINARY_CLOUD_NAME:
        # Local fallback
        os.makedirs('static/uploads', exist_ok=True)
        with open(f'static/uploads/{filename}', 'wb') as f:
            f.write(file_data)
        cloudinary_url = f'/static/uploads/{filename}'

    if not cloudinary_url:
        return jsonify({'success': False, 'error': 'فشل رفع الملف. تأكد من إعدادات Cloudinary'})

    conn = get_db()
    conn.execute('INSERT INTO prayer_files (prayer, type, filename, original_name, cloudinary_url) VALUES (?, ?, ?, ?, ?)',
                (prayer, audio_type, filename, file.filename, cloudinary_url))
    conn.commit()
    conn.close()
    add_log('UPLOAD', f'تم رفع ملف {audio_type} لصلاة {PRAYER_NAMES[prayer]}: {file.filename}')
    return jsonify({'success': True, 'url': cloudinary_url})

@app.route('/api/get-audio/<prayer>/<audio_type>')
def get_audio(prayer, audio_type):
    conn = get_db()
    row = conn.execute('SELECT cloudinary_url, filename FROM prayer_files WHERE prayer=? AND type=? ORDER BY uploaded_at DESC LIMIT 1',
                      (prayer, audio_type)).fetchone()
    conn.close()
    if row:
        url = row['cloudinary_url'] or f'/static/uploads/{row["filename"]}'
        return jsonify({'success': True, 'url': url})
    return jsonify({'success': False, 'error': 'لا يوجد ملف صوتي'})

@app.route('/api/save-settings', methods=['POST'])
def save_settings():
    data = request.json
    for key, value in data.items():
        set_setting(key, str(value))
    add_log('SETTINGS', 'تم حفظ الإعدادات')
    return jsonify({'success': True})

@app.route('/api/save-adjustments', methods=['POST'])
def save_adjustments():
    data = request.json
    conn = get_db()
    for prayer, adj in data.items():
        conn.execute('INSERT OR REPLACE INTO prayer_adjustments (prayer, adjustment_minutes, iqama_minutes, enabled) VALUES (?, ?, ?, ?)',
                    (prayer, adj.get('adjustment', 0), adj.get('iqama', 20), 1 if adj.get('enabled', True) else 0))
    conn.commit()
    conn.close()
    conn = get_db()
    conn.execute('DELETE FROM prayer_times_cache')
    conn.commit()
    conn.close()
    add_log('SETTINGS', 'تم حفظ تعديلات مواقيت الصلاة')
    return jsonify({'success': True})

@app.route('/api/toggle-system', methods=['POST'])
def toggle_system():
    current = get_setting('system_enabled', '1')
    new_val = '0' if current == '1' else '1'
    set_setting('system_enabled', new_val)
    add_log('SYSTEM', f'تم {"تشغيل" if new_val == "1" else "إيقاف"} النظام')
    return jsonify({'success': True, 'enabled': new_val == '1'})

@app.route('/api/test-adhan', methods=['POST'])
def test_adhan():
    prayer = request.json.get('prayer', 'fajr')
    audio_type = request.json.get('type', 'adhan')
    conn = get_db()
    row = conn.execute('SELECT cloudinary_url, filename FROM prayer_files WHERE prayer=? AND type=? ORDER BY uploaded_at DESC LIMIT 1',
                      (prayer, audio_type)).fetchone()
    conn.close()
    if row:
        url = row['cloudinary_url'] or f'/static/uploads/{row["filename"]}'
        add_log('TEST', f'اختبار تشغيل {audio_type} لصلاة {PRAYER_NAMES.get(prayer, prayer)}')
        return jsonify({'success': True, 'url': url})
    return jsonify({'success': False, 'error': 'لا يوجد ملف صوتي لهذه الصلاة'})

@app.route('/api/delete-audio', methods=['POST'])
def delete_audio():
    file_id = request.json.get('id')
    conn = get_db()
    conn.execute('DELETE FROM prayer_files WHERE id=?', (file_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/backup')
def backup():
    conn = get_db()
    data = {
        'settings': {row['key']: row['value'] for row in conn.execute('SELECT * FROM settings').fetchall()},
        'adjustments': [dict(row) for row in conn.execute('SELECT * FROM prayer_adjustments').fetchall()],
        'exported_at': datetime.now().isoformat(),
    }
    conn.close()
    return Response(json.dumps(data, ensure_ascii=False, indent=2), mimetype='application/json',
                   headers={'Content-Disposition': f'attachment; filename=adhan_backup_{datetime.now().strftime("%Y%m%d")}.json'})

@app.route('/api/logs')
def api_logs():
    conn = get_db()
    logs = [dict(row) for row in conn.execute('SELECT * FROM logs ORDER BY created_at DESC LIMIT 100').fetchall()]
    conn.close()
    return jsonify(logs)

@app.route('/api/clear-logs', methods=['POST'])
def clear_logs():
    conn = get_db()
    conn.execute('DELETE FROM logs')
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/refresh-times', methods=['POST'])
def refresh_times():
    conn = get_db()
    conn.execute('DELETE FROM prayer_times_cache')
    conn.commit()
    conn.close()
    today = datetime.now().strftime('%d-%m-%Y')
    times = fetch_prayer_times(today)
    return jsonify({'success': times is not None, 'times': get_adjusted_times(times) if times else {}})

if __name__ == '__main__':
    init_db()
    start_scheduler()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
