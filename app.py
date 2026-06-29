import os, json, sqlite3, logging, threading, time, requests
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, Response
from werkzeug.utils import secure_filename
import pytz

app = Flask(__name__)
app.config['SECRET_KEY'] = 'adhan-secret-2024'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME', '')
CLOUDINARY_API_KEY    = os.environ.get('CLOUDINARY_API_KEY', '')
CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET', '')

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = '/tmp/adhan.db'
PRAYER_NAMES = {'fajr':'الفجر','dhuhr':'الظهر','asr':'العصر','maghrib':'المغرب','isha':'العشاء'}
PRAYER_ORDER = ['fajr','dhuhr','asr','maghrib','isha']
scheduler_running = False
last_triggered = {}

# ── DB ──────────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
    c.execute('''CREATE TABLE IF NOT EXISTS prayer_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT, prayer TEXT, type TEXT DEFAULT "adhan",
        filename TEXT, original_name TEXT, cloudinary_url TEXT,
        uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS prayer_adjustments (
        prayer TEXT PRIMARY KEY, adjustment_minutes INTEGER DEFAULT 0,
        iqama_minutes INTEGER DEFAULT 20, enabled INTEGER DEFAULT 1)''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT,
        message TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS prayer_times_cache (
        date TEXT PRIMARY KEY, times TEXT, cached_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    for k,v in [('city','Riyadh'),('country','SA'),('timezone','Asia/Riyadh'),
                ('volume','80'),('notification_before','5'),('system_enabled','1'),
                ('calculation_method','4'),('school','0')]:
        c.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', (k,v))
    for p in PRAYER_ORDER:
        c.execute('INSERT OR IGNORE INTO prayer_adjustments (prayer) VALUES (?)', (p,))
    conn.commit(); conn.close()
    logger.info('DB ready')

def get_setting(key, default=None):
    try:
        conn = get_db()
        r = conn.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        conn.close()
        return r['value'] if r else default
    except: return default

def set_setting(key, value):
    conn = get_db()
    conn.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(key,value))
    conn.commit(); conn.close()

def add_log(event_type, message):
    try:
        conn = get_db()
        conn.execute('INSERT INTO logs (event_type,message) VALUES (?,?)',(event_type,message))
        conn.commit(); conn.close()
    except: pass

# ── Cloudinary ──────────────────────────────────────────────────────────────

def upload_to_cloudinary(file_data, filename):
    if not CLOUDINARY_CLOUD_NAME: return None
    try:
        import hashlib
        ts = str(int(time.time()))
        pid = f'adhan/{filename.rsplit(".",1)[0]}'
        sig = hashlib.sha1((f'public_id={pid}&timestamp={ts}'+CLOUDINARY_API_SECRET).encode()).hexdigest()
        r = requests.post(f'https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/video/upload',
            files={'file':(filename,file_data)},
            data={'api_key':CLOUDINARY_API_KEY,'timestamp':ts,'public_id':pid,'signature':sig},timeout=60)
        return r.json().get('secure_url')
    except Exception as e:
        logger.error(f'Cloudinary: {e}'); return None

# ── Prayer Times ─────────────────────────────────────────────────────────────

def fetch_prayer_times(date_str=None):
    if not date_str: date_str = datetime.now().strftime('%d-%m-%Y')
    city    = get_setting('city','Riyadh')
    country = get_setting('country','SA')
    method  = get_setting('calculation_method','4')
    cache_key = date_str.replace('-','')
    try:
        conn = get_db()
        cached = conn.execute('SELECT times FROM prayer_times_cache WHERE date=?',(cache_key,)).fetchone()
        conn.close()
        if cached: return json.loads(cached['times'])
    except: pass
    try:
        r = requests.get(f'https://api.aladhan.com/v1/timingsByCity/{date_str}',
            params={'city':city,'country':country,'method':method},timeout=10)
        d = r.json()
        if d.get('code')==200:
            t = d['data']['timings']
            h = d['data']['date']['hijri']
            g = d['data']['date']['gregorian']
            result = {'fajr':t['Fajr'],'dhuhr':t['Dhuhr'],'asr':t['Asr'],
                      'maghrib':t['Maghrib'],'isha':t['Isha'],
                      'hijri':f"{h['day']} {h['month']['ar']} {h['year']}هـ",
                      'gregorian':g['date']}
            try:
                conn = get_db()
                conn.execute('INSERT OR REPLACE INTO prayer_times_cache VALUES (?,?)',
                             (cache_key, json.dumps(result,ensure_ascii=False)))
                conn.commit(); conn.close()
            except: pass
            return result
    except Exception as e:
        logger.error(f'Prayer API: {e}')
    return None

def get_adjusted_times(times):
    if not times: return times
    try:
        conn = get_db()
        adjs = {r['prayer']:r['adjustment_minutes'] for r in conn.execute('SELECT prayer,adjustment_minutes FROM prayer_adjustments').fetchall()}
        conn.close()
        result = dict(times)
        for p in PRAYER_ORDER:
            if p in result and adjs.get(p,0) != 0:
                t = datetime.strptime(result[p],'%H:%M') + timedelta(minutes=adjs[p])
                result[p] = t.strftime('%H:%M')
        return result
    except: return times

def get_next_prayer(times):
    tz  = pytz.timezone(get_setting('timezone','Asia/Riyadh'))
    now = datetime.now(tz)
    now_str = now.strftime('%H:%M')
    for p in PRAYER_ORDER:
        pt = times.get(p)
        if pt and pt > now_str:
            t = datetime.strptime(pt,'%H:%M')
            dt = now.replace(hour=t.hour,minute=t.minute,second=0,microsecond=0)
            secs = int((dt-now).total_seconds())
            return {'prayer':p,'name':PRAYER_NAMES[p],'time':pt,
                    'remaining_hours':secs//3600,'remaining_minutes':(secs%3600)//60,'remaining_seconds':secs}
    pt = times.get('fajr','05:00')
    t  = datetime.strptime(pt,'%H:%M')
    dt = (now+timedelta(days=1)).replace(hour=t.hour,minute=t.minute,second=0,microsecond=0)
    secs = int((dt-now).total_seconds())
    return {'prayer':'fajr','name':PRAYER_NAMES['fajr'],'time':pt,
            'remaining_hours':secs//3600,'remaining_minutes':(secs%3600)//60,'remaining_seconds':secs}

# ── Scheduler ────────────────────────────────────────────────────────────────

def scheduler_loop():
    while scheduler_running:
        try:
            if get_setting('system_enabled','1')=='1':
                tz  = pytz.timezone(get_setting('timezone','Asia/Riyadh'))
                now = datetime.now(tz)
                now_str = now.strftime('%H:%M')
                today   = now.strftime('%d-%m-%Y')
                times   = fetch_prayer_times(today)
                if times:
                    adj = get_adjusted_times(times)
                    for p in PRAYER_ORDER:
                        pt = adj.get(p)
                        if not pt: continue
                        key = f'{today}_{p}'
                        if pt==now_str and key not in last_triggered:
                            last_triggered[key]=True
                            add_log('ADHAN',f'تشغيل أذان {PRAYER_NAMES[p]} - {pt}')
                old = [k for k in last_triggered if not k.startswith(today)]
                for k in old: del last_triggered[k]
        except Exception as e: logger.error(f'Scheduler: {e}')
        time.sleep(30)

def start_scheduler():
    global scheduler_running
    if scheduler_running: return
    scheduler_running = True
    threading.Thread(target=scheduler_loop, daemon=True).start()

# ── Initialize immediately ───────────────────────────────────────────────────

init_db()
start_scheduler()

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    today = datetime.now().strftime('%d-%m-%Y')
    times = fetch_prayer_times(today)
    adj   = get_adjusted_times(times) if times else {}
    next_p = get_next_prayer(adj) if adj else None
    tz  = pytz.timezone(get_setting('timezone','Asia/Riyadh'))
    now = datetime.now(tz)
    return render_template('index.html', times=adj, next_prayer=next_p,
        prayer_names=PRAYER_NAMES, prayer_order=PRAYER_ORDER,
        hijri=adj.get('hijri',''), gregorian=adj.get('gregorian',''),
        city=get_setting('city','الرياض'), system_enabled=get_setting('system_enabled','1'),
        volume=get_setting('volume','80'), current_time=now.strftime('%H:%M:%S'))

@app.route('/settings')
def settings():
    conn = get_db()
    all_settings = {r['key']:r['value'] for r in conn.execute('SELECT * FROM settings').fetchall()}
    adjustments  = {r['prayer']:dict(r) for r in conn.execute('SELECT * FROM prayer_adjustments').fetchall()}
    files = {}
    for r in conn.execute('SELECT * FROM prayer_files ORDER BY uploaded_at DESC').fetchall():
        k = f"{r['prayer']}_{r['type']}"
        if k not in files: files[k]=dict(r)
    conn.close()
    return render_template('settings.html', settings=all_settings, adjustments=adjustments,
        files=files, prayer_names=PRAYER_NAMES, prayer_order=PRAYER_ORDER,
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
    adj   = get_adjusted_times(times)
    next_p = get_next_prayer(adj) if adj else None
    tz  = pytz.timezone(get_setting('timezone','Asia/Riyadh'))
    now = datetime.now(tz)
    return jsonify({'times':adj,'next_prayer':next_p,'current_time':now.strftime('%H:%M:%S'),
                    'hijri':adj.get('hijri',''),'system_enabled':get_setting('system_enabled','1')=='1'})

@app.route('/api/upload-audio', methods=['POST'])
def upload_audio():
    prayer = request.form.get('prayer')
    atype  = request.form.get('type','adhan')
    if not prayer or prayer not in PRAYER_ORDER:
        return jsonify({'success':False,'error':'صلاة غير صالحة'})
    if 'file' not in request.files:
        return jsonify({'success':False,'error':'لم يتم اختيار ملف'})
    f = request.files['file']
    ext = f.filename.rsplit('.',1)[-1].lower()
    filename = secure_filename(f'{prayer}_{atype}_{int(time.time())}.{ext}')
    data = f.read()
    url = upload_to_cloudinary(data, filename)
    if not url:
        os.makedirs('static/uploads', exist_ok=True)
        with open(f'static/uploads/{filename}','wb') as fp: fp.write(data)
        url = f'/static/uploads/{filename}'
    conn = get_db()
    conn.execute('INSERT INTO prayer_files (prayer,type,filename,original_name,cloudinary_url) VALUES (?,?,?,?,?)',
                 (prayer,atype,filename,f.filename,url))
    conn.commit(); conn.close()
    add_log('UPLOAD',f'رفع {atype} لصلاة {PRAYER_NAMES[prayer]}')
    return jsonify({'success':True,'url':url})

@app.route('/api/get-audio/<prayer>/<atype>')
def get_audio(prayer, atype):
    conn = get_db()
    r = conn.execute('SELECT cloudinary_url,filename FROM prayer_files WHERE prayer=? AND type=? ORDER BY uploaded_at DESC LIMIT 1',(prayer,atype)).fetchone()
    conn.close()
    if r:
        return jsonify({'success':True,'url':r['cloudinary_url'] or f'/static/uploads/{r["filename"]}'})
    return jsonify({'success':False})

@app.route('/api/save-settings', methods=['POST'])
def save_settings():
    for k,v in request.json.items(): set_setting(k,str(v))
    add_log('SETTINGS','تم حفظ الإعدادات')
    return jsonify({'success':True})

@app.route('/api/save-adjustments', methods=['POST'])
def save_adjustments():
    conn = get_db()
    for p,adj in request.json.items():
        conn.execute('INSERT OR REPLACE INTO prayer_adjustments (prayer,adjustment_minutes,iqama_minutes,enabled) VALUES (?,?,?,?)',
                     (p,adj.get('adjustment',0),adj.get('iqama',20),1 if adj.get('enabled',True) else 0))
    conn.commit()
    conn.execute('DELETE FROM prayer_times_cache')
    conn.commit(); conn.close()
    return jsonify({'success':True})

@app.route('/api/toggle-system', methods=['POST'])
def toggle_system():
    new = '0' if get_setting('system_enabled','1')=='1' else '1'
    set_setting('system_enabled', new)
    add_log('SYSTEM',f'تم {"تشغيل" if new=="1" else "إيقاف"} النظام')
    return jsonify({'success':True,'enabled':new=='1'})

@app.route('/api/test-adhan', methods=['POST'])
def test_adhan():
    prayer = request.json.get('prayer','fajr')
    atype  = request.json.get('type','adhan')
    conn = get_db()
    r = conn.execute('SELECT cloudinary_url,filename FROM prayer_files WHERE prayer=? AND type=? ORDER BY uploaded_at DESC LIMIT 1',(prayer,atype)).fetchone()
    conn.close()
    if r:
        add_log('TEST',f'اختبار {PRAYER_NAMES.get(prayer,prayer)}')
        return jsonify({'success':True,'url':r['cloudinary_url'] or f'/static/uploads/{r["filename"]}'})
    return jsonify({'success':False,'error':'لا يوجد ملف صوتي'})

@app.route('/api/delete-audio', methods=['POST'])
def delete_audio():
    conn = get_db()
    conn.execute('DELETE FROM prayer_files WHERE id=?',(request.json.get('id'),))
    conn.commit(); conn.close()
    return jsonify({'success':True})

@app.route('/api/refresh-times', methods=['POST'])
def refresh_times():
    conn = get_db()
    conn.execute('DELETE FROM prayer_times_cache')
    conn.commit(); conn.close()
    times = fetch_prayer_times()
    return jsonify({'success':times is not None,'times':get_adjusted_times(times) if times else {}})

@app.route('/api/backup')
def backup():
    conn = get_db()
    data = {'settings':{r['key']:r['value'] for r in conn.execute('SELECT * FROM settings').fetchall()},
            'adjustments':[dict(r) for r in conn.execute('SELECT * FROM prayer_adjustments').fetchall()],
            'exported_at':datetime.now().isoformat()}
    conn.close()
    return Response(json.dumps(data,ensure_ascii=False,indent=2), mimetype='application/json',
                    headers={'Content-Disposition':f'attachment; filename=backup_{datetime.now().strftime("%Y%m%d")}.json'})

@app.route('/api/logs')
def api_logs():
    conn = get_db()
    logs = [dict(r) for r in conn.execute('SELECT * FROM logs ORDER BY created_at DESC LIMIT 100').fetchall()]
    conn.close()
    return jsonify(logs)

@app.route('/api/clear-logs', methods=['POST'])
def clear_logs():
    conn = get_db()
    conn.execute('DELETE FROM logs')
    conn.commit(); conn.close()
    return jsonify({'success':True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',5000)), debug=False)
