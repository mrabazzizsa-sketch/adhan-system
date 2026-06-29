/* ─── Main Dashboard JS ─────────────────────────────────────────────── */

const player = document.getElementById('adhanPlayer');
let volume = window.ADHAN?.volume ?? 80;
let countdownSeconds = window.ADHAN?.nextPrayer?.remaining_seconds ?? 0;
const playedToday = new Set();

// ─── Clock ────────────────────────────────────────────────────────────

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
    }

    // Check adhan every minute at :00 seconds
    if (s === '00') {
      checkAdhanNow(`${h}:${m}`);
    }
  }, 1000);
}

// ─── Countdown ────────────────────────────────────────────────────────

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
  const MAX = 10800;
  const progress = Math.max(0, Math.min(1, 1 - countdownSeconds / MAX));
  ring.style.strokeDashoffset = 327 * (1 - progress);
}

// ─── Adhan Check ──────────────────────────────────────────────────────

function checkAdhanNow(timeStr) {
  const today = new Date().toISOString().split('T')[0];

  // Get latest times from API
  fetch('/api/prayer-times')
    .then(r => r.json())
    .then(data => {
      if (!data.system_enabled) return;

      window.ADHAN.prayerOrder.forEach(prayer => {
        const prayerTime = data.times[prayer];
        if (!prayerTime) return;

        const key = `${today}_${prayer}`;

        // Notify 5 min before
        const [ph, pm] = prayerTime.split(':').map(Number);
        const prayerTotalMin = ph * 60 + pm;
        const nowTotalMin = parseInt(timeStr.split(':')[0]) * 60 + parseInt(timeStr.split(':')[1]);

        if (prayerTotalMin - nowTotalMin === 5 && !playedToday.has(`${key}_notif`)) {
          playedToday.add(`${key}_notif`);
          showToast(`🔔 سيحين أذان ${window.ADHAN.prayerNames[prayer]} بعد 5 دقائق`);
        }

        // Play adhan exactly at prayer time
        if (prayerTime === timeStr && !playedToday.has(key)) {
          playedToday.add(key);
          playAdhan(prayer, 'adhan');
          showToast(`🕌 حان وقت صلاة ${window.ADHAN.prayerNames[prayer]}`);
          showNotification(`حان وقت صلاة ${window.ADHAN.prayerNames[prayer]}`);
        }
      });

      // Update next prayer countdown
      if (data.next_prayer) {
        countdownSeconds = data.next_prayer.remaining_seconds;
        const nameEl = document.getElementById('nextPrayerName');
        const timeEl = document.getElementById('nextPrayerTime');
        if (nameEl) nameEl.textContent = data.next_prayer.name;
        if (timeEl) timeEl.textContent = data.next_prayer.time;

        // Update highlighted card
        window.ADHAN.prayerOrder.forEach(p => {
          const card = document.getElementById(`card-${p}`);
          if (card) {
            card.classList.toggle('next', data.next_prayer.prayer === p);
          }
        });
      }

      // Update prayer times display
      window.ADHAN.prayerOrder.forEach(p => {
        const el = document.getElementById(`time-${p}`);
        if (el && data.times[p]) el.textContent = data.times[p];
      });

      // Update hijri date
      if (data.hijri) {
        const hEl = document.getElementById('hijriDate');
        if (hEl) hEl.textContent = data.hijri;
      }
    })
    .catch(err => console.warn('API error:', err));
}

// ─── Adhan Playback ───────────────────────────────────────────────────

function playAdhan(prayer, type = 'adhan') {
  fetch(`/api/get-audio/${prayer}/${type}`)
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        player.src = data.url;
        player.volume = volume / 100;
        player.play().catch(e => {
          console.warn('Audio play failed:', e);
          showToast('⚠️ تعذّر تشغيل الصوت تلقائياً — تأكد من تفاعلك مع الصفحة أولاً', 'warning');
        });
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

// ─── Refresh ──────────────────────────────────────────────────────────

function refreshTimes() {
  showToast('⌛ جاري تحديث المواقيت...');
  fetch('/api/refresh-times', { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        showToast('✅ تم تحديث مواقيت الصلاة');
        checkAdhanNow(new Date().toTimeString().slice(0,5));
      } else {
        showToast('تعذّر الاتصال بالخادم', 'error');
      }
    });
}

// ─── Notifications ────────────────────────────────────────────────────

function showNotification(text) {
  if ('Notification' in window && Notification.permission === 'granted') {
    new Notification('🕌 نظام الأذان', { body: text });
  }
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
  setTimeout(() => { t.className = 'toast'; }, 4000);
}

// ─── Init ─────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  startClock();
  updateCountdownDisplay();
  updateProgressRing();
  requestNotificationPermission();

  // Set volume
  const vs = document.getElementById('volumeSlider');
  if (vs) {
    vs.value = volume;
    player.volume = volume / 100;
  }

  // Run a check immediately on load
  const now = new Date();
  checkAdhanNow(`${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`);
});
