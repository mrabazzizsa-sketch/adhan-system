/* ─── Settings JS ───────────────────────────────────────────────────── */

const player = document.getElementById('adhanPlayer');

// ─── Save General Settings ────────────────────────────────────────────

function saveGeneralSettings() {
  const data = {
    city: document.getElementById('citySelect').value,
    timezone: document.getElementById('timezoneSelect').value,
    calculation_method: document.getElementById('methodSelect').value,
    notification_before: document.getElementById('notifBefore').value,
  };

  fetch('/api/save-settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
    .then(r => r.json())
    .then(d => {
      if (d.success) {
        showToast('✅ تم حفظ الإعدادات بنجاح');
        // Clear cache & refresh
        fetch('/api/refresh-times', { method: 'POST' });
      } else {
        showToast('حدث خطأ أثناء الحفظ', 'error');
      }
    });
}

// ─── Prayer Adjustments ───────────────────────────────────────────────

function changeAdj(prayer, field, delta) {
  const id = field === 'adjustment' ? `adj-${prayer}` : `iqama-${prayer}`;
  const input = document.getElementById(id);
  if (!input) return;
  let val = parseInt(input.value) + delta;
  if (field === 'adjustment') val = Math.max(-60, Math.min(60, val));
  if (field === 'iqama') val = Math.max(0, Math.min(60, val));
  input.value = val;
}

function saveAdjustments() {
  const prayers = ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha'];
  const data = {};
  prayers.forEach(p => {
    data[p] = {
      adjustment: parseInt(document.getElementById(`adj-${p}`)?.value ?? 0),
      iqama: parseInt(document.getElementById(`iqama-${p}`)?.value ?? 20),
      enabled: document.getElementById(`enabled-${p}`)?.checked ?? true,
    };
  });

  fetch('/api/save-adjustments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
    .then(r => r.json())
    .then(d => {
      if (d.success) showToast('✅ تم حفظ التعديلات');
      else showToast('حدث خطأ', 'error');
    });
}

// ─── Audio Upload ─────────────────────────────────────────────────────

function uploadFile(input, prayer, type) {
  const file = input.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append('file', file);
  formData.append('prayer', prayer);
  formData.append('type', type);

  showToast('⌛ جاري رفع الملف...');

  fetch('/api/upload-audio', { method: 'POST', body: formData })
    .then(r => r.json())
    .then(d => {
      if (d.success) {
        showToast('✅ تم رفع الملف بنجاح');
        setTimeout(() => location.reload(), 1000);
      } else {
        showToast(d.error || 'فشل في رفع الملف', 'error');
      }
    })
    .catch(() => showToast('فشل في رفع الملف', 'error'));
}

// ─── Audio Playback ───────────────────────────────────────────────────

function playAudio(url) {
  player.src = url;
  player.volume = 0.8;
  player.play().catch(e => showToast('تعذّر تشغيل الملف', 'error'));
  showToast('▶ جاري التشغيل...');
}

// ─── Delete File ──────────────────────────────────────────────────────

function deleteFile(id) {
  if (!confirm('هل تريد حذف هذا الملف الصوتي؟')) return;
  fetch('/api/delete-audio', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  })
    .then(r => r.json())
    .then(d => {
      if (d.success) {
        showToast('🗑️ تم حذف الملف');
        setTimeout(() => location.reload(), 800);
      }
    });
}

// ─── Cache Clear ──────────────────────────────────────────────────────

function clearCache() {
  fetch('/api/refresh-times', { method: 'POST' })
    .then(r => r.json())
    .then(d => showToast(d.success ? '✅ تم مسح الكاش وتحديث المواقيت' : 'فشل التحديث', d.success ? 'success' : 'error'));
}

// ─── Toast ────────────────────────────────────────────────────────────

function showToast(msg, type = 'success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show ' + type;
  setTimeout(() => { t.className = 'toast'; }, 3500);
}
