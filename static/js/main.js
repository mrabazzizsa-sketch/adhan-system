/* ─── Main Dashboard JS ─────────────────────────────────────────────── */

const player = document.getElementById('adhanPlayer');
let volume = window.ADHAN?.volume ?? 80;
let countdownSeconds = window.ADHAN?.nextPrayer?.remaining_seconds ?? 0;
let systemEnabled = true;

// ─── Clock & Countdown ────────────────────────────────────────────────

function startClock() {
  setInterval(() => {
    const now = new Date();
    const h = String(now.getHours()).padStart(2, '0');
    const m = String(now.getMinutes()).padStart(2, '0');
    const s = String(now.getSeconds()).padStart(2, '0');
    const el = document.getElementById('liveClock');
    if (el) el.textContent = `${h}:${m}:${s}`;

    // Countdown
    if (countdownSeconds > 0) {
      countdownSeconds--;
      updateCountdownDisplay();
    } else if (countdownSeconds === 0) {
      refreshData();
    }
  }, 1000);
}

function updateCountdownDisplay() {
  const h = Math.floor(countdownSeconds / 3600);
  const m = Math.floor((countdownSeconds % 3600) / 60);
  const s = countdownSeconds % 60;
  const hEl = document.getElementById('countdownHours');
  const mEl = document.getElementById('countdownMins');
  const sEl = document.getElementById('countdownSecs');
  if (hEl) hEl.textContent = String(h).padStart(2, '0');
  if (mEl) mEl.textContent = String(m).padStart(2, '0');
  if (sEl) sEl.textContent = String(s).padStart(2, '0');
  updateProgressRing();
}

function updateProgressRing() {
  const ring = document.getElementById('ringFill');
  if (!ring) return;
  // Assume average gap between prayers is ~3 hours (10800s)
  const MAX = 10800;
  const progress = Math.max(0, Math.min(1, 1 - countdownSeconds / MAX));
  const circumference = 327;
  ring.style.strokeDashoffset = circumference * (1 - progress);
}

// ─── Data Refresh ─────────────────────────────────────────────────────

let lastRefresh = Date.now();
function refreshData() {
  // Throttle
  if (Date.now() - lastRefresh < 30000) return;
  lastRefresh = Date.now();

  fetch('/api/prayer-times')
    .then(r => r.json())
    .then(data => {
      // Update prayer times
      window.ADHAN.prayerOrder.forEach(p => {
        const el = document.getElementById(`time-${p}`);
        if (el && data.times[p]) el.textContent = data.times[p];
        const card = document.getElementById(`card-${p}`);
        if (card) {
          card.classList.remove('next');
          if (data.next_prayer && data.next_prayer.prayer === p) {
            card.classList.add('next');
          }
        }
      });

      // Update next prayer
      if (data.next_prayer) {
        const np = data.next_prayer;
        countdownSeconds = np.remaining_seconds;
        const nameEl = document.getElementById('nextPrayerName');
        const timeEl = document.getElementById('nextPrayerTime');
        if (nameEl) nameEl.textContent = np.name;
        if (timeEl) timeEl.textContent = np.time;
      }

      // Update dates
      if (data.hijri) {
        const hEl = document.getElementById('hijriDate');
        if (hEl) hEl.textContent = data.hijri;
      }

      // Check if should play adhan
      checkAdhanTrigger(data);
    })
    .catch(err => console.warn('Refresh failed:', err));
}

// Refresh every 30 seconds
setInterval(refreshData, 30000);

// ─── Adhan Trigger (client-side backup) ──────────────────────────────

const playedToday = new Set();

function checkAdhanTrigger(data) {
  if (!data.system_enabled) return;
  const now = new Date();
  const timeStr = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;
  const today = now.toISOString().split('T')[0];

  window.ADHAN.prayerOrder.forEach(prayer => {
    const prayerTime = data.times[prayer];
    if (!prayerTime) return;
    const key = `${today}_${prayer}`;
    if (prayerTime === timeStr && !playedToday.has(key)) {
      playedToday.add(key);
      playAdhan(prayer, 'adhan');
      showNotification(`حان وقت صلاة ${window.ADHAN.prayerNames[prayer]}`);
    }
  });
}

// ─── Adhan Playback ───────────────────────────────────────────────────

function playAdhan(prayer, type = 'adhan') {
  fetch(`/api/get-audio/${prayer}/${type}`)
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        player.src = data.url;
        player.volume = volume / 100;
        player.play().catch(e => console.warn('Audio play failed:', e));
      }
    });
}

function testAdhan(prayer) {
  fetch('/api/test-adhan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prayer, type: 'adhan' }),
  })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        player.src = data.url;
        player.volume = volume / 100;
        player.play();
        showToast(`🔔 اختبار أذان ${window.ADHAN.prayerNames[prayer]}`);
      } else {
        showToast('لا يوجد ملف صوتي لهذه الصلاة', 'error');
      }
    });
}

// ─── Volume ───────────────────────────────────────────────────────────

function updateVolume(val) {
  volume = parseInt(val);
  document.getElementById('volumeVal').textContent = val + '%';
  player.volume = volume / 100;
  // Save
  fetch('/api/save-settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ volume: val }),
  });
}

// ─── Toggle System ────────────────────────────────────────────────────

function toggleSystem() {
  fetch('/api/toggle-system', { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      const btn = document.getElementById('toggleBtn');
      const badge = document.getElementById('systemBadge');
      const dot = badge?.querySelector('.status-dot');
      systemEnabled = data.enabled;
      if (data.enabled) {
        btn.textContent = '⏸ إيقاف النظام';
        btn.classList.add('active');
        if (dot) dot.classList.add('active');
        badge.querySelector('span:last-child').textContent = 'النظام يعمل';
        showToast('✅ تم تشغيل النظام');
      } else {
        btn.textContent = '▶ تشغيل النظام';
        btn.classList.remove('active');
        if (dot) dot.classList.remove('active');
        badge.querySelector('span:last-child').textContent = 'النظام متوقف';
        showToast('⏸ تم إيقاف النظام', 'warning');
      }
    });
}

// ─── Refresh Times ────────────────────────────────────────────────────

function refreshTimes() {
  showToast('⌛ جاري تحديث المواقيت...');
  fetch('/api/refresh-times', { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        showToast('✅ تم تحديث مواقيت الصلاة');
        lastRefresh = 0;
        refreshData();
      } else {
        showToast('تعذّر الاتصال بالخادم', 'error');
      }
    });
}

// ─── Notifications ────────────────────────────────────────────────────

function showNotification(text) {
  if ('Notification' in window && Notification.permission === 'granted') {
    new Notification('🕌 نظام الأذان', { body: text, icon: '/static/mosque.png' });
  }
  showToast('🔔 ' + text);
}

function requestNotificationPermission() {
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
  }
}

// ─── Toast ────────────────────────────────────────────────────────────

function showToast(msg, type = 'success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show ' + type;
  setTimeout(() => { t.className = 'toast'; }, 3500);
}

// ─── Init ─────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  startClock();
  updateCountdownDisplay();
  updateProgressRing();
  requestNotificationPermission();

  // Set volume slider
  const vs = document.getElementById('volumeSlider');
  if (vs) {
    vs.value = volume;
    player.volume = volume / 100;
  }
});
