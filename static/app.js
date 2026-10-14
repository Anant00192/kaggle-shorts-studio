document.addEventListener('DOMContentLoaded', () => {
    // --- State ---
    let currentSlotCount = 1;
    let studioData = {
        globals: { voice: null, bgm: null, outro: null },
        slots: {}
    };
    let isPolling = false;
    let pollInterval = null;

    // --- DOM Elements ---
    const credsForm = document.getElementById('credsForm');
    const toggleCredsBtn = document.getElementById('toggleCredsBtn');
    const resetDefaultCredsBtn = document.getElementById('resetDefaultCredsBtn');
    const activeUsernameDisplay = document.getElementById('activeUsernameDisplay');
    const kaggleUsernameInput = document.getElementById('kaggleUsername');
    const kaggleKeyInput = document.getElementById('kaggleKey');
    const connectionStatus = document.getElementById('connectionStatus');
    const connectionText = document.getElementById('connectionText');
    const saveCredsBtn = document.getElementById('saveCredsBtn');

    // Multi-Account & Browser Storage Elements
    const quickAccountSelect = document.getElementById('quickAccountSelect');
    const deleteAccountBtn = document.getElementById('deleteAccountBtn');
    const browserSyncTag = document.getElementById('browserSyncTag');
    const accountTagBadge = document.getElementById('accountTagBadge');
    const browserCacheBadge = document.getElementById('browserCacheBadge');
    const accountSubtext = document.getElementById('accountSubtext');

    const slotButtons = document.getElementById('slotButtons');
    const slotsContainer = document.getElementById('slotsContainer');

    const outroRatio = document.getElementById('outroRatio');
    const zoomFactor = document.getElementById('zoomFactor');
    const zoomVal = document.getElementById('zoomVal');
    const cooldownSecs = document.getElementById('cooldownSecs');
    const aiUpscaling = document.getElementById('aiUpscaling');

    const launchBtn = document.getElementById('launchBtn');
    const downloadBtn = document.getElementById('downloadBtn');
    const statusBadge = document.getElementById('statusBadge');
    const statusMessage = document.getElementById('statusMessage');
    const progressBar = document.getElementById('progressBar');
    const terminalLogs = document.getElementById('terminalLogs');
    const clearLogBtn = document.getElementById('clearLogBtn');

    // --- Range Sliders ---
    zoomFactor.addEventListener('input', (e) => {
        zoomVal.textContent = parseFloat(e.target.value).toFixed(2) + 'x';
    });

    // --- Slot Count Buttons ---
    slotButtons.querySelectorAll('.btn-slot-num').forEach(btn => {
        btn.addEventListener('click', () => {
            slotButtons.querySelectorAll('.btn-slot-num').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentSlotCount = parseInt(btn.dataset.count, 10);
            renderSlots();
        });
    });

    // --- Account & Browser Storage Manager ---
    const STORAGE_KEY = 'kaggle_shorts_studio_accounts';
    const ACTIVE_KEY = 'kaggle_shorts_studio_active';

    function getBrowserName() {
        const ua = navigator.userAgent;
        if (ua.includes("Firefox")) return "Mozilla Firefox";
        if (ua.includes("Edg")) return "Microsoft Edge";
        if (ua.includes("Chrome")) return "Google Chrome";
        if (ua.includes("Safari")) return "Apple Safari";
        return "This Browser";
    }

    function getStoredAccounts() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            return raw ? JSON.parse(raw) : {};
        } catch (e) {
            return {};
        }
    }

    function saveStoredAccounts(accounts) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(accounts));
        } catch (e) {
            console.error('Failed to save accounts to localStorage:', e);
        }
    }

    function getActiveAccount() {
        const accounts = getStoredAccounts();
        const activeUser = localStorage.getItem(ACTIVE_KEY);
        if (activeUser && accounts[activeUser]) {
            return accounts[activeUser];
        }
        const keys = Object.keys(accounts);
        if (keys.length > 0) {
            return accounts[keys[0]];
        }
        return null;
    }

    function setActiveAccount(account) {
        if (!account || !account.username) return;
        localStorage.setItem(ACTIVE_KEY, account.username);
        document.cookie = `kaggle_username=${encodeURIComponent(account.username)}; path=/; max-age=31536000; SameSite=Lax`;
        if (account.key) {
            document.cookie = `kaggle_key=${encodeURIComponent(account.key)}; path=/; max-age=31536000; SameSite=Lax`;
        }
    }

    async function apiFetch(url, options = {}) {
        options.headers = options.headers || {};
        const active = getActiveAccount();
        if (active && active.username) {
            options.headers['X-Kaggle-Username'] = active.username;
            if (active.key) {
                options.headers['X-Kaggle-Key'] = active.key;
            }
        }
        return fetch(url, options);
    }

    function updateConnectionState(connected, text) {
        const dot = connectionStatus.querySelector('.dot');
        if (dot) dot.className = 'dot ' + (connected ? 'connected' : 'disconnected');
        if (connectionText) connectionText.textContent = text;
    }

    function renderAccountUI() {
        const accounts = getStoredAccounts();
        const active = getActiveAccount();
        const browserName = getBrowserName();

        if (browserSyncTag) {
            browserSyncTag.textContent = `🌐 ${browserName} Sync`;
        }

        if (active) {
            if (activeUsernameDisplay) activeUsernameDisplay.textContent = `@${active.username}`;
            if (accountTagBadge) {
                accountTagBadge.textContent = active.isDefault ? 'Default' : 'Custom';
                accountTagBadge.className = active.isDefault ? 'tag-default' : 'tag-default custom';
            }
            if (browserCacheBadge) {
                browserCacheBadge.textContent = `Saved in ${browserName}`;
            }
            if (accountSubtext) {
                accountSubtext.textContent = `Active Kaggle profile for this ${browserName} session: @${active.username}. All batch uploads and GPU runs stay bound to this browser.`;
            }
            updateConnectionState(true, `Connected as @${active.username} (${browserName})`);

            if (kaggleUsernameInput) kaggleUsernameInput.value = active.username;
            if (kaggleKeyInput) kaggleKeyInput.placeholder = `•••••••••••••••••••••••• (Saved in ${browserName})`;
        } else {
            if (activeUsernameDisplay) activeUsernameDisplay.textContent = 'Not Connected';
            if (accountTagBadge) accountTagBadge.style.display = 'none';
            if (browserCacheBadge) {
                browserCacheBadge.textContent = `No Account in ${browserName}`;
            }
            if (accountSubtext) {
                accountSubtext.textContent = `No Kaggle credentials found in this ${browserName}. Add your Kaggle username & API key below to enable processing.`;
            }
            updateConnectionState(false, `Not Connected (${browserName})`);
            if (credsForm) credsForm.classList.remove('hidden');
            if (toggleCredsBtn) toggleCredsBtn.textContent = '▲ Enter Account Credentials';
        }

        if (quickAccountSelect) {
            quickAccountSelect.innerHTML = '';
            const userList = Object.keys(accounts);
            if (userList.length === 0) {
                const opt = document.createElement('option');
                opt.value = '__add_new__';
                opt.textContent = `+ Add Kaggle Account in this ${browserName}...`;
                quickAccountSelect.appendChild(opt);
                if (deleteAccountBtn) deleteAccountBtn.classList.add('hidden');
            } else {
                userList.forEach(u => {
                    const opt = document.createElement('option');
                    opt.value = u;
                    const isDef = accounts[u].isDefault ? ' (Default)' : '';
                    opt.textContent = `@${u}${isDef}`;
                    if (active && active.username === u) {
                        opt.selected = true;
                    }
                    quickAccountSelect.appendChild(opt);
                });

                const optAdd = document.createElement('option');
                optAdd.value = '__add_new__';
                optAdd.textContent = '➕ Add another Kaggle account...';
                quickAccountSelect.appendChild(optAdd);

                if (deleteAccountBtn) {
                    if (active && !active.isDefault) {
                        deleteAccountBtn.classList.remove('hidden');
                    } else {
                        deleteAccountBtn.classList.add('hidden');
                    }
                }
            }
        }
    }

    toggleCredsBtn.addEventListener('click', () => {
        credsForm.classList.toggle('hidden');
        toggleCredsBtn.textContent = credsForm.classList.contains('hidden')
            ? '➕ Add / Manage Accounts'
            : '▲ Hide Credentials Form';
    });

    quickAccountSelect.addEventListener('change', (e) => {
        const val = e.target.value;
        if (val === '__add_new__') {
            credsForm.classList.remove('hidden');
            if (kaggleUsernameInput) kaggleUsernameInput.value = '';
            if (kaggleKeyInput) {
                kaggleKeyInput.value = '';
                kaggleKeyInput.placeholder = 'Paste Kaggle API token (KGAT_...)';
            }
            kaggleUsernameInput.focus();
            return;
        }

        const accounts = getStoredAccounts();
        if (accounts[val]) {
            setActiveAccount(accounts[val]);
            renderAccountUI();
            apiFetch('/api/credentials', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    username: accounts[val].username,
                    key: accounts[val].key
                })
            }).then(() => {
                loadStudioState();
            }).catch(console.error);
        }
    });

    if (deleteAccountBtn) {
        deleteAccountBtn.addEventListener('click', () => {
            const active = getActiveAccount();
            if (!active || active.isDefault) return;
            if (confirm(`Remove @${active.username} from this browser's cached accounts?`)) {
                const accounts = getStoredAccounts();
                delete accounts[active.username];
                saveStoredAccounts(accounts);
                const remaining = Object.keys(accounts);
                if (remaining.length > 0) {
                    setActiveAccount(accounts[remaining[0]]);
                } else {
                    localStorage.removeItem(ACTIVE_KEY);
                }
                renderAccountUI();
                loadStudioState();
            }
        });
    }

    credsForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = kaggleUsernameInput.value.trim();
        const key = kaggleKeyInput.value.trim();

        if (!username || !key) {
            alert('Please enter both Kaggle Username and API Key.');
            return;
        }

        saveCredsBtn.disabled = true;
        saveCredsBtn.textContent = 'Verifying...';

        try {
            const res = await fetch('/api/credentials', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, key })
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);

            const accounts = getStoredAccounts();
            accounts[username] = {
                username: username,
                key: key,
                isDefault: (username === 'rathinnew')
            };
            saveStoredAccounts(accounts);
            setActiveAccount(accounts[username]);

            renderAccountUI();
            credsForm.classList.add('hidden');
            toggleCredsBtn.textContent = '➕ Add / Manage Accounts';
            alert(`✅ Kaggle account @${username} verified and saved!`);
        } catch (err) {
            alert('❌ Verification failed: ' + err.message);
        } finally {
            saveCredsBtn.disabled = false;
            saveCredsBtn.textContent = '💾 Save to this Browser';
        }
    });

    resetDefaultCredsBtn.addEventListener('click', async () => {
        if (!confirm('Reset to default Kaggle account (@rathinnew)?')) return;
        try {
            const res = await fetch('/api/reset_credentials', { method: 'POST' });
            const data = await res.json();
            if (data.success) {
                const accounts = getStoredAccounts();
                accounts[data.username] = {
                    username: data.username,
                    key: data.key,
                    isDefault: true
                };
                saveStoredAccounts(accounts);
                setActiveAccount(accounts[data.username]);
                renderAccountUI();
                loadStudioState();
                alert(`✅ Reset to default @${data.username}`);
            }
        } catch (err) {
            alert('Failed to reset: ' + err.message);
        }
    });

    // --- State & Rendering ---
    async function loadStudioState() {
        try {
            const res = await apiFetch('/api/studio_state');
            const data = await res.json();

            // Init accounts if empty
            const accounts = getStoredAccounts();
            if (Object.keys(accounts).length === 0) {
                accounts['rathinnew'] = {
                    username: 'rathinnew',
                    key: 'KGAT_10cab40726cd143c3e7d52696187fb7a',
                    isDefault: true
                };
                saveStoredAccounts(accounts);
                setActiveAccount(accounts['rathinnew']);
            }

            renderAccountUI();

            studioData.globals = data.globals || {};
            studioData.slots = data.slots || {};

            let maxSlot = 1;
            for (let i = 1; i <= 10; i++) {
                if (studioData.slots[String(i)] && studioData.slots[String(i)].video) {
                    maxSlot = Math.max(maxSlot, i);
                }
            }
            currentSlotCount = Math.min(Math.max(currentSlotCount, maxSlot), 10);
            slotButtons.querySelectorAll('.btn-slot-num').forEach(b => {
                b.classList.toggle('active', parseInt(b.dataset.count, 10) === currentSlotCount);
            });

            renderGlobals();
            renderSlots();

            if (data.app_state) {
                updateStatusDisplay(data.app_state);
                if (['running', 'syncing', 'pushing'].includes(data.app_state.status)) {
                    startPolling();
                }
            }
        } catch (err) {
            console.error('Failed to load studio state:', err);
        }
    }

    // --- Render Global Dropzones ---
    function renderGlobals() {
        ['voice', 'bgm', 'outro'].forEach(type => {
            const container = document.getElementById(`${type}-content`);
            if (!container) return;
            const dz = container.closest('.upload-dropzone');
            const info = studioData.globals[type];

            if (info) {
                dz.classList.add('has-file');
                container.innerHTML = `
                    <div class="uploaded-chip">
                        <span class="chip-name" title="${info.original_name}">${info.original_name}</span>
                        <span class="chip-size">(${info.size_mb} MB)</span>
                        <button type="button" class="chip-del" data-type="global" data-asset="${type}" title="Remove file">✕</button>
                    </div>
                `;
            } else {
                dz.classList.remove('has-file');
                container.innerHTML = `<span class="dz-prompt">Click or drag ${type.toUpperCase()} file</span>`;
            }
        });

        document.querySelectorAll('.chip-del[data-type="global"]').forEach(btn => {
            btn.onclick = async (e) => {
                e.stopPropagation();
                const asset = btn.dataset.asset;
                await apiFetch('/api/delete_global', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ kind: asset })
                });
                studioData.globals[asset] = null;
                renderGlobals();
            };
        });

        setupGlobalDropzones();
    }

    function setupGlobalDropzones() {
        document.querySelectorAll('.upload-dropzone[data-global]').forEach(dz => {
            const assetType = dz.dataset.global;
            const input = dz.querySelector('.file-input');

            dz.onclick = () => {
                if (!studioData.globals[assetType]) input.click();
            };

            input.onchange = () => {
                if (input.files.length > 0) {
                    uploadGlobalFile(assetType, input.files[0]);
                    input.value = '';
                }
            };

            ['dragenter', 'dragover'].forEach(evt => {
                dz.addEventListener(evt, (e) => {
                    e.preventDefault();
                    dz.classList.add('drag-over');
                });
            });

            ['dragleave', 'drop'].forEach(evt => {
                dz.addEventListener(evt, (e) => {
                    e.preventDefault();
                    dz.classList.remove('drag-over');
                });
            });

            dz.ondrop = (e) => {
                e.preventDefault();
                dz.classList.remove('drag-over');
                if (e.dataTransfer.files.length > 0) {
                    uploadGlobalFile(assetType, e.dataTransfer.files[0]);
                }
            };
        });
    }

    async function uploadGlobalFile(kind, file) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('kind', kind);

        const container = document.getElementById(`${kind}-content`);
        if (container) container.innerHTML = `<span class="uploading-spinner">Uploading ${file.name}...</span>`;

        try {
            const res = await apiFetch('/api/upload_global', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);

            studioData.globals[kind] = {
                filename: file.name,
                original_name: data.original_name,
                size_mb: data.size_mb
            };
            renderGlobals();
        } catch (err) {
            alert('Upload failed: ' + err.message);
            renderGlobals();
        }
    }

    // --- Render Shorts Slots ---
    function renderSlots() {
        slotsContainer.innerHTML = '';
        for (let i = 1; i <= currentSlotCount; i++) {
            const slotStr = String(i);
            const slotData = studioData.slots[slotStr] || { video: null };

            const card = document.createElement('div');
            card.className = 'slot-card';
            card.dataset.slot = i;

            card.innerHTML = `
                <div class="slot-header">
                    <span class="slot-num">Short #${i}</span>
                    ${slotData.video ? '<span class="status-ready">✓ Video Ready</span>' : '<span class="status-empty">Pending Video</span>'}
                </div>
                <div class="slot-body">
                    <div class="slot-dropzone ${slotData.video ? 'has-file' : ''}" data-slot="${i}">
                        <input type="file" accept=".mp4,.mov,.mkv,.webm" class="slot-file-input" style="display: none;">
                        <div class="slot-dz-content">
                            ${slotData.video ? `
                                <div class="uploaded-chip">
                                    <span class="chip-name" title="${slotData.video.original_name}">🎬 ${slotData.video.original_name}</span>
                                    <span class="chip-size">(${slotData.video.size_mb} MB)</span>
                                    <button type="button" class="chip-del" data-type="slot" data-slot="${i}" title="Remove video">✕</button>
                                </div>
                            ` : `
                                <div class="slot-prompt">
                                    <span class="prompt-icon">📁</span>
                                    <span class="prompt-text">Click or drag Short Video #${i}</span>
                                </div>
                            `}
                        </div>
                    </div>
                </div>
            `;
            slotsContainer.appendChild(card);
        }

        document.querySelectorAll('.chip-del[data-type="slot"]').forEach(btn => {
            btn.onclick = async (e) => {
                e.stopPropagation();
                const slotNum = btn.dataset.slot;
                await apiFetch('/api/delete_slot_file', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ slot_num: slotNum })
                });
                if (studioData.slots[slotNum]) {
                    studioData.slots[slotNum].video = null;
                }
                renderSlots();
            };
        });

        setupSlotDropzones();
    }

    function setupSlotDropzones() {
        document.querySelectorAll('.slot-dropzone').forEach(dz => {
            const slotNum = dz.dataset.slot;
            const input = dz.querySelector('.slot-file-input');

            dz.onclick = () => {
                const sData = studioData.slots[slotNum];
                if (!sData || !sData.video) input.click();
            };

            input.onchange = () => {
                if (input.files.length > 0) {
                    uploadSlotVideo(slotNum, input.files[0]);
                    input.value = '';
                }
            };

            ['dragenter', 'dragover'].forEach(evt => {
                dz.addEventListener(evt, (e) => {
                    e.preventDefault();
                    dz.classList.add('drag-over');
                });
            });

            ['dragleave', 'drop'].forEach(evt => {
                dz.addEventListener(evt, (e) => {
                    e.preventDefault();
                    dz.classList.remove('drag-over');
                });
            });

            dz.ondrop = (e) => {
                e.preventDefault();
                dz.classList.remove('drag-over');
                if (e.dataTransfer.files.length > 0) {
                    uploadSlotVideo(slotNum, e.dataTransfer.files[0]);
                }
            };
        });
    }

    async function uploadSlotVideo(slotNum, file) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('slot_num', slotNum);

        const card = document.querySelector(`.slot-card[data-slot="${slotNum}"]`);
        const dzContent = card ? card.querySelector('.slot-dz-content') : null;
        if (dzContent) dzContent.innerHTML = `<span class="uploading-spinner">Uploading Short #${slotNum}...</span>`;

        try {
            const res = await apiFetch('/api/upload_slot_file', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);

            if (!studioData.slots[slotNum]) studioData.slots[slotNum] = {};
            studioData.slots[slotNum].video = {
                filename: file.name,
                original_name: data.original_name,
                size_mb: data.size_mb
            };
            renderSlots();
        } catch (err) {
            alert('Upload failed: ' + err.message);
            renderSlots();
        }
    }

    // --- Launch Pipeline ---
    launchBtn.addEventListener('click', async () => {
        const active = getActiveAccount();
        if (!active || !active.username || !active.key) {
            alert('Please connect your Kaggle account first.');
            return;
        }

        let hasVideo = false;
        for (let i = 1; i <= currentSlotCount; i++) {
            if (studioData.slots[String(i)] && studioData.slots[String(i)].video) {
                hasVideo = true;
                break;
            }
        }
        if (!hasVideo) {
            alert('Please upload at least one video in Short #1.');
            return;
        }

        if (!studioData.globals.voice) {
            alert('Reference Voice (SeedVC) is required! Please upload a voice sample in Section 2.');
            return;
        }

        if (!confirm('Start batch shorts processing on Kaggle GPU?')) return;

        launchBtn.disabled = true;
        launchBtn.innerHTML = '<span class="btn-icon">⏳</span> Launching...';

        try {
            const config = {
                kaggle_username: active.username,
                kaggle_key: active.key,
                cooldown_secs: parseInt(cooldownSecs.value, 10) || 30,
                outro_ratio: outroRatio.value
            };

            const res = await apiFetch('/api/launch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });
            const data = await res.json();
            if (!data.success) throw new Error(data.error);

            startPolling();
        } catch (err) {
            alert('Launch failed: ' + err.message);
            launchBtn.disabled = false;
            launchBtn.innerHTML = '<span class="btn-icon">🚀</span> Sync & Start Batch Shorts on Kaggle GPU';
        }
    });

    // --- Polling & Status ---
    function startPolling() {
        if (isPolling) return;
        isPolling = true;
        if (pollInterval) clearInterval(pollInterval);
        pollInterval = setInterval(pollStatus, 4000);
        pollStatus();
    }

    async function pollStatus() {
        try {
            const res = await apiFetch('/api/status');
            const state = await res.json();
            updateStatusDisplay(state);

            if (state.status === 'complete' || state.status === 'error') {
                clearInterval(pollInterval);
                isPolling = false;
                launchBtn.disabled = false;
                launchBtn.innerHTML = '<span class="btn-icon">🚀</span> Sync & Start Batch Shorts on Kaggle GPU';
            }
        } catch (err) {
            console.error('Polling error:', err);
        }
    }

    function updateStatusDisplay(state) {
        statusBadge.textContent = (state.status || 'IDLE').toUpperCase();
        statusBadge.className = 'status-badge ' + (state.status || 'idle');
        statusMessage.textContent = state.message || '';
        progressBar.style.width = (state.progress || 0) + '%';

        if (state.logs && state.logs.length > 0) {
            terminalLogs.textContent = state.logs.join('\n');
            terminalLogs.scrollTop = terminalLogs.scrollHeight;
        }

        if (state.status === 'complete' && state.output_file) {
            downloadBtn.classList.remove('hidden');
        } else {
            downloadBtn.classList.add('hidden');
        }
    }

    clearLogBtn.addEventListener('click', () => {
        terminalLogs.textContent = '';
    });

    // Initial load
    loadStudioState();
});
