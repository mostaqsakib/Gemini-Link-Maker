//  State 
let socket = null;
let batchCount = 1;
let selectedProviders = ['FirebaseDirect'];
let orders = {};
let savedLinks = [];
let duoLinks = [];
let linkCheckStatus = {};
let linkCheckStats = { live: 0, used: 0, expired: 0, invalid: 0, error: 0, left: 0, total: 0 };
let proxyRows = [];
let proxyResults = {};
let settingsData = {};
let currentDetailOrderId = null;

const PROVIDERS = {
    FirebaseDirect: { name: 'Firebase Direct', service: 'firebase', dotClass: 'dot-jio' },
    OTPSMS: { name: 'OTP SMS', service: 'jio', dotClass: 'dot-uotp' },
    UOTP: { name: 'UOTP', service: 'jio', dotClass: 'dot-uotp' },
    Grizzly: { name: 'Grizzly', service: 'jio', dotClass: 'dot-grizzly' },
    Tiger: { name: 'Tiger SMS', service: 'mjo', dotClass: 'dot-tiger' },
    MeowSMS: { name: 'MeowSMS', service: 'myjio', dotClass: 'dot-meowsms' },
    OTPDoctor: { name: 'OTP Doctor', service: '10549', dotClass: 'dot-otpdoctor' }
};

//  Init 
document.addEventListener('DOMContentLoaded', () => {
    initSocket();
    renderProviders();
    initControls();
    initTabs();
    initModals();
    initMobileUI();
    setTimeout(initAirtelBatch, 800);
});

//  Socket.IO 
function initSocket() {
    socket = io();

    socket.on('connect', () => {
        updateConnectionStatus('connected', 'Connected');
        addLog('Connected to server', 'info');
        socket.emit('get_balances');
        loadSavedLinks();
        loadProxyList();
    });
    socket.on('disconnect', () => {
        updateConnectionStatus('disconnected', 'Disconnected');
        addLog('Disconnected from server', 'error');
    });
    socket.on('balance_update', (data) => {
        for (const [provider, balance] of Object.entries(data)) {
            const el = document.getElementById(`balance-${provider}`);
            if (el) {
                el.textContent = balance !== null ? `${parseFloat(balance).toFixed(2)}` : 'Error';
                el.classList.remove('loading');
            }
        }
    });
    socket.on('order_update', (data) => {
        orders[data.id] = data;
        updateTopStats();
        if (data.status === 'logged_in') {
            addLog(` Successfully logged into ${data.phone} (${data.provider})!`, 'success');
        } else if (data.status === 'cancelled') {
            addLog(` Cancelled ${data.phone} (${data.provider})`, 'error');
        }
        if (document.getElementById('tab-orders').classList.contains('active')) {
            renderOrders();
        }
        if (document.getElementById('tab-display')?.classList.contains('active')) renderProcessDisplay();
    });

    socket.on('omkar_gen_log', (data) => {
        const c = document.getElementById('omkarGenLog');
        if (!c) return;
        const e = c.querySelector('.log-empty');
        if (e) e.remove();
        const el = document.createElement('div');
        el.className = `log-entry log-${data.level || 'info'}`;

        // Highlight emails with a pill-like style if they exist
        let htmlMsg = data.msg.replace(/\[([a-zA-Z0-9._-]+@[a-zA-Z0-9._-]+\.[a-zA-Z0-9_-]+)\]/g, '<span class="log-email">$1</span>');

        el.innerHTML = `<span class="log-time">${new Date().toLocaleTimeString()}</span> <span class="log-msg">${htmlMsg}</span>`;
        c.insertBefore(el, c.firstChild);
    });
    socket.on('number_update', (data) => {
        orders[data.id] = data;
        renderOrders();
        if (document.getElementById('tab-display')?.classList.contains('active')) renderProcessDisplay();
        if (currentDetailOrderId === data.id && !document.getElementById('orderDetailModal')?.classList.contains('hidden')) {
            openOrderDetail(data);
        }
        updateTopStats();
    });
    socket.on('number_remove', (data) => {
        delete orders[data.id];
        renderOrders();
        if (document.getElementById('tab-display')?.classList.contains('active')) renderProcessDisplay();
        if (currentDetailOrderId === data.id) {
            currentDetailOrderId = null;
            document.getElementById('orderDetailModal')?.classList.add('hidden');
        }
        updateTopStats();
    });
    socket.on('stats_update', (data) => {
        const statFetched = document.getElementById('statFetched');
        const statJio = document.getElementById('statJio');
        const statOtp = document.getElementById('statOtp');
        const statLogin = document.getElementById('statLogin');
        if (statFetched) statFetched.textContent = data.fetched || 0;
        if (statJio) statJio.textContent = data.jio || 0;
        if (statOtp) statOtp.textContent = data.otp || 0;
        if (statLogin) statLogin.textContent = data.login || 0;

        // OTP wait time display
        const otpAvgEl = document.getElementById('statOtpAvg');
        if (otpAvgEl && data.otp_avg && data.otp_avg > 0) {
            otpAvgEl.textContent = `${data.otp_avg}s`;
            otpAvgEl.title = `Min: ${data.otp_min}s | Max: ${data.otp_max}s | Count: ${data.otp_count}`;
        } else if (otpAvgEl) {
            otpAvgEl.textContent = '';
        }
    });
    socket.on('log', (data) => {
        addLog(data.message, data.level || 'info');
    });
    socket.on('link_stats', (data) => {
        updateLinkCounters(data.count || 0);
    });
    socket.on('link_saved', (data) => {
        if (data.link && !savedLinks.includes(data.link)) savedLinks.unshift(data.link);
        updateLinkCounters(data.count || savedLinks.length);
        if (document.getElementById('tab-links')?.classList.contains('active')) renderSavedLinks();
    });

    // ── Airtel Duolingo events ──────────────────────────────────────────────
    socket.on('duolingo_link_saved', (data) => {
        if (data.link && !duoLinks.includes(data.link)) duoLinks.unshift(data.link);
        updateDuoCount(data.count || duoLinks.length);
        if (document.getElementById('tab-airtel')?.classList.contains('active')) renderDuoLinks();
        addLog(`🦉 Duolingo link saved: ${data.phone}`, 'success');
    });

    socket.on('airtel_links_data', (data) => {
        duoLinks = data.links || [];
        updateDuoCount(data.count || duoLinks.length);
        renderDuoLinks();
    });

    socket.on('airtel_batch_status', (data) => {
        const startBtn = document.getElementById('startAirtelBatch');
        const stopBtn  = document.getElementById('stopAirtelBatch');
        if (startBtn) startBtn.disabled = !!data.running;
        if (stopBtn)  stopBtn.disabled  = !data.running;
    });

    socket.on('airtel_concurrency_updated', (data) => {
        const el = document.getElementById('airtelConcurrency');
        if (el) el.value = data.concurrency;
        addLog(`🔧 Airtel concurrency → ${data.concurrency}`, 'info');
    });

    socket.on('airtel_batch_progress', (data) => {
        const bar  = document.getElementById('airtelProgressBar');
        const fill = document.getElementById('airtelProgressFill');
        const txt  = document.getElementById('airtelProgressText');
        const eta  = document.getElementById('airtelETA');
        if (!bar) return;
        bar.style.display = 'block';
        const pct = data.total > 0 ? Math.round((data.checked / data.total) * 100) : 0;
        if (fill) fill.style.width = pct + '%';
        if (txt)  txt.textContent  = `Checking ${data.checked} / ${data.total} (${pct}%)`;
        if (eta)  eta.textContent  = data.eta_minutes > 0 ? `ETA ~${data.eta_minutes}m | ${data.tpm} TPM` : '';
    });

    socket.on('batch_progress', (data) => {
        if (document.getElementById('progTotal')) {
            document.getElementById('progTotal').textContent = data.total;
            document.getElementById('progChecked').textContent = data.checked;
            document.getElementById('progRemaining').textContent = data.remaining;
            document.getElementById('progTPM').textContent = data.tpm;
            document.getElementById('progETA').textContent = data.eta;

            const pct = data.total > 0 ? (data.checked / data.total) * 100 : 0;
            const progBar = document.getElementById('progBar');
            if (progBar) progBar.style.width = pct + '%';
            const statTotal = document.getElementById('statTotal');
            const statChecked = document.getElementById('statChecked');
            const statLeft = document.getElementById('statLeft');
            if (statTotal) statTotal.textContent = data.total || 0;
            if (statChecked) statChecked.textContent = data.checked || 0;
            if (statLeft) statLeft.textContent = data.remaining || 0;
        }
    });
    socket.on('sniping_started', () => {
        document.getElementById('startBtn').classList.add('hidden');
        document.getElementById('pauseBtn').classList.remove('hidden');
        document.getElementById('resumeBtn').classList.add('hidden');
        document.getElementById('stopBtn').classList.remove('hidden');
        document.getElementById('forceStopBtn').classList.add('hidden');
        document.getElementById('pauseBanner').classList.add('hidden');
        updateConnectionStatus('sniping', 'Sniping...');
        mobileSetSniping(true);
    });
    socket.on('sniping_stopped', () => {
        document.getElementById('startBtn').classList.remove('hidden');
        document.getElementById('pauseBtn').classList.add('hidden');
        document.getElementById('resumeBtn').classList.add('hidden');
        document.getElementById('stopBtn').classList.add('hidden');
        document.getElementById('forceStopBtn').classList.add('hidden');
        document.getElementById('pauseBanner').classList.add('hidden');
        updateConnectionStatus('connected', 'Connected');
        mobileSetSniping(false);
    });
    socket.on('sniping_paused', (data) => {
        document.getElementById('pauseBtn').classList.add('hidden');
        document.getElementById('resumeBtn').classList.remove('hidden');
        document.getElementById('stopBtn').classList.remove('hidden');
        document.getElementById('forceStopBtn').classList.add('hidden');
        const banner = document.getElementById('pauseBanner');
        if (data && data.reason) {
            banner.textContent = ' ' + data.reason;
            banner.classList.remove('hidden');
        }
        updateConnectionStatus('connected', 'Paused');
    });
    socket.on('sniping_resumed', () => {
        document.getElementById('pauseBtn').classList.remove('hidden');
        document.getElementById('resumeBtn').classList.add('hidden');
        document.getElementById('stopBtn').classList.remove('hidden');
        document.getElementById('forceStopBtn').classList.add('hidden');
        document.getElementById('pauseBanner').classList.add('hidden');
        updateConnectionStatus('sniping', 'Sniping...');
    });

    // System stats
    socket.on('system_stats', (data) => {
        updateGauge('cpu', data.cpu);
        updateGauge('ram', data.ram_percent);
        if (data.omkar_data) {
            renderOmkarSidebar(data.omkar_data);
        }
        const browsersOpen = document.getElementById('browsersOpen');
        if (browsersOpen) browsersOpen.textContent = data.browsers_open || 0;
    });

    // Settings
    socket.on('settings_data', (data) => {
        settingsData = data;
        renderSettings();
    });
    socket.on('settings_saved', () => addLog('Settings saved successfully', 'success'));

    // Analytics

    // Order detail
    socket.on('order_detail', (data) => openOrderDetail(data));
}

//  Gauges 
function updateGauge(type, value) {
    const fill = document.getElementById(`${type}Fill`);
    const valEl = document.getElementById(`${type}Value`);
    if (!fill || !valEl) return;

    const v = Math.min(100, Math.max(0, value));
    fill.setAttribute('stroke-dasharray', `${v}, 100`);
    valEl.textContent = Math.round(v);

    // Color shift based on load
    let color;
    if (v < 50) color = type === 'cpu' ? '#06b6d4' : '#8b5cf6';
    else if (v < 80) color = '#f59e0b';
    else color = '#ef4444';
    fill.style.stroke = color;
}

function renderOmkarSidebar(omkarData) {
    const container = document.getElementById('omkarKeysListWidget');
    if (!container) return;

    if (omkarData.length === 0) {
        container.innerHTML = '<div class="log-empty">No keys configured.</div>';
        return;
    }

    let html = '';
    omkarData.forEach((k, idx) => {
        const usage = k.usage;
        const max = k.max || 200;
        const pct = Math.min(100, Math.max(0, (usage / max) * 100));
        const remain = max - usage;

        let color, desc;
        if (pct < 50) { color = '#22c55e'; desc = `${remain} left`; }
        else if (pct < 80) { color = '#f59e0b'; desc = `${remain} left`; }
        else if (pct < 100) { color = '#ef4444'; desc = 'Low'; }
        else { color = '#dc2626'; desc = 'Exhausted'; }

        html += `
        <div class="omkar-key-item">
            <div class="omkar-key-info">
                <div class="omkar-key-label">${k.label}</div>
                <div class="omkar-key-desc" style="color: ${color}">${desc}</div>
            </div>
            <div class="gauge gauge-mini" title="${usage}/${max} Used">
                <svg viewBox="0 0 36 36" class="gauge-svg">
                    <path class="gauge-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"/>
                    <path class="gauge-fill" stroke-dasharray="${pct}, 100" style="stroke: ${color};" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"/>
                </svg>
                <div class="gauge-label"><span class="gauge-value" style="color: ${color}">${usage}</span></div>
            </div>
        </div>
        `;
    });

    container.innerHTML = html;
}

//  Providers 
function renderProviders() {
    const container = document.getElementById('providerList');
    container.innerHTML = '';
    for (const [key, prov] of Object.entries(PROVIDERS)) {
        const selected = selectedProviders.includes(key);
        const card = document.createElement('div');
        card.className = `provider-card ${selected ? 'selected' : ''}`;
        card.dataset.provider = key;
        card.innerHTML = `
            <div class="provider-checkbox"></div>
            <div class="provider-info">
                <div class="provider-name">${prov.name}</div>
                <div class="provider-service">Service: ${prov.service}  India</div>
            </div>
            <div class="provider-balance loading" id="balance-${key}">Loading...</div>
        `;
        card.addEventListener('click', () => {
            const idx = selectedProviders.indexOf(key);
            if (idx > -1) { selectedProviders.splice(idx, 1); card.classList.remove('selected'); }
            else { selectedProviders.push(key); card.classList.add('selected'); }
        });
        container.appendChild(card);
    }
}

//  Controls 
function initControls() {
    let otpDelay = 4;
    let scanMode = 'deep';

    document.getElementById('countDown').addEventListener('click', () => {
        batchCount = Math.max(1, parseInt(document.getElementById('batchCount').value)||1);
        if (batchCount > 1) batchCount--;
        document.getElementById('batchCount').value = batchCount;
    });
    document.getElementById('countUp').addEventListener('click', () => {
        batchCount = Math.min(1000, parseInt(document.getElementById('batchCount').value)||1);
        if (batchCount < 1000) batchCount++;
        document.getElementById('batchCount').value = batchCount;
    });

    document.getElementById('delayDown').addEventListener('click', () => {
        if (otpDelay > 0) otpDelay--;
        document.getElementById('otpDelayDisplay').textContent = otpDelay;
    });
    document.getElementById('delayUp').addEventListener('click', () => {
        if (otpDelay < 60) otpDelay++;
        document.getElementById('otpDelayDisplay').textContent = otpDelay;
    });

    document.querySelectorAll('.scan-mode-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.scan-mode-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            scanMode = btn.dataset.scan;
        });
    });
    document.getElementById('startBtn').addEventListener('click', () => {
        if (selectedProviders.length === 0) { addLog('Select at least one provider!', 'error'); return; }
        const headlessMode = document.getElementById('headlessToggle').checked;
        batchCount = Math.min(1000, Math.max(1, parseInt(document.getElementById('batchCount').value)||1));
        socket.emit('start_sniping', { providers: selectedProviders, batch_size: batchCount, scan_mode: scanMode, headless: headlessMode, otp_delay: otpDelay });
    });
    document.getElementById('pauseBtn').addEventListener('click', () => {
        socket.emit('pause_sniping');
    });
    document.getElementById('resumeBtn').addEventListener('click', () => {
        socket.emit('resume_sniping');
    });
    document.getElementById('stopBtn').addEventListener('click', () => {
        socket.emit('stop_sniping');
        document.getElementById('stopBtn').classList.add('hidden');
        document.getElementById('pauseBtn').classList.add('hidden');
        document.getElementById('resumeBtn').classList.add('hidden');
        document.getElementById('forceStopBtn').classList.remove('hidden');
    });
    document.getElementById('forceStopBtn').addEventListener('click', () => {
        socket.emit('force_stop_sniping');
        document.getElementById('forceStopBtn').textContent = "🛑 Force Stopping...";
        document.getElementById('forceStopBtn').disabled = true;
    });
    const clearLogBtn = document.getElementById('clearLog');
    if (clearLogBtn) {
        clearLogBtn.addEventListener('click', () => {
            document.getElementById('logContainer').innerHTML = '<div class="log-empty">No activity yet...</div>';
        });
    }
    document.getElementById('refreshDisplay')?.addEventListener('click', renderProcessDisplay);
    document.getElementById('refreshSavedLinks')?.addEventListener('click', loadSavedLinks);
    document.getElementById('refreshCheckedLinks')?.addEventListener('click', loadCheckedLinks);
    document.getElementById('refreshProxyList')?.addEventListener('click', loadProxyList);
    document.getElementById('checkAllProxies')?.addEventListener('click', checkAllProxies);
    document.getElementById('checkAllSavedLinks')?.addEventListener('click', e => checkLinksNow(savedLinks, e.currentTarget));
    document.getElementById('checkAllCheckedLinks')?.addEventListener('click', e => checkLinksNow(checkedLinks, e.currentTarget));
    document.getElementById('copyAllSavedLinks')?.addEventListener('click', () => {
        if (!savedLinks.length) return;
        navigator.clipboard.writeText(savedLinks.join('\n'));
        addLog(`Copied ${savedLinks.length} saved links`, 'success');
    });
    document.getElementById('downloadAndClearLinks')?.addEventListener('click', async () => {
        if (!savedLinks.length) { addLog('No links to download', 'warn'); return; }
        const btn = document.getElementById('downloadAndClearLinks');
        btn.disabled = true;
        btn.textContent = '⏳ Downloading...';
        // Download as .txt file
        const blob = new Blob([savedLinks.join('\n')], { type: 'text/plain' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `gemini_links_${new Date().toISOString().slice(0,19).replace(/[:T]/g,'-')}.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(a.href);
        // Confirm before clearing
        if (confirm(`Downloaded ${savedLinks.length} links. Clear them from server now?`)) {
            try {
                const resp = await fetch('/api/clear-links', { method: 'POST' });
                const data = await resp.json();
                if (data.ok) {
                    savedLinks = [];
                    updateLinkCounters(0);
                    renderSavedLinks();
                    addLog(`✅ Downloaded & cleared ${data.cleared} links`, 'success');
                } else {
                    addLog(`Clear failed: ${data.error}`, 'error');
                }
            } catch(e) {
                addLog(`Clear request failed: ${e.message}`, 'error');
            }
        }
        btn.disabled = false;
        btn.textContent = '⬇️ Download & Clear';
    });
    document.getElementById('copyAllCheckedLinks')?.addEventListener('click', () => {
        if (!checkedLinks.length) return;
        navigator.clipboard.writeText(checkedLinks.join('\n'));
        addLog(`Copied ${checkedLinks.length} checked links`, 'success');
    });
    document.getElementById('killZombieBtn').addEventListener('click', () => {
        socket.emit('kill_zombie_browsers');
        const btn = document.getElementById('killZombieBtn');
        const originalText = btn.innerHTML;
        btn.innerHTML = '<span class="btn-icon-left">🧹</span> Killing...';
        btn.disabled = true;
        setTimeout(() => {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }, 3000);
    });
    document.getElementById('refreshBalances').addEventListener('click', () => {
        document.querySelectorAll('.provider-balance').forEach(el => { el.textContent = 'Loading...'; el.classList.add('loading'); });
        socket.emit('get_balances');
    });
    document.getElementById('refreshOrders').addEventListener('click', () => socket.emit('get_orders'));


}

//  Tabs 
function initTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            const tab = document.getElementById(`tab-${btn.dataset.tab}`);
            if (tab) tab.classList.add('active');
            if (btn.dataset.tab === 'display') renderProcessDisplay();
            if (btn.dataset.tab === 'links') loadSavedLinks();
            if (btn.dataset.tab === 'proxies') loadProxyList();
            if (btn.dataset.tab === 'airtel') loadDuoLinks();
        });
    });
}

//  Modals 
function initModals() {
    // Settings
    document.getElementById('openSettings').addEventListener('click', () => {
        socket.emit('get_settings');
        document.getElementById('settingsModal').classList.remove('hidden');
    });
    document.getElementById('closeSettings').addEventListener('click', () => {
        document.getElementById('settingsModal').classList.add('hidden');
    });
    document.getElementById('saveSettings').addEventListener('click', saveSettings);
    document.querySelectorAll('.modal-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.modal-tab').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.modal-tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(`mtab-${btn.dataset.mtab}`).classList.add('active');
        });
    });
    document.getElementById('addOmkarKey').addEventListener('click', () => {
        addOmkarKeyRow('');
    });

    // Order detail
    document.getElementById('closeDetail').addEventListener('click', () => {
        currentDetailOrderId = null;
        document.getElementById('orderDetailModal').classList.add('hidden');
    });

    // Close modals on overlay click
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) overlay.classList.add('hidden');
        });
    });
    // Retry OTP Timeouts
    document.getElementById('retryOtpTimeoutsBtn').addEventListener('click', async () => {
        if (!confirm('Remove all "Timed out waiting for Firebase OTP" devices from used list so they can be retried?')) return;

        const btn = document.getElementById('retryOtpTimeoutsBtn');
        const originalText = btn.innerHTML;
        btn.innerHTML = '<span class="btn-icon-left">Run</span> Processing...';
        btn.disabled = true;
        btn.style.opacity = '0.6';

        try {
            const resp = await fetch('/api/retry_otp_timeouts', { method: 'POST' });
            const data = await resp.json();

            if (data.error) {
                alert(' Error: ' + data.error);
            } else {
                alert(` ${data.message}\n\nUnique timeout IDs: ${data.unique_timeout_ids}\nRemoved from used list: ${data.removed}\nRemaining used devices: ${data.remaining}`);
            }
        } catch (e) {
            alert(' Request failed: ' + e.message);
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
            btn.style.opacity = '1';
        }
    });

    // Link Checker

    document.getElementById('startLinkCheck').addEventListener('click', () => {
        const input = document.getElementById('linkCheckerInput').value.trim();
        const links = input ? input.split('\n').map(l => l.trim()).filter(l => l.startsWith('http')) : [];

        // Clear previous results
        document.getElementById('linkCheckLog').innerHTML = '';
        document.getElementById('validLinksOutput').value = '';
        document.getElementById('validLinkCount').textContent = '0';
        document.getElementById('linkCheckResults').style.display = 'none';
        document.getElementById('linkCheckProgress').textContent = '';
        window._validLinks = [];
        window._linkCheckTotal = 0;
        window._linkCheckDone = 0;

        document.getElementById('startLinkCheck').classList.add('hidden');
        document.getElementById('stopLinkCheck').classList.remove('hidden');

        socket.emit('check_links', { links: links, use_csv: links.length === 0 });
    });
    document.getElementById('loginLinkChecker').addEventListener('click', () => {
        socket.emit('link_checker_login');
        document.getElementById('linkCheckLog').innerHTML = '';
        const entry = document.createElement('div');
        entry.className = 'log-entry';
        entry.style.color = '#60a5fa';
        entry.textContent = 'Opening Google login browser. Complete login there, then close that browser.';
        document.getElementById('linkCheckLog').appendChild(entry);
    });
    document.getElementById('loginTgChecker').addEventListener('click', () => {
        document.getElementById('linkCheckLog').innerHTML = '';
        addTgCheckerLog('Starting Telegram login...', 'info');
        socket.emit('tg_checker_send_code');
    });
    document.getElementById('verifyTgChecker').addEventListener('click', () => {
        socket.emit('tg_checker_verify', {
            code: document.getElementById('tgLoginCode').value.trim(),
            password: document.getElementById('tgLoginPassword').value
        });
    });
    document.getElementById('startTgCheck').addEventListener('click', () => {
        const input = document.getElementById('linkCheckerInput').value.trim();
        const links = input ? input.split('\n').map(l => l.trim()).filter(l => l.startsWith('http')) : [];
        startTelegramLinkCheck(
            links,
            document.getElementById('startTgCheck'),
            links.length ? `Sending ${links.length} pasted links to Telegram checker...` : 'Sending extracted_links.csv to Telegram checker...'
        );
    });
    document.getElementById('stopLinkCheck').addEventListener('click', () => {
        socket.emit('stop_link_check');
        document.getElementById('stopLinkCheck').classList.add('hidden');
        document.getElementById('startLinkCheck').classList.remove('hidden');
    });
    document.getElementById('copyValidLinks').addEventListener('click', () => {
        const text = document.getElementById('validLinksOutput').value;
        navigator.clipboard.writeText(text).then(() => {
            const btn = document.getElementById('copyValidLinks');
            btn.textContent = 'Copied!';
            setTimeout(() => { btn.textContent = '📋 Copy Valid Links'; }, 2000);
        });
    });

    // Socket listeners for link checker
    socket.on('link_check_log', (data) => {
        const log = document.getElementById('linkCheckLog');
        const entry = document.createElement('div');
        entry.className = 'log-entry';
        const colors = { VALID: '#10b981', USED: '#ef4444', ERROR: '#f59e0b', UNKNOWN: '#6b7280', info: '#60a5fa' };
        entry.style.color = colors[data.level] || 'var(--text-2)';
        entry.textContent = data.msg;
        log.appendChild(entry);
        log.scrollTop = log.scrollHeight;
    });
    socket.on('link_check_result', (data) => {
        window._linkCheckDone = (window._linkCheckDone || 0) + 1;
        const total = window._linkCheckTotal || '?';
        document.getElementById('linkCheckProgress').textContent = `${window._linkCheckDone}/${total}`;

        if (data.status === 'VALID') {
            window._validLinks = window._validLinks || [];
            window._validLinks.push(data.link);
            document.getElementById('validLinksOutput').value = window._validLinks.join('\n');
            document.getElementById('validLinkCount').textContent = window._validLinks.length;
            document.getElementById('linkCheckResults').style.display = 'block';
        }
    });
    socket.on('link_check_total', (data) => {
        window._linkCheckTotal = data.total;
        document.getElementById('linkCheckProgress').textContent = `0/${data.total}`;
    });
    socket.on('link_check_done', (data) => {
        document.getElementById('stopLinkCheck').classList.add('hidden');
        document.getElementById('startLinkCheck').classList.remove('hidden');
        document.getElementById('linkCheckProgress').textContent = `Done! ${data.valid} ${data.used} ${data.errors}`;
        if (window._validLinks && window._validLinks.length > 0) {
            document.getElementById('linkCheckResults').style.display = 'block';
        }
    });
    socket.on('tg_checker_log', data => addTgCheckerLog(data.msg, data.level));
    socket.on('tg_checker_code_needed', () => {
        document.getElementById('tgLoginBox').classList.remove('hidden');
        document.getElementById('linkCheckProgress').textContent = 'Enter TG code';
    });
    socket.on('tg_checker_password_needed', () => {
        document.getElementById('tgLoginBox').classList.remove('hidden');
        document.getElementById('tgLoginPassword').focus();
    });
    socket.on('tg_checker_login_status', data => {
        if (data.authorized) {
            document.getElementById('tgLoginBox').classList.add('hidden');
            document.getElementById('linkCheckProgress').textContent = 'TG logged in';
        }
    });
    socket.on('tg_checker_stats', data => {
        linkCheckStats = {
            live: data.valid || 0,
            used: data.used || 0,
            expired: data.expired || 0,
            invalid: data.invalid || 0,
            error: data.error || 0,
            left: data.left || 0,
            total: data.total || 0
        };
        updateLinkCheckSummary();
        document.getElementById('linkCheckProgress').textContent =
            `Live ${linkCheckStats.live} | Used ${linkCheckStats.used} | Exp ${linkCheckStats.expired} | Inv ${linkCheckStats.invalid} | Err ${linkCheckStats.error} | Left ${linkCheckStats.left}`;
    });
    socket.on('tg_checker_category', data => {
        const statusMap = { valid: 'VALID', used: 'USED', expired: 'EXPIRED', invalid: 'INVALID', error: 'ERROR' };
        const status = statusMap[data.category] || 'UNKNOWN';
        (data.links || []).forEach(link => {
            linkCheckStatus[link] = status;
            if (status === 'VALID' && !checkedLinks.includes(link)) checkedLinks.unshift(link);
        });
        renderVisibleLinkTabs();
        updateCheckedLinkCounters(checkedLinks.length);
    });
    socket.on('tg_checker_done', data => {
        document.getElementById('startTgCheck').disabled = false;
        restoreTgCheckButton();
        document.getElementById('linkCheckProgress').textContent =
            `TG Done! Valid ${data.valid || 0} | Used ${data.used || 0} | Exp ${data.expired || 0} | Inv ${data.invalid || 0} | Err ${data.error || 0}`;
        window._validLinks = data.valid_links || [];
        document.getElementById('validLinksOutput').value = window._validLinks.join('\n');
        document.getElementById('validLinkCount').textContent = window._validLinks.length;
        document.getElementById('linkCheckResults').style.display = window._validLinks.length ? 'block' : 'none';
        markTgLinks(data.valid_links, 'VALID');
        markTgLinks(data.used_links, 'USED');
        markTgLinks(data.expired_links, 'EXPIRED');
        markTgLinks(data.invalid_links, 'INVALID');
        markTgLinks(data.error_links, 'ERROR');
        checkedLinks = [...new Set([...(data.valid_links || []), ...checkedLinks])];
        updateCheckedLinkCounters(checkedLinks.length);
        renderVisibleLinkTabs();
    });
    //  APK / Link Extractor 
    document.getElementById('openApkExtractorModal').addEventListener('click', () => {
        document.getElementById('apkExtractorModal').classList.remove('hidden');
    });
    document.getElementById('closeApkExtractorModal').addEventListener('click', () => {
        document.getElementById('apkExtractorModal').classList.add('hidden');
    });
    document.getElementById('cancelApkExtractorModal').addEventListener('click', () => {
        document.getElementById('apkExtractorModal').classList.add('hidden');
    });

    window._apkNewUrls = [];
    window._apkAllUrls = [];

    function apkLog(msg, color) {
        const log = document.getElementById('apkExtractorLog');
        if (log.querySelector('.log-empty')) log.innerHTML = '';
        const entry = document.createElement('div');
        entry.className = 'log-entry';
        entry.style.color = color || 'var(--text-2)';
        entry.textContent = msg;
        log.appendChild(entry);
        log.scrollTop = log.scrollHeight;
    }

    function updateApkSummary(newCount, dupCount) {
        const summary = document.getElementById('apkExtractorSummary');
        summary.style.display = 'block';
        const prevNew = parseInt(document.getElementById('apkNewCount').textContent) || 0;
        const prevDup = parseInt(document.getElementById('apkDupCount').textContent) || 0;
        const totalNew = prevNew + newCount;
        const totalDup = prevDup + dupCount;
        document.getElementById('apkNewCount').textContent = totalNew;
        document.getElementById('apkDupCount').textContent = totalDup;
        document.getElementById('apkTotalCount').textContent = totalNew + totalDup;
    }

    // APK Drop Zone
    const dropZone = document.getElementById('apkDropZone');
    const fileInput = document.getElementById('apkFileInput');

    dropZone.addEventListener('click', () => fileInput.click());
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.style.borderColor = '#8b5cf6';
        dropZone.style.background = 'rgba(139, 92, 246, 0.1)';
    });
    dropZone.addEventListener('dragleave', () => {
        dropZone.style.borderColor = 'var(--border-2)';
        dropZone.style.background = 'var(--bg-2)';
    });
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.style.borderColor = 'var(--border-2)';
        dropZone.style.background = 'var(--bg-2)';
        handleApkFiles(e.dataTransfer.files);
    });
    fileInput.addEventListener('change', () => handleApkFiles(fileInput.files));

    async function handleApkFiles(files) {
        for (const file of files) {
            if (!file.name.toLowerCase().endsWith('.apk')) {
                apkLog(` Skipped ${file.name} (not an APK)`, '#f59e0b');
                continue;
            }
            apkLog(` Processing ${file.name}...`, '#60a5fa');
            const formData = new FormData();
            formData.append('file', file);
            try {
                const resp = await fetch('/api/extract_apk', { method: 'POST', body: formData });
                const data = await resp.json();
                if (data.message) {
                    apkLog(`   ${file.name}: ${data.message}`, '#ef4444');
                } else {
                    for (const u of (data.urls || [])) {
                        const label = u.duplicate ? ' DUP' : ' NEW';
                        const color = u.duplicate ? '#f59e0b' : '#22c55e';
                        const shortUrl = u.url.split('//')[1].split('.')[0];
                        apkLog(`  ${label}: ${shortUrl}`, color);
                        window._apkAllUrls.push(u.url);
                        if (!u.duplicate) window._apkNewUrls.push(u.url);
                    }
                    updateApkSummary(data.new_count || 0, data.dup_count || 0);
                }
            } catch (err) {
                apkLog(`   Error: ${err.message}`, '#ef4444');
            }
        }
    }

    // Profex Link Decoder
    document.getElementById('decodeProfexBtn').addEventListener('click', async () => {
        const input = document.getElementById('profexLinkInput').value.trim();
        if (!input) { apkLog(' Paste some links first!', '#f59e0b'); return; }
        apkLog(' Decoding links...', '#60a5fa');
        try {
            const resp = await fetch('/api/decode_links', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ links: input })
            });
            const data = await resp.json();
            for (const r of (data.results || [])) {
                if (r.error) {
                    apkLog(`   ${r.error}: ${r.input || ''}`, '#ef4444');
                } else {
                    const label = r.duplicate ? ' DUP' : ' NEW';
                    const color = r.duplicate ? '#f59e0b' : '#22c55e';
                    const shortUrl = r.url.split('//')[1].split('.')[0];
                    apkLog(`  ${label}: ${shortUrl}`, color);
                    window._apkAllUrls.push(r.url);
                    if (!r.duplicate) window._apkNewUrls.push(r.url);
                }
            }
            updateApkSummary(data.new_count || 0, data.dup_count || 0);
            document.getElementById('profexLinkInput').value = '';
        } catch (err) {
            apkLog(`   Error: ${err.message}`, '#ef4444');
        }
    });

    // Copy buttons
    document.getElementById('copyNewUrls').addEventListener('click', () => {
        const unique = [...new Set(window._apkNewUrls)];
        if (!unique.length) { apkLog('No new URLs to copy!', '#f59e0b'); return; }
        navigator.clipboard.writeText(unique.join('\n')).then(() => {
            const btn = document.getElementById('copyNewUrls');
            btn.textContent = `Copied ${unique.length}!`;
            setTimeout(() => { btn.textContent = '📋 Copy New URLs'; }, 2000);
        });
    });
    document.getElementById('copyAllUrls').addEventListener('click', () => {
        const unique = [...new Set(window._apkAllUrls)];
        if (!unique.length) { apkLog('No URLs to copy!', '#f59e0b'); return; }
        navigator.clipboard.writeText(unique.join('\n')).then(() => {
            const btn = document.getElementById('copyAllUrls');
            btn.textContent = `Copied ${unique.length}!`;
            setTimeout(() => { btn.textContent = '📋 Copy All URLs'; }, 2000);
        });
    });
}

//  Settings 
function renderSettings() {
    // Provider keys
    const provContainer = document.getElementById('providerSettings');
    provContainer.innerHTML = '';
    const providers = settingsData.providers || {};
    for (const [key, cfg] of Object.entries(providers)) {
        const card = document.createElement('div');
        card.className = 'provider-setting-card';
        card.innerHTML = `
            <div class="provider-setting-name">${key}</div>
            <div class="setting-group">
                <label>API Key <button class="key-toggle" data-field="key-${key}"> Show</button></label>
                <input type="password" class="setting-input" id="key-${key}" value="${cfg.key || ''}" data-provider="${key}" data-field="key">
            </div>
            <div class="setting-group">
                <label>URL</label>
                <input type="text" class="setting-input" id="url-${key}" value="${cfg.url || ''}" data-provider="${key}" data-field="url">
            </div>
            <div class="setting-group">
                <label>Service / Country / Delay</label>
                <div class="setting-input-row">
                    <input type="text" class="setting-input" id="svc-${key}" value="${cfg.service || ''}" data-provider="${key}" data-field="service" placeholder="Service">
                    <input type="text" class="setting-input" id="cty-${key}" value="${cfg.country || ''}" data-provider="${key}" data-field="country" placeholder="Country" style="width:80px">
                    <input type="number" class="setting-input" id="dly-${key}" value="${cfg.delay || 3}" data-provider="${key}" data-field="delay" placeholder="Delay" style="width:80px">
                </div>
            </div>
        `;
        provContainer.appendChild(card);
    }

    // Key toggle listeners
    document.querySelectorAll('.key-toggle').forEach(btn => {
        btn.addEventListener('click', () => {
            const input = document.getElementById(btn.dataset.field);
            if (input.type === 'password') { input.type = 'text'; btn.textContent = '🙈 Hide'; }
            else { input.type = 'password'; btn.textContent = '👁️ Show'; }
        });
    });

    // Omkar keys
    const omkarList = document.getElementById('omkarKeysList');
    omkarList.innerHTML = '';
    (settingsData.omkar_keys || []).forEach(k => addOmkarKeyRow(k));

    // Firebase DB rows (URL + Key pairs)
    const firebaseDbList = document.getElementById('firebaseDbList');
    if (firebaseDbList) {
        firebaseDbList.innerHTML = '';
        const dbs = settingsData.firebase_dbs || [];
        if (dbs.length > 0) {
            dbs.forEach(db => addFirebaseDbRow(db.url || '', db.key || ''));
        } else {
            (settingsData.firebase_urls || []).forEach(url => addFirebaseDbRow(url, ''));
        }
        if (firebaseDbList.children.length === 0) addFirebaseDbRow('', '');
    }

    // Proxies (Textarea)
    const proxiesTextarea = document.getElementById('proxiesTextarea');
    if (proxiesTextarea) {
        proxiesTextarea.value = (settingsData.proxies || []).join('\n');
    }

    // Telegram checker + monitor
    const tg = settingsData.tg_checker || settingsData.tg_monitor || {};
    const tgApiId = document.getElementById('tgApiId');
    const tgApiHash = document.getElementById('tgApiHash');
    const tgPhone = document.getElementById('tgPhone');
    if (tgApiId) tgApiId.value = tg.api_id || '';
    if (tgApiHash) tgApiHash.value = tg.api_hash || '';
    if (tgPhone) tgPhone.value = tg.phone || '';
    const tgChannel = document.getElementById('tgMonitorChannel');
    if (tgChannel) tgChannel.value = (settingsData.tg_monitor || {}).channel || '';

    // Timing
    const timing = settingsData.timing || {};
    document.getElementById('settingPollInterval').value = timing.otp_poll_interval || 3;
    document.getElementById('settingCancelWait').value = timing.cancel_wait_seconds || 45;
    document.getElementById('settingMaxAttempts').value = timing.max_otp_attempts || 60;
}

function addFirebaseDbRow(url, key) {
    const list = document.getElementById('firebaseDbList');
    const row = document.createElement('div');
    row.className = 'setting-input-row';
    row.style.cssText = 'display:flex;gap:6px;align-items:center;';
    row.innerHTML = `
        <input type="text" class="setting-input firebase-db-url" value="${url}" placeholder="https://project-default-rtdb.firebaseio.com" style="flex:2;">
        <input type="text" class="setting-input firebase-db-key" value="${key}" placeholder="Auth Key (optional)" style="flex:1;">
        <button class="btn-remove-key" onclick="this.parentElement.remove()"></button>
    `;
    list.appendChild(row);
}

function addOmkarKeyRow(value) {
    const list = document.getElementById('omkarKeysList');
    const row = document.createElement('div');
    row.className = 'setting-input-row';
    row.innerHTML = `
        <input type="password" class="setting-input omkar-key-input" value="${value}" placeholder="ok_...">
        <button class="key-toggle" onclick="this.previousElementSibling.type = this.previousElementSibling.type === 'password' ? 'text' : 'password'"></button>
        <button class="btn-remove-key" onclick="this.parentElement.remove()"></button>
    `;
    list.appendChild(row);
}

function addTgCheckerLog(msg, level = 'info') {
    const log = document.getElementById('linkCheckLog');
    if (!log) return;
    if (log.querySelector('.log-empty')) log.innerHTML = '';
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    const colors = {
        success: '#10b981',
        error: '#ef4444',
        warn: '#f59e0b',
        info: '#60a5fa'
    };
    entry.style.color = colors[level] || 'var(--text-2)';
    entry.textContent = msg;
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;
    if (level === 'error') {
        const btn = document.getElementById('startTgCheck');
        if (btn) btn.disabled = false;
        restoreTgCheckButton();
    }
}

function restoreTgCheckButton() {
    const btn = window._tgCheckButton;
    if (btn) {
        btn.disabled = false;
        btn.textContent = window._tgCheckButtonText || 'Check';
    }
    window._tgCheckButton = null;
    window._tgCheckButtonText = '';
}

function saveSettings() {
    const newConfig = { providers: {}, omkar_keys: [], firebase_urls: [], timing: {}, tg_checker: {} };

    // Collect provider settings
    const providers = settingsData.providers || {};
    for (const key of Object.keys(providers)) {
        newConfig.providers[key] = {
            key: document.getElementById(`key-${key}`)?.value || '',
            url: document.getElementById(`url-${key}`)?.value || '',
            service: document.getElementById(`svc-${key}`)?.value || '',
            country: document.getElementById(`cty-${key}`)?.value || '',
            delay: parseInt(document.getElementById(`dly-${key}`)?.value || '3')
        };
    }

    // Omkar keys
    document.querySelectorAll('.omkar-key-input').forEach(input => {
        if (input.value.trim()) newConfig.omkar_keys.push(input.value.trim());
    });

    // Firebase DB rows (URL + Key pairs)
    newConfig.firebase_dbs = [];
    newConfig.firebase_urls = [];
    document.querySelectorAll('#firebaseDbList .setting-input-row').forEach(row => {
        const url = row.querySelector('.firebase-db-url')?.value?.trim();
        const key = row.querySelector('.firebase-db-key')?.value?.trim();
        if (url) {
            newConfig.firebase_dbs.push({ url, key: key || '' });
            newConfig.firebase_urls.push(url);
        }
    });

    // Proxies
    newConfig.proxies = [];
    const proxiesTextarea = document.getElementById('proxiesTextarea');
    if (proxiesTextarea) {
        const lines = proxiesTextarea.value.split('\n');
        for (const line of lines) {
            const proxy = line.trim();
            if (proxy) newConfig.proxies.push(proxy);
        }
    }

    // Timing
    newConfig.timing = {
        otp_poll_interval: parseInt(document.getElementById('settingPollInterval').value),
        cancel_wait_seconds: parseInt(document.getElementById('settingCancelWait').value),
        max_otp_attempts: parseInt(document.getElementById('settingMaxAttempts').value)
    };

    // Telegram checker
    newConfig.tg_checker = {
        api_id: document.getElementById('tgApiId')?.value.trim() || '',
        api_hash: document.getElementById('tgApiHash')?.value.trim() || '',
        phone: document.getElementById('tgPhone')?.value.trim() || '',
        bot: ''
    };

    socket.emit('save_settings', newConfig);
    document.getElementById('settingsModal').classList.add('hidden');
}

//  Order Rendering 
function renderOrders() {
    const container = document.getElementById('ordersContainer');
    const ids = Object.keys(orders);
    document.getElementById('orderCount').textContent = ids.length;

    if (ids.length === 0) {
        container.innerHTML = `<div class="empty-state"><div class="empty-icon"></div><h3>No active numbers</h3><p>Select providers and click "Start Sniping" to begin</p></div>`;
        return;
    }

    ids.sort((a, b) => {
        const pa = getStatusPriority(orders[a].status), pb = getStatusPriority(orders[b].status);
        if (pa !== pb) return pa - pb;
        return (orders[b].timestamp || 0) - (orders[a].timestamp || 0);
    });

    container.innerHTML = ids.map(id => renderOrderCard(orders[id])).join('');

    // Attach listeners
    container.querySelectorAll('.btn-cancel').forEach(btn => {
        btn.addEventListener('click', (e) => { e.stopPropagation(); socket.emit('cancel_number', { id: btn.dataset.id }); });
    });
    container.querySelectorAll('.btn-copy-otp').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            navigator.clipboard.writeText(btn.dataset.otp);
            btn.textContent = 'Copied!';
            setTimeout(() => { btn.innerHTML = 'Copy'; }, 1500);
        });
    });
    container.querySelectorAll('.btn-repoll').forEach(btn => {
        btn.addEventListener('click', (e) => { e.stopPropagation(); socket.emit('request_new_otp', { id: btn.dataset.id }); });
    });
    container.querySelectorAll('.btn-force-cancel').forEach(btn => {
        btn.addEventListener('click', (e) => { e.stopPropagation(); socket.emit('force_cancel', { id: btn.dataset.id }); });
    });
    container.querySelectorAll('.order-card').forEach(card => {
        card.addEventListener('click', () => {
            const orderId = card.dataset.id;
            if (orders[orderId]) openOrderDetail(orders[orderId]);
        });
    });
}

function getStatusPriority(s) {
    return { extract_link: 0, logged_in: 1, logging_in: 2, otp_received: 3, waiting_otp: 4, checking_carrier: 5, cancelling: 6, non_jio: 7, cancelled: 8 }[s] ?? 5;
}

function renderOrderCard(o) {
    const prov = PROVIDERS[o.provider] || {};
    const badge = getStatusBadge(o.status);
    const statusText = getStatusText(o.status);
    const progress = getProgress(o.status);
    const time = o.timestamp ? new Date(o.timestamp * 1000).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) : '';
    const isActive = ['waiting_otp', 'checking_carrier', 'logging_in'].includes(o.status);
    const statusClass = getCardClass(o.status);

    let otp = o.otp ? `<div class="order-otp">${o.otp}</div>` : '';
    let actions = '';
    if (o.status !== 'cancelled' && o.status !== 'cancelling') {
        actions += `<button class="btn-cancel" data-id="${o.id}"> Cancel</button>`;
    }
    if (o.status === 'cancelling' || o.status === 'non_jio') {
        actions += `<button class="btn-force-cancel" data-id="${o.id}"> Force Cancel</button>`;
    }
    if (o.otp) actions += `<button class="btn-copy-otp" data-otp="${o.otp}"> Copy</button>`;
    if (['waiting_otp', 'otp_received'].includes(o.status)) {
        actions += `<button class="btn-repoll" data-id="${o.id}"> Re-poll</button>`;
    }

    let timerHtml = '';
    if (['waiting_otp', 'cancelling', 'non_jio'].includes(o.status)) {
        let maxTime = (o.status === 'waiting_otp') ? 240 : 120;
        if (o.provider === 'OTPDoctor' && o.status !== 'waiting_otp') maxTime = 300;

        let startTime = o.timestamp;
        if (o.events && o.events.length > 0) {
            // Find the last major status event, or just use the last event
            startTime = o.events[o.events.length - 1].t;
        }

        timerHtml = `
            <div class="order-timer-container" data-start="${startTime}" data-max="${maxTime}">
                <svg class="order-timer-svg" viewBox="0 0 24 24">
                    <circle class="order-timer-bg" cx="12" cy="12" r="10"></circle>
                    <circle class="order-timer-fill" cx="12" cy="12" r="10"></circle>
                </svg>
            </div>
        `;
    }

    return `
        <div class="order-card ${statusClass}" data-id="${o.id}">
            ${timerHtml}
            <div class="order-top">
                <div class="order-phone-row">
                    <span class="order-phone">+${o.phone || '...'}</span>
                    <span class="order-badge ${badge.cls}">${badge.text}</span>
                </div>
                <span class="order-time">${time}</span>
            </div>
            <div class="order-meta">
                <span class="order-provider"><span class="provider-dot ${prov.dotClass || ''}"></span>${prov.name || o.provider}</span>
                ${o.carrier ? `<span> ${o.carrier}</span>` : ''}
            </div>
            <div class="order-status-bar">
                <span class="status-text">${statusText}</span>
                ${isActive ? '<div class="status-dots"><span></span><span></span><span></span></div>' : ''}
                <div class="progress-bar"><div class="progress-fill" style="width:${progress}%"></div></div>
            </div>
            ${otp}
            <div class="order-actions">
                ${actions}
                <span class="order-id">#${(o.aid || '').slice(-6)}</span>
            </div>
        </div>`;
}

function getCardClass(s) {
    return { waiting_otp: 'status-waiting-otp', otp_received: 'status-jio', logging_in: 'status-jio', logged_in: 'status-login-success', extract_link: 'status-login-success', non_jio: 'status-non-jio', cancelling: 'status-non-jio', cancelled: 'status-non-jio' }[s] || '';
}
function getStatusBadge(s) {
    return { checking_carrier: { text: 'Checking', cls: 'badge-waiting-sms' }, waiting_otp: { text: 'Waiting SMS', cls: 'badge-waiting-sms' }, otp_received: { text: 'OTP Received', cls: 'badge-otp-received' }, logging_in: { text: 'Logging In', cls: 'badge-logging-in' }, logged_in: { text: 'Logged In', cls: 'badge-logged-in' }, extract_link: { text: 'Extract Link', cls: 'badge-extract' }, non_jio: { text: 'Non-Jio', cls: 'badge-non-jio' }, cancelling: { text: 'Cancelling', cls: 'badge-cancelling' }, cancelled: { text: 'Cancelled', cls: 'badge-non-jio' }, jio: { text: 'Jio', cls: 'badge-jio' } }[s] || { text: s, cls: 'badge-waiting-sms' };
}
function getStatusText(s) {
    return { checking_carrier: 'Checking carrier via MNP...', waiting_otp: 'Waiting for SMS', otp_received: 'OTP received! Opening browser...', logging_in: 'Logging into jio.com...', logged_in: 'Successfully logged in!', extract_link: 'Extract your link now!', non_jio: 'Not Jio. Waiting to cancel & refund.', cancelling: 'Cancelling & requesting refund...', cancelled: 'Cancelled & refunded.' }[s] || s;
}
function getProgress(s) {
    return { checking_carrier: 15, waiting_otp: 40, otp_received: 60, logging_in: 75, logged_in: 90, extract_link: 100, non_jio: 100, cancelling: 50, cancelled: 100 }[s] || 0;
}

//  Order Detail 
function renderProcessDisplay() {
    const container = document.getElementById('processContainer');
    if (!container) return;
    const ids = Object.keys(orders).sort((a, b) => (orders[b].timestamp || 0) - (orders[a].timestamp || 0));
    document.getElementById('displayCount').textContent = `${ids.length} processes`;
    if (!ids.length) {
        container.innerHTML = `<div class="empty-state"><div class="empty-icon"></div><h3>No process activity</h3><p>Live number steps will appear here</p></div>`;
        return;
    }
    container.innerHTML = ids.map(id => {
        const o = orders[id];
        const badge = getStatusBadge(o.status);
        const events = (o.events || []).slice(-8).map(ev => {
            const t = ev.t ? new Date(ev.t * 1000).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '';
            return `<div class="process-event"><span>${t}</span><p>${escapeHtml(ev.msg || '')}</p></div>`;
        }).join('');
        return `
            <div class="process-card">
                <div class="process-head">
                    <span class="order-phone">+${escapeHtml(o.phone || '...')}</span>
                    <span class="order-badge ${badge.cls}">${badge.text}</span>
                </div>
                <div class="process-stage">${escapeHtml(getStatusText(o.status))}</div>
                <div class="process-events">${events || '<div class="process-event"><p>No events yet</p></div>'}</div>
                <div class="process-foot">Number: +${escapeHtml(o.phone || '...')} | Device: ${(o.aid || '').slice(-8)}</div>
            </div>`;
    }).join('');
}

async function loadSavedLinks() {
    // Immediately render what we already have in memory
    if (savedLinks.length) renderSavedLinks();
    
    try {
        const resp = await fetch('/api/links', { cache: 'no-store' });
        const data = await resp.json();
        const serverLinks = data.links || [];
        // Merge: put server links first, then add any socket-only links
        const seen = new Set(serverLinks);
        const merged = [...serverLinks];
        for (const l of savedLinks) {
            if (l && !seen.has(l)) { merged.push(l); seen.add(l); }
        }
        savedLinks = merged;
        updateLinkCounters(savedLinks.length);
        renderSavedLinks();
    } catch (err) {
        renderSavedLinks();
        addLog(`Failed to load saved links: ${err.message}`, 'error');
    }
}

function renderSavedLinks() {
    const container = document.getElementById('savedLinksContainer');
    if (!container) return;
    document.getElementById('linksTabCount').textContent = savedLinks.length;
    if (!savedLinks.length) {
        container.innerHTML = `<div class="empty-state"><div class="empty-icon"></div><h3>No saved links</h3><p>Extracted links will appear here</p></div>`;
        return;
    }
    container.innerHTML = savedLinks.map((link, index) => `
        <div class="saved-link-row">
            <span class="saved-link-index">${index + 1}</span>
            <a class="saved-link-text" href="${escapeAttr(link)}" target="_blank" rel="noopener noreferrer">${escapeHtml(link)}</a>
            <div class="link-actions">
                ${renderLinkStatusBadge(link, false)}
                <button class="btn-secondary btn-copy-link" data-link="${escapeAttr(link)}">Copy</button>
                <button class="btn-secondary btn-open-link" data-link="${escapeAttr(link)}">Open</button>
                <button class="btn-link-delete" data-list="saved" data-link="${escapeAttr(link)}" title="Delete link">×</button>
            </div>
        </div>
    `).join('');
    bindLinkActionButtons(container);
}

async function loadCheckedLinks() {
    try {
        const resp = await fetch('/api/checked-links', { cache: 'no-store' });
        const data = await resp.json();
        checkedLinks = data.links || [];
        updateCheckedLinkCounters(data.count || checkedLinks.length);
        renderCheckedLinks();
    } catch (err) {
        addLog(`Failed to load checked links: ${err.message}`, 'error');
    }
}

function renderCheckedLinks() {
    const container = document.getElementById('checkedLinksContainer');
    if (!container) return;
    document.getElementById('checkedLinksTabCount')?.textContent && (document.getElementById('checkedLinksTabCount').textContent = checkedLinks.length);
    if (!checkedLinks.length) {
        container.innerHTML = `<div class="empty-state"><div class="empty-icon"></div><h3>No checked links</h3><p>Valid links will appear here after auto-check</p></div>`;
        return;
    }
    container.innerHTML = checkedLinks.map((link, index) => `
        <div class="saved-link-row">
            <span class="saved-link-index">${index + 1}</span>
            <a class="saved-link-text" href="${escapeAttr(link)}" target="_blank" rel="noopener noreferrer">${escapeHtml(link)}</a>
            <div class="link-actions">
                ${renderLinkStatusBadge(link, true)}
                <button class="btn-secondary btn-copy-link" data-link="${escapeAttr(link)}">Copy</button>
                <button class="btn-secondary btn-open-link" data-link="${escapeAttr(link)}">Open</button>
                <button class="btn-link-delete" data-list="checked" data-link="${escapeAttr(link)}" title="Delete link">×</button>
            </div>
        </div>
    `).join('');
    bindLinkActionButtons(container);
}

function renderLinkStatusBadge(link, defaultValid = false) {
    const status = (linkCheckStatus[link] || (defaultValid ? 'VALID' : '')).toUpperCase();
    if (!status) return '';
    const labels = {
        CHECKING: 'Checking',
        VALID: 'Valid',
        USED: 'Used',
        EXPIRED: 'Expired',
        INVALID: 'Invalid',
        UNKNOWN: 'Unknown',
        ERROR: 'Error',
        LOGIN_EXPIRED: 'Login Expired',
        SKIPPED: 'Skipped'
    };
    const cls = status === 'VALID' ? 'valid' : (status === 'USED' ? 'used' : (status === 'EXPIRED' ? 'expired' : (status === 'INVALID' || status === 'ERROR' ? 'error' : (status === 'CHECKING' ? 'checking' : 'unknown'))));
    return `<span class="link-status-badge ${cls}">${labels[status] || escapeHtml(status)}</span>`;
}

function bindLinkActionButtons(container) {
    container.querySelectorAll('.btn-open-link').forEach(btn => {
        btn.addEventListener('click', () => window.open(btn.dataset.link, '_blank', 'noopener,noreferrer'));
    });
    container.querySelectorAll('.btn-copy-link').forEach(btn => {
        btn.addEventListener('click', async () => {
            await navigator.clipboard.writeText(btn.dataset.link || '');
            btn.textContent = 'Copied';
            setTimeout(() => { btn.textContent = 'Copy'; }, 1200);
        });
    });
    container.querySelectorAll('.btn-check-link').forEach(btn => {
        btn.addEventListener('click', () => checkLinksNow([btn.dataset.link], btn));
    });
    container.querySelectorAll('.btn-link-delete').forEach(btn => {
        btn.addEventListener('click', () => deleteLinkNow(btn.dataset.link, btn.dataset.list, btn));
    });
}

async function checkLinksNow(links, btn = null) {
    const clean = [...new Set((links || []).filter(Boolean))];
    if (!clean.length) return;
    startTelegramLinkCheck(clean, btn, `Sending ${clean.length} selected links to Telegram checker...`);
}

function startTelegramLinkCheck(links = [], btn = null, message = 'Sending links to Telegram checker...') {
    const clean = [...new Set((links || []).filter(Boolean))];
    window._tgCheckButton = btn || null;
    window._tgCheckButtonText = btn?.textContent || '';
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'TG Checking...';
    }
    document.getElementById('linkCheckLog').innerHTML = '';
    document.getElementById('linkCheckProgress').textContent = 'TG checking...';
    const total = clean.length || savedLinks.length;
    linkCheckStats = { live: 0, used: 0, expired: 0, invalid: 0, error: 0, left: clean.length, total: clean.length };
    linkCheckStats.left = total;
    linkCheckStats.total = total;
    updateLinkCheckSummary();
    (clean.length ? clean : savedLinks).forEach(link => { linkCheckStatus[link] = 'CHECKING'; });
    renderVisibleLinkTabs();
    addTgCheckerLog(message, 'info');
    socket.emit('tg_checker_run', { links: clean });
}

async function deleteLinkNow(link, listName, btn = null) {
    if (!link) return;
    const oldText = btn?.textContent;
    if (btn) {
        btn.disabled = true;
        btn.textContent = '…';
    }
    try {
        const resp = await fetch('/api/delete-link', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ link, list: listName })
        });
        const data = await resp.json();
        if (listName === 'checked') {
            checkedLinks = checkedLinks.filter(item => item !== link);
            updateCheckedLinkCounters(checkedLinks.length);
            renderCheckedLinks();
        } else {
            savedLinks = savedLinks.filter(item => item !== link);
            updateLinkCounters(savedLinks.length);
            renderSavedLinks();
        }
        delete linkCheckStatus[link];
        addLog(`Deleted ${data.deleted || 0} link${(data.deleted || 0) === 1 ? '' : 's'}`, 'success');
    } catch (err) {
        addLog(`Failed to delete link: ${err.message}`, 'error');
        if (btn) {
            btn.disabled = false;
            btn.textContent = oldText || '×';
        }
    }
}

function renderVisibleLinkTabs() {
    if (document.getElementById('tab-links')?.classList.contains('active')) renderSavedLinks();
    if (document.getElementById('tab-checked-links')?.classList.contains('active')) renderCheckedLinks();
}

function markTgLinks(links, status) {
    (links || []).forEach(link => {
        if (link) linkCheckStatus[link] = status;
    });
}

function updateLinkCheckSummary() {
    const leftText = [
        `Left ${linkCheckStats.left || 0}`,
        linkCheckStats.expired ? `Exp ${linkCheckStats.expired}` : '',
        linkCheckStats.invalid ? `Inv ${linkCheckStats.invalid}` : '',
        linkCheckStats.error ? `Err ${linkCheckStats.error}` : ''
    ].filter(Boolean).join(' | ');
    const pairs = [
        ['linkCheckLive', linkCheckStats.live],
        ['linkCheckUsed', linkCheckStats.used],
        ['linkCheckLeft', leftText || (linkCheckStats.left || 0)],
        ['checkedLinkLive', linkCheckStats.live],
        ['checkedLinkUsed', linkCheckStats.used],
        ['checkedLinkLeft', leftText || (linkCheckStats.left || 0)],
    ];
    pairs.forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    });
}

function updateLinkCounters(count) {
    const value = count || 0;
    const top = document.getElementById('statLinks');
    const tab = document.getElementById('tabLinkCount');
    const list = document.getElementById('linksTabCount');
    if (top) top.textContent = value;
    if (tab) tab.textContent = value;
    if (list) list.textContent = value;
}

function updateCheckedLinkCounters(count) { /* removed */ }

async function loadProxyList() {
    try {
        const resp = await fetch('/api/proxies', { cache: 'no-store' });
        const data = await resp.json();
        proxyRows = data.proxies || [];
        proxyResults = data.cached || {};
        document.getElementById('proxyLatencyLimit').textContent = data.limit_ms || 2500;
        updateProxyCounters();
        renderProxyList();
    } catch (err) {
        addLog(`Failed to load proxies: ${err.message}`, 'error');
    }
}

function renderProxyList() {
    const container = document.getElementById('proxyListContainer');
    if (!container) return;
    if (!proxyRows.length) {
        container.innerHTML = `<div class="empty-state"><div class="empty-icon">🧪</div><h3>No proxies configured</h3><p>Add proxies in Settings to check them here</p></div>`;
        updateProxyCounters();
        return;
    }
    container.innerHTML = proxyRows.map((proxy, index) => {
        const result = proxyResults[proxy] || {};
        const status = result.status || 'UNCHECKED';
        const statusClass = result.ok ? 'proxy-live' : (status === 'UNCHECKED' ? 'proxy-idle' : 'proxy-dead');
        const latency = Number.isFinite(result.latency_ms) ? `${result.latency_ms}ms` : '-';
        return `
            <div class="proxy-row" data-proxy="${escapeAttr(proxy)}">
                <span class="saved-link-index">${index + 1}</span>
                <span class="proxy-url" title="${escapeAttr(proxy)}">${escapeHtml(proxy)}</span>
                <span class="proxy-latency">${latency}</span>
                <span class="proxy-status ${statusClass}">${proxyStatusIcon(status, result.ok)} ${escapeHtml(status)}</span>
                <button class="btn-secondary btn-check-proxy" data-proxy="${escapeAttr(proxy)}">Check</button>
            </div>
        `;
    }).join('');
    container.querySelectorAll('.btn-check-proxy').forEach(btn => {
        btn.addEventListener('click', () => checkSingleProxy(btn.dataset.proxy, btn));
    });
    updateProxyCounters();
}

function proxyStatusIcon(status, ok) {
    if (ok || status === 'LIVE') return '✅';
    if (status === 'CHECKING') return '⏳';
    if (status === 'SLOW') return '🐢';
    if (status === 'DEAD') return '❌';
    return '⚪';
}

async function checkSingleProxy(proxy, btn = null) {
    if (!proxy) return;
    proxyResults[proxy] = { status: 'CHECKING', latency_ms: null, ok: false };
    renderProxyList();
    try {
        const resp = await fetch('/api/proxy-check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ proxies: [proxy] })
        });
        const data = await resp.json();
        const result = (data.results || [])[0] || { ok: false, status: 'No response', latency_ms: null };
        proxyResults[proxy] = result;
        renderProxyList();
        addLog(`${result.ok ? '✅' : '❌'} Proxy ${result.status}: ${result.latency_ms ?? '-'}ms`, result.ok ? 'success' : 'warn');
    } catch (err) {
        proxyResults[proxy] = { status: 'DEAD', ok: false, latency_ms: null, error: err.message };
        renderProxyList();
        addLog(`❌ Proxy check failed: ${err.message}`, 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function checkAllProxies() {
    if (!proxyRows.length) {
        await loadProxyList();
    }
    if (!proxyRows.length) return;
    const btn = document.getElementById('checkAllProxies');
    if (btn) {
        btn.disabled = true;
            btn.textContent = '⏳ Checking...';
    }
    proxyRows.forEach(proxy => {
        proxyResults[proxy] = { status: 'CHECKING', latency_ms: null, ok: false };
    });
    renderProxyList();
    try {
        const resp = await fetch('/api/proxy-check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ proxies: proxyRows })
        });
        const data = await resp.json();
        (data.results || []).forEach(result => {
            proxyResults[result.proxy] = result;
        });
        renderProxyList();
        addLog(`🧪 Checked ${data.count || 0} proxies: ${Object.values(proxyResults).filter(r => r.ok).length} live`, 'info');
    } catch (err) {
        addLog(`❌ Check all proxies failed: ${err.message}`, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = '🧪 Check All';
        }
    }
}

function updateProxyCounters() {
    const total = proxyRows.length;
    const live = proxyRows.filter(proxy => proxyResults[proxy]?.ok).length;
    const tab = document.getElementById('tabProxyCount');
    const totalEl = document.getElementById('proxyTabCount');
    const liveEl = document.getElementById('proxyLiveCount');
    if (tab) tab.textContent = total;
    if (totalEl) totalEl.textContent = total;
    if (liveEl) liveEl.textContent = live;
}

function openOrderDetail(order) {
    currentDetailOrderId = order.id;
    document.getElementById('detailPhone').textContent = `+${order.phone}`;

    const prov = PROVIDERS[order.provider] || {};
    let metaHtml = `
        <span class="detail-meta-item">Provider: ${prov.name || order.provider}</span>
        <span class="detail-meta-item">Carrier: ${order.carrier || 'Unknown'}</span>
        <span class="detail-meta-item">Status: ${getStatusBadge(order.status).text}</span>
        <span class="detail-meta-item">AID: ${order.aid || 'N/A'}</span>
    `;
    document.getElementById('detailMeta').innerHTML = metaHtml;

    // OTP
    if (order.otp) {
        document.getElementById('detailOtp').innerHTML = `<div class="order-otp">${order.otp}</div>`;
    } else {
        document.getElementById('detailOtp').innerHTML = '';
    }

    // Timeline
    const events = order.events || [];
    let tlHtml = events.map(ev => {
        const t = new Date(ev.t * 1000).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        return `<div class="timeline-entry"><span class="tl-time">${t}</span><span class="tl-msg">${ev.msg}</span></div>`;
    }).join('');
    document.getElementById('detailTimeline').innerHTML = tlHtml || '<div class="timeline-entry"><span class="tl-msg">No events recorded</span></div>';

    // Actions
    let actionsHtml = '';
    if (['waiting_otp', 'otp_received'].includes(order.status)) {
        actionsHtml += `<button class="btn-repoll" onclick="socket.emit('request_new_otp',{id:'${order.id}'})"> Re-poll OTP</button>`;
    }
    if (order.status !== 'cancelled') {
        actionsHtml += `<button class="btn-force-cancel" onclick="socket.emit('force_cancel',{id:'${order.id}'}); document.getElementById('orderDetailModal').classList.add('hidden');"> Force Cancel</button>`;
    }
    if (order.otp) {
        actionsHtml += `<button class="btn-copy-otp" onclick="navigator.clipboard.writeText('${order.otp}'); this.textContent='✅ Copied!'">📋 Copy OTP</button>`;
    }
    actionsHtml += `<button class="btn-copy-otp" onclick="navigator.clipboard.writeText(JSON.stringify(${JSON.stringify(safe(order))}, null, 2)); this.textContent='✅ Copied!'">📋 Copy All</button>`;
    document.getElementById('detailActions').innerHTML = actionsHtml;

    document.getElementById('orderDetailModal').classList.remove('hidden');
}

function safe(order) {
    const o = {};
    for (const [k, v] of Object.entries(order)) { if (!k.startsWith('_')) o[k] = v; }
    return o;
}

//  Analytics 

//  Helpers 
function updateConnectionStatus(type, text) {
    const el = document.getElementById('connectionStatus');
    el.querySelector('.dot').className = `dot dot-${type}`;
    el.querySelector('span:last-child').textContent = text;
}

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[ch]));
}

function escapeAttr(value) {
    return escapeHtml(value).replace(/`/g, '&#96;');
}

function addLog(message, level = 'info') {
    const container = document.getElementById('logContainer');
    if (!container) return;
    const empty = container.querySelector('.log-empty');
    if (empty) empty.remove();
    const entry = document.createElement('div');
    entry.className = `log-entry log-${level}`;
    const time = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    entry.textContent = `[${time}] ${message}`;
    container.appendChild(entry);
    container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
    while (container.children.length > 500) container.removeChild(container.firstChild); // Keep long history
}

function updateTopStats() {
    let fetched = 0, jio = 0, otp = 0, login = 0;
    for (const o of Object.values(orders)) {
        fetched++;
        if (['waiting_otp', 'otp_received', 'logging_in', 'logged_in', 'extract_link'].includes(o.status)) jio++;
        if (o.otp) otp++;
        if (['logged_in', 'extract_link'].includes(o.status)) login++;
    }
    const statFetched = document.getElementById('statFetched');
    const statJio = document.getElementById('statJio');
    const statOtp = document.getElementById('statOtp');
    const statLogin = document.getElementById('statLogin');
    if (statFetched) statFetched.textContent = fetched;
    if (statJio) statJio.textContent = jio;
    if (statOtp) statOtp.textContent = otp;
    if (statLogin) statLogin.textContent = login;
}


/* ═══════════════════════════════════════════
   MOBILE UI
   ═══════════════════════════════════════════ */
function mobileSetSniping(active) {
    const startBtn = document.getElementById('mobileStartBtn');
    const stopBtn  = document.getElementById('mobileStopBtn');
    if (!startBtn || !stopBtn) return;
    if (active) {
        startBtn.style.display = 'none';
        stopBtn.style.display  = 'flex';
    } else {
        startBtn.style.display = 'flex';
        stopBtn.style.display  = 'none';
    }
}

function initMobileUI() {
    // Mobile Start → desktop startBtn
    document.getElementById('mobileStartBtn')?.addEventListener('click', () => {
        document.getElementById('startBtn')?.click();
        // Close drawer if open
        document.querySelector('.left-panel')?.classList.remove('mobile-open');
    });

    // Mobile Stop → desktop stopBtn
    document.getElementById('mobileStopBtn')?.addEventListener('click', () => {
        document.getElementById('stopBtn')?.click();
    });

    // ☰ Menu → toggle left panel drawer
    document.getElementById('mobileMenuBtn')?.addEventListener('click', (e) => {
        e.stopPropagation();
        const lp = document.querySelector('.left-panel');
        if (!lp) return;
        lp.classList.toggle('mobile-open');
    });

    // Close drawer on outside tap
    document.addEventListener('click', (e) => {
        if (window.innerWidth > 768) return;
        const lp = document.querySelector('.left-panel');
        const menuBtn = document.getElementById('mobileMenuBtn');
        if (!lp?.classList.contains('mobile-open')) return;
        if (lp.contains(e.target) || e.target === menuBtn) return;
        lp.classList.remove('mobile-open');
    });
}

/* ═══════════════════════════════════
   TG MONITOR UI
   ═══════════════════════════════════ */
function initTgMonitor() {
    // Status updates
    socket.on('tg_monitor_status', (data) => {
        const el = document.getElementById('tgMonitorStatus');
        if (!el) return;
        if (data.running) {
            el.textContent = '✅ Status: Running — watching channel';
            el.style.color = '#22c55e';
        } else {
            el.textContent = '⭕ Status: Not running';
            el.style.color = '#94a3b8';
        }
    });

    // Auto-start sniper when new Firebase DB added via TG Monitor
    socket.on('auto_start_sniper', () => {
        addLog('📡 TG Monitor: Auto-starting sniper with new Firebase DB...', 'info');
        // Click start button after short delay to let config save
        setTimeout(() => {
            const startBtn = document.getElementById('startBtn');
            if (startBtn && !startBtn.classList.contains('hidden')) {
                startBtn.click();
            }
        }, 2000);
    });

    socket.on('firebase_dbs_updated', (data) => {
        addLog(`📡 TG Monitor: ${data.added?.length || 0} new Firebase DB(s) added`, 'success');
        loadSavedLinks();
    });

    // Login button
    document.getElementById('tgMonitorLoginBtn')?.addEventListener('click', async () => {
        const api_id = document.getElementById('tgApiId')?.value.trim();
        const api_hash = document.getElementById('tgApiHash')?.value.trim();
        const phone = document.getElementById('tgPhone')?.value.trim();
        if (!api_id || !api_hash || !phone) {
            addLog('Fill in API ID, API Hash, and Phone first', 'error');
            return;
        }
        const btn = document.getElementById('tgMonitorLoginBtn');
        btn.disabled = true;
        btn.textContent = '⏳ Sending code...';
        try {
            const resp = await fetch('/api/tg-monitor/send-code', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_id, api_hash, phone })
            });
            const data = await resp.json();
            if (data.ok && data.needs_code) {
                document.getElementById('tgMonitorAuth').style.display = 'block';
                addLog('📱 Code sent to your Telegram! Enter it below.', 'success');
            } else if (data.ok && data.already_auth) {
                addLog('✅ Already logged in!', 'success');
            } else {
                addLog(`❌ Login error: ${data.error}`, 'error');
            }
        } catch(e) {
            addLog(`❌ Login failed: ${e.message}`, 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = '🔑 Login & Connect';
        }
    });

    // Verify code button
    document.getElementById('tgMonitorVerifyBtn')?.addEventListener('click', async () => {
        const api_id = document.getElementById('tgApiId')?.value.trim();
        const api_hash = document.getElementById('tgApiHash')?.value.trim();
        const phone = document.getElementById('tgPhone')?.value.trim();
        const code = document.getElementById('tgMonitorCode')?.value.trim();
        const password = document.getElementById('tgMonitorPass')?.value.trim();
        const btn = document.getElementById('tgMonitorVerifyBtn');
        btn.disabled = true;
        btn.textContent = '⏳ Verifying...';
        try {
            const resp = await fetch('/api/tg-monitor/verify-code', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_id, api_hash, phone, code, password })
            });
            const data = await resp.json();
            if (data.ok) {
                addLog('✅ Logged in successfully!', 'success');
                document.getElementById('tgMonitorAuth').style.display = 'none';
            } else if (data.needs_password) {
                document.getElementById('tgMonitorPassGroup').style.display = 'block';
                addLog('🔐 2FA password required', 'warn');
            } else {
                addLog(`❌ Verify error: ${data.error}`, 'error');
            }
        } catch(e) {
            addLog(`❌ Verify failed: ${e.message}`, 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = '✅ Verify Code';
        }
    });

    // Start monitor
    document.getElementById('tgMonitorStartBtn')?.addEventListener('click', () => {
        const channel = document.getElementById('tgMonitorChannel')?.value.trim();
        if (!channel) { addLog('Enter channel username or ID first', 'error'); return; }
        // Save channel to config
        socket.emit('save_tg_monitor_config', {
            channel,
            api_id: document.getElementById('tgApiId')?.value.trim(),
            api_hash: document.getElementById('tgApiHash')?.value.trim(),
            phone: document.getElementById('tgPhone')?.value.trim(),
        });
        socket.emit('start_tg_monitor');
        addLog('📡 TG Monitor starting...', 'info');
    });

    // Stop monitor
    document.getElementById('tgMonitorStopBtn')?.addEventListener('click', () => {
        socket.emit('stop_tg_monitor');
    });

    // Get initial status
    socket.emit('get_tg_monitor_status');
}

// Call after socket init
if (typeof socket !== 'undefined') {
    document.addEventListener('DOMContentLoaded', initTgMonitor);
}

/* ═══════════════════════════════════
   FIREBASE BULK PASTE
   ═══════════════════════════════════ */
function toggleFirebaseBulk() {
    const sec = document.getElementById('firebaseBulkSection');
    if (!sec) return;
    sec.style.display = sec.style.display === 'none' ? 'block' : 'none';
}

function clearFirebaseList() {
    if (!confirm('Clear all Firebase databases from the list?')) return;
    const list = document.getElementById('firebaseDbList');
    if (list) list.innerHTML = '';
}

function parseBulkFirebase() {
    const textarea = document.getElementById('firebaseBulkInput');
    if (!textarea) return;

    const lines = textarea.value.split('\n');
    const urlPattern = /https?:\/\/[a-zA-Z0-9_-]+-default-rtdb(?:\.firebaseio\.com|\.[\w-]+\.firebasedatabase\.app)/;
    const keyPattern = /(?:🔑\s*)?[Kk]ey\s*[:\-]?\s*([A-Za-z0-9_\-]{2,40})/;

    let added = 0;
    let skipped = 0;

    // Get existing URLs to avoid duplicates
    const existing = new Set();
    document.querySelectorAll('#firebaseDbList .firebase-db-url').forEach(el => {
        if (el.value.trim()) existing.add(el.value.trim());
    });

    // Group lines into blocks (each URL starts a block)
    const blocks = [];
    let currentBlock = [];
    for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) {
            if (currentBlock.length) { blocks.push(currentBlock.join('\n')); currentBlock = []; }
            continue;
        }
        if (urlPattern.test(trimmed) && currentBlock.length > 0) {
            blocks.push(currentBlock.join('\n'));
            currentBlock = [trimmed];
        } else {
            currentBlock.push(trimmed);
        }
    }
    if (currentBlock.length) blocks.push(currentBlock.join('\n'));

    for (const block of blocks) {
        const urlMatch = urlPattern.exec(block);
        if (!urlMatch) continue;

        const url = urlMatch[0].trim().replace(/\/$/, '');
        if (existing.has(url)) { skipped++; continue; }

        // Extract key from same block
        let key = '';
        const keyMatch = keyPattern.exec(block);
        if (keyMatch) {
            const candidate = keyMatch[1].trim();
            if (!candidate.includes('http') && candidate.length >= 2) {
                key = candidate;
            }
        }

        addFirebaseDbRow(url, key);
        existing.add(url);
        added++;
    }

    // Show result
    const msg = `✅ Added ${added} database(s)${skipped ? `, skipped ${skipped} duplicates` : ''}.`;
    addLog(msg, 'success');
    textarea.value = '';
    document.getElementById('firebaseBulkSection').style.display = 'none';

    if (added > 0) {
        // Scroll to list
        document.getElementById('firebaseDbList')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

// ─── Airtel Duolingo Functions ─────────────────────────────────────────────

function updateDuoCount(count) {
    const val = count || 0;
    const tab = document.getElementById('tabDuoCount');
    const inner = document.getElementById('duoLinkCount');
    if (tab) tab.textContent = val;
    if (inner) inner.textContent = val;
}

async function loadDuoLinks() {
    if (duoLinks.length) renderDuoLinks();
    try {
        const resp = await fetch('/api/airtel-links', { cache: 'no-store' });
        const data = await resp.json();
        const serverLinks = data.links || [];
        const seen = new Set(serverLinks);
        const merged = [...serverLinks];
        for (const l of duoLinks) {
            if (l && !seen.has(l)) { merged.push(l); seen.add(l); }
        }
        duoLinks = merged;
        updateDuoCount(duoLinks.length);
        renderDuoLinks();
    } catch (err) {
        renderDuoLinks();
        addLog(`Failed to load Duolingo links: ${err.message}`, 'error');
    }
}

function renderDuoLinks() {
    const container = document.getElementById('duoLinksContainer');
    if (!container) return;
    updateDuoCount(duoLinks.length);
    if (!duoLinks.length) {
        container.innerHTML = `<p style="color:#6c7086;font-size:13px;">No Duolingo links yet. Start the batch to extract links.</p>`;
        return;
    }
    container.innerHTML = duoLinks.map((link, i) => {
        // Extract code from URL for display: duolingo.com/redeem?code=AIRTELLIVE...
        const codeMatch = link.match(/[?&]code=([^&]+)/);
        const codeLabel = codeMatch ? codeMatch[1] : link;
        return `
        <div class="saved-link-row" style="display:flex;align-items:center;gap:8px;padding:6px 8px;background:#1e1e2e;border-radius:6px;border:1px solid #313244;">
            <span class="saved-link-index" style="color:#6c7086;min-width:24px;">${i + 1}</span>
            <a class="saved-link-text" href="${escapeAttr(link)}" target="_blank" rel="noopener noreferrer"
                style="flex:1;font-size:12px;color:#89b4fa;text-decoration:none;word-break:break-all;">
                🦉 ${escapeHtml(codeLabel)}
            </a>
            <div style="display:flex;gap:6px;flex-shrink:0;">
                <button class="btn-secondary" style="padding:2px 8px;font-size:11px;"
                    onclick="navigator.clipboard.writeText('${escapeAttr(link)}');addLog('Copied!','success')">Copy</button>
                <button class="btn-secondary" style="padding:2px 8px;font-size:11px;"
                    onclick="window.open('${escapeAttr(link)}','_blank')">Open</button>
            </div>
        </div>`;
    }).join('');
}

function airtelStart() {
    const concurrency = parseInt(document.getElementById('airtelConcurrency')?.value || '2');
    const delay       = parseFloat(document.getElementById('airtelDelay')?.value || '10');
    console.log('[Airtel] emitting start_airtel_batch', { concurrency, delay });
    socket.emit('start_airtel_batch', { concurrency, delay });
    addLog(`🚀 Airtel Duolingo batch starting (concurrency=${concurrency}, delay=${delay}s)...`, 'info');
}

function airtelStop() {
    socket.emit('stop_airtel_batch');
    addLog('⏹ Stopping Airtel batch...', 'warn');
}

function airtelCopyAll() {
    if (!duoLinks.length) { addLog('No Duolingo links to copy', 'warn'); return; }
    navigator.clipboard.writeText(duoLinks.join('\n'));
    addLog(`📋 Copied ${duoLinks.length} Duolingo links`, 'success');
}

function airtelClear() {
    if (!confirm(`Clear all ${duoLinks.length} Duolingo links?`)) return;
    socket.emit('clear_airtel_links');
    duoLinks = [];
    renderDuoLinks();
    updateDuoCount(0);
    addLog('🗑 Duolingo links cleared', 'info');
}

function initAirtelBatch() {
    // Kept for compatibility — buttons now use inline onclick
    console.log('[Airtel] initAirtelBatch called');
}

function airtelUpdateConcurrency() {
    const val = parseInt(document.getElementById('airtelConcurrency')?.value || '2');
    socket.emit('update_airtel_concurrency', { concurrency: val });
}


// initAirtelBatch is called from the main DOMContentLoaded block above

// ─── Manual Airtel Test Tool ───────────────────────────────────────────────

let _manualSessionId = null;
let _manualPollTimer = null;

// Tab switch trigger
const _origInitTabs = window._origInitTabs;
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => {
        document.querySelectorAll('.tab-btn').forEach(btn => {
            if (btn.dataset.tab === 'airtel-manual') {
                btn.addEventListener('click', () => manualScanDevices());
            }
        });
    }, 1000);
});

async function manualScanDevices() {
    const list = document.getElementById('manualDeviceList');
    if (!list) return;
    list.innerHTML = '<p style="color:#a6adc8;font-size:13px;">⏳ Scanning Firebase...</p>';
    try {
        const resp = await fetch('/api/airtel-manual/devices', { cache: 'no-store' });
        const data = await resp.json();
        if (data.error) { list.innerHTML = `<p style="color:#f38ba8;">${data.error}</p>`; return; }
        const devices = data.devices || [];
        if (!devices.length) { list.innerHTML = '<p style="color:#6c7086;font-size:13px;">No devices found.</p>'; return; }
        list.innerHTML = devices.map(d => `
            <div style="display:flex;align-items:center;gap:8px;padding:5px 8px;background:#1e1e2e;border-radius:5px;border:1px solid #313244;">
                <span style="font-family:monospace;font-size:13px;color:#cdd6f4;flex:1;">📱 +91${d.phone}</span>
                <span style="font-size:11px;color:#6c7086;">${d.db_name}</span>
                <button class="btn-secondary" style="padding:2px 10px;font-size:12px;"
                    onclick='manualStartSession(${JSON.stringify(d)})'>Test</button>
            </div>
        `).join('');
        addLog(`🔬 Found ${devices.length} Firebase devices`, 'info');
    } catch(e) {
        list.innerHTML = `<p style="color:#f38ba8;">Error: ${e.message}</p>`;
    }
}

async function manualStartSession(device) {
    const panel = document.getElementById('manualSessionPanel');
    const phoneEl = document.getElementById('manualSessionPhone');
    const statusEl = document.getElementById('manualSessionStatus');
    const logEl = document.getElementById('manualLog');
    const ssEl = document.getElementById('manualScreenshots');
    const otpRow = document.getElementById('manualOtpRow');

    if (panel) panel.style.display = 'block';
    if (phoneEl) phoneEl.textContent = `+91${device.phone}`;
    if (logEl) logEl.innerHTML = '';
    if (ssEl) ssEl.innerHTML = '';
    if (otpRow) otpRow.style.display = 'none';

    manualSetStatus('Starting...', '#6c7086');
    addLog(`🔬 Manual test starting for +91${device.phone}`, 'info');

    try {
        const resp = await fetch('/api/airtel-manual/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ phone: device.phone, device_id: device.device_id, fb_url: device.fb_url })
        });
        const data = await resp.json();
        if (data.error) { manualSetStatus(`Error: ${data.error}`, '#f38ba8'); return; }
        _manualSessionId = data.session_id;
        manualSetStatus('Sending OTP...', '#89b4fa');
        manualStartPolling();
    } catch(e) {
        manualSetStatus(`Error: ${e.message}`, '#f38ba8');
    }
}

function manualSetStatus(text, color) {
    const el = document.getElementById('manualSessionStatus');
    if (el) { el.textContent = text; el.style.color = color || '#cdd6f4'; }
}

function manualStartPolling() {
    if (_manualPollTimer) clearInterval(_manualPollTimer);
    _manualPollTimer = setInterval(manualPollStatus, 2000);
}

async function manualPollStatus() {
    if (!_manualSessionId) return;
    try {
        const resp = await fetch(`/api/airtel-manual/status/${_manualSessionId}`, { cache: 'no-store' });
        const data = await resp.json();
        manualUpdateLog(data.log || []);
        manualUpdateScreenshots(data.screenshots || []);

        if (data.status === 'otp_received') {
            manualSetStatus(`OTP: ${data.otp} — Submit to continue`, '#a6e3a1');
            const inp = document.getElementById('manualOtpInput');
            if (inp) inp.value = data.otp;
            const otpRow = document.getElementById('manualOtpRow');
            if (otpRow) otpRow.style.display = 'flex';
        } else if (data.status === 'otp_timeout') {
            manualSetStatus('OTP timeout — enter manually', '#fab387');
            const otpRow = document.getElementById('manualOtpRow');
            if (otpRow) otpRow.style.display = 'flex';
        } else if (data.status === 'waiting_otp') {
            manualSetStatus('Waiting for OTP...', '#89b4fa');
        } else if (data.status === 'done') {
            const hasDuo = data.has_duolingo;
            manualSetStatus(hasDuo ? '✅ Duolingo offer found!' : '❌ No Duolingo offer', hasDuo ? '#a6e3a1' : '#f38ba8');
            clearInterval(_manualPollTimer);
        } else if (data.status === 'error') {
            manualSetStatus('Error — check log', '#f38ba8');
            clearInterval(_manualPollTimer);
        }
    } catch(e) {}
}

function manualUpdateLog(lines) {
    const el = document.getElementById('manualLog');
    if (!el) return;
    el.innerHTML = lines.map(l => `<div>${escapeHtml(l)}</div>`).join('');
    el.scrollTop = el.scrollHeight;
}

function manualUpdateScreenshots(screenshots) {
    const el = document.getElementById('manualScreenshots');
    if (!el || !screenshots.length) return;
    el.innerHTML = screenshots.map(ss => `
        <div style="text-align:center;">
            <p style="font-size:10px;color:#6c7086;margin:0 0 3px;">${escapeHtml(ss.label)}</p>
            <a href="/api/airtel-manual/screenshot/${ss.file}" target="_blank">
                <img src="/api/airtel-manual/screenshot/${ss.file}?t=${Date.now()}"
                    style="width:200px;border-radius:4px;border:1px solid #45475a;"
                    onerror="this.style.display='none'">
            </a>
        </div>
    `).join('');
}

async function manualSubmitOtp() {
    const otp = document.getElementById('manualOtpInput')?.value?.trim();
    if (!otp || !_manualSessionId) return;
    manualSetStatus('Submitting OTP...', '#89b4fa');
    const otpRow = document.getElementById('manualOtpRow');
    if (otpRow) otpRow.style.display = 'none';
    try {
        const resp = await fetch('/api/airtel-manual/submit-otp', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: _manualSessionId, otp })
        });
        const data = await resp.json();
        manualUpdateLog(data.log || []);
        manualUpdateScreenshots(data.screenshots || []);
        if (data.has_duolingo) {
            manualSetStatus('✅ Duolingo offer found!', '#a6e3a1');
        } else {
            manualSetStatus('❌ No Duolingo offer on this number', '#f38ba8');
        }
        clearInterval(_manualPollTimer);
    } catch(e) {
        manualSetStatus(`Error: ${e.message}`, '#f38ba8');
    }
}
