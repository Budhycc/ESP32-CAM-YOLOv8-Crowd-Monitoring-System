// ==========================================
// Dashboard Configuration & Variables
// ==========================================
const WS_URL = `ws://${window.location.hostname || '127.0.0.1'}:8765/ws/dashboard`;
let ws;
let reconnectInterval = 3000;

// Store state per camera
const cameraState = {};
let currentRooms = [];
let activeEsps = [];

// Global DOM
const els = {
    connectionDot: document.getElementById('connection-dot'),
    connectionStatus: document.getElementById('connection-status'),
    camerasContainer: document.getElementById('cameras-container'),
    historyList: document.getElementById('history-list'),
    hwBadge: document.getElementById('hw-badge'),
    btnSettings: document.getElementById('btn-settings'),
    settingsModal: document.getElementById('settings-modal'),
    btnCloseModal: document.getElementById('btn-close-modal'),
    btnSaveRoom: document.getElementById('btn-save-room'),
    inputRoomId: document.getElementById('input-room-id'),
    inputCapacity: document.getElementById('input-capacity'),
    inputEsp32Id: document.getElementById('input-esp32-id'),
    settingsRoomList: document.getElementById('settings-room-list'),
    activeEspsList: document.getElementById('active-esps-list')
};

// ==========================================
// Initialization & WebSocket Connection
// ==========================================
function init() {
    connectWebSocket();
    setupModalEvents();
    // Start global monitor loop
    setInterval(checkCameraStatus, 1000);
}

function setupModalEvents() {
    els.btnSettings.addEventListener('click', () => {
        els.settingsModal.classList.remove('hidden');
    });
    els.btnCloseModal.addEventListener('click', () => {
        els.settingsModal.classList.add('hidden');
    });
    els.btnSaveRoom.addEventListener('click', () => {
        const roomId = els.inputRoomId.value.trim();
        const capacity = parseInt(els.inputCapacity.value);
        const esp32Id = els.inputEsp32Id.value.trim();
        if (roomId && !isNaN(capacity)) {
            ws.send(JSON.stringify({
                action: 'add_room',
                room_id: roomId,
                capacity: capacity,
                esp32_id: esp32Id
            }));
            els.inputRoomId.value = '';
            els.inputCapacity.value = '';
            els.inputEsp32Id.value = '';
        }
    });
}

function connectWebSocket() {
    console.log(`Connecting to WebSocket: ${WS_URL}`);
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        console.log("WebSocket Connected");
        els.connectionDot.classList.add('online');
        els.connectionStatus.textContent = 'Connected';
        els.connectionStatus.style.color = 'var(--text-main)';
    };

    ws.onclose = () => {
        console.log("WebSocket Disconnected. Reconnecting...");
        els.connectionDot.classList.remove('online');
        els.connectionStatus.textContent = 'Disconnected';
        els.connectionStatus.style.color = 'var(--status-offline)';
        setTimeout(connectWebSocket, reconnectInterval);
    };

    ws.onerror = (error) => {
        console.error("WebSocket Error:", error);
        ws.close();
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleIncomingData(data);
        } catch (e) {
            console.error("Error parsing message:", e);
        }
    };
}

// ==========================================
// Data Handling
// ==========================================
function handleIncomingData(data) {
    if (data.type === 'init_state') {
        updateStaticInfo(data);
        if (data.rooms) {
            currentRooms = data.rooms;
            renderRoomList(currentRooms);
            data.rooms.forEach(room => {
                ensureCameraCard(room.room_id, { capacity: room.capacity });
            });
        }
        if (data.active_esps) {
            activeEsps = data.active_esps;
        }
        renderActiveEsps();
        if (data.history) renderHistory(data.history);
    } 
    else if (data.type === 'room_config_update') {
        if (data.rooms) {
            currentRooms = data.rooms;
            renderRoomList(currentRooms);
            renderActiveEsps();
            
            const newRoomIds = new Set(data.rooms.map(r => r.room_id));
            const mappedEsps = new Set(data.rooms.map(r => r.esp32_id).filter(id => id));
            
            // Remove deleted rooms from UI and assigned ESPs
            for (const camId in cameraState) {
                let shouldRemove = false;
                if (camId.startsWith("Unassigned (")) {
                    const espId = camId.slice(12, -1);
                    if (mappedEsps.has(espId)) {
                        shouldRemove = true;
                    }
                } else if (!newRoomIds.has(camId)) {
                    shouldRemove = true;
                }

                if (shouldRemove) {
                    const card = document.getElementById(`card-${camId}`);
                    if (card) card.remove();
                    delete cameraState[camId];
                }
            }

            // Update capacity for existing cards or create new ones
            data.rooms.forEach(room => {
                if (cameraState[room.room_id]) {
                    cameraState[room.room_id].capacity = room.capacity;
                    document.getElementById(`capacity-${room.room_id}`).textContent = room.capacity;
                } else {
                    ensureCameraCard(room.room_id, { capacity: room.capacity });
                }
            });
        }
    }
    else if (data.type === 'active_esps_update') {
        if (data.active_esps) {
            activeEsps = data.active_esps;
            renderActiveEsps();
        }
    }
    else if (data.type === 'detection_update') {
        const camId = data.kamera_id;
        ensureCameraCard(camId, data);
        updateCameraUI(camId, data);
        addHistoryItem(data);
    }
}

function renderRoomList(rooms) {
    els.settingsRoomList.innerHTML = '';
    rooms.forEach(room => {
        const espText = room.esp32_id ? `<br><small style="color:var(--text-muted)">Mapped to: ${room.esp32_id}</small>` : '';
        const li = document.createElement('li');
        li.innerHTML = `
            <span><strong>${room.room_id}</strong> (Cap: ${room.capacity})${espText}</span>
            <button class="btn-danger" onclick="deleteRoom('${room.room_id}')">Delete</button>
        `;
        els.settingsRoomList.appendChild(li);
    });
}

function renderActiveEsps() {
    if (!els.activeEspsList) return;
    els.activeEspsList.innerHTML = '';
    
    const mappedEsps = new Set(currentRooms.map(r => r.esp32_id).filter(id => id));
    const unassigned = activeEsps.filter(id => id !== "Unknown" && !mappedEsps.has(id));

    if (unassigned.length === 0) {
        els.activeEspsList.innerHTML = '<li style="color:var(--text-muted)">No unassigned ESP32s connected.</li>';
        return;
    }

    unassigned.forEach(id => {
        const li = document.createElement('li');
        li.style.cursor = 'pointer';
        li.innerHTML = `
            <span><strong>${id}</strong> <small style="color:var(--accent-color)">(Click to assign)</small></span>
        `;
        li.addEventListener('click', () => {
            els.inputEsp32Id.value = id;
            els.inputRoomId.focus();
        });
        els.activeEspsList.appendChild(li);
    });
}

window.deleteRoom = function(roomId) {
    if (confirm(`Delete configuration for room: ${roomId}?`)) {
        ws.send(JSON.stringify({
            action: 'delete_room',
            room_id: roomId
        }));
    }
}

function updateStaticInfo(data) {
    if (data.device) {
        if (els.hwBadge) {
            els.hwBadge.textContent = 'YOLOv8 ' + data.device;
            if (data.device.includes('CUDA') || data.device.includes('GPU')) {
                els.hwBadge.style.background = 'rgba(16, 185, 129, 0.4)';
                els.hwBadge.style.color = '#ffffff'; // Pure white text
                els.hwBadge.style.borderColor = 'rgba(16, 185, 129, 0.8)';
                els.hwBadge.style.textShadow = 'none';
            } else {
                els.hwBadge.style.background = 'rgba(239, 68, 68, 0.4)'; // Slightly darker red background
                els.hwBadge.style.color = '#ffffff'; // Pure white text
                els.hwBadge.style.borderColor = 'rgba(239, 68, 68, 0.8)';
                els.hwBadge.style.textShadow = 'none';
            }
        }
    }
}

// ==========================================
// Camera Card Management
// ==========================================
function ensureCameraCard(camId, data) {
    if (cameraState[camId]) return; // already exists

    // Initialize state
    cameraState[camId] = {
        lastFrameTime: Date.now(),
        frameCount: 0,
        fps: 0,
        capacity: data.kapasitas || data.capacity || 0
    };

    // Create DOM element
    const cardHtml = `
        <div class="camera-card glass-panel fade-in" id="card-${camId}">
            <div class="panel-header">
                <h2><i class='bx bx-broadcast'></i> Live Feed</h2>
                <span class="badge" id="camera-id-${camId}">${camId}</span>
            </div>
            
            <div class="feed-container">
                <img id="video-feed-${camId}" src="" alt="Waiting for stream..." class="hidden">
                <div id="feed-placeholder-${camId}" class="placeholder">
                    <i class='bx bx-sleepy'></i>
                    <p>No video stream</p>
                </div>
            </div>
            
            <div class="feed-meta">
                <span id="timestamp-${camId}"><i class='bx bx-time-five'></i> --:--:--</span>
                <span id="fps-${camId}"><i class='bx bx-tachometer'></i> 0 FPS</span>
            </div>

            <!-- Stats inside card -->
            <div class="stats-section">
                <div class="metrics-grid">
                    <div class="glass-card metric-card" style="padding: 1rem;">
                        <div class="metric-icon" style="width: 35px; height: 35px; font-size: 1.2rem;"><i class='bx bx-group'></i></div>
                        <div class="metric-data">
                            <h4>Person Count</h4>
                            <div class="value" style="font-size: 1.2rem;"><span id="person-count-${camId}">0</span> / <span id="capacity-${camId}">${cameraState[camId].capacity}</span></div>
                        </div>
                    </div>
                    
                    <div class="glass-card status-card" id="status-card-${camId}" data-status="UNKNOWN" style="padding: 1rem;">
                        <h3 style="font-size: 0.8rem;">Status</h3>
                        <div class="status-value" id="crowd-status-${camId}" style="font-size: 1.5rem;">UNKNOWN</div>
                    </div>
                </div>

                <div class="glass-card capacity-card" style="padding: 1rem;">
                    <div class="card-header" style="margin-bottom: 0.5rem;">
                        <h3 style="font-size: 0.8rem;">Room Capacity</h3>
                        <span id="capacity-percentage-${camId}" style="font-size: 0.8rem;">0%</span>
                    </div>
                    <div class="progress-bar-container" style="height: 8px;">
                        <div class="progress-bar" id="capacity-bar-${camId}"></div>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    // Append to container
    els.camerasContainer.insertAdjacentHTML('beforeend', cardHtml);
}

function updateCameraUI(camId, data) {
    const state = cameraState[camId];
    state.frameCount++;
    state.lastFrameTime = Date.now();
    state.capacity = data.kapasitas || state.capacity;

    // Update DOM
    document.getElementById(`capacity-${camId}`).textContent = state.capacity;
    document.getElementById(`person-count-${camId}`).textContent = data.jumlah_orang;
    document.getElementById(`timestamp-${camId}`).innerHTML = `<i class='bx bx-time-five'></i> ${data.waktu}`;
    
    // Status Logic
    const statusStr = data.status || 'UNKNOWN';
    document.getElementById(`crowd-status-${camId}`).textContent = statusStr;
    const statusCard = document.getElementById(`status-card-${camId}`);
    if (statusCard) statusCard.setAttribute('data-status', statusStr);
    
    // Capacity Progress Bar
    const capacity = state.capacity || 1;
    let percentage = (data.jumlah_orang / capacity) * 100;
    if(percentage > 100) percentage = 100;
    
    document.getElementById(`capacity-percentage-${camId}`).textContent = `${Math.round(percentage)}%`;
    const capBar = document.getElementById(`capacity-bar-${camId}`);
    if (capBar) {
        capBar.style.width = `${percentage}%`;
        if (statusStr === 'Normal') capBar.style.backgroundColor = 'var(--status-safe)';
        else if (statusStr === 'Waspada') capBar.style.backgroundColor = 'var(--status-warning)';
        else if (statusStr === 'Padat') capBar.style.backgroundColor = 'var(--status-danger)';
    }

    // Video frame
    if (data.frame_b64 && data.frame_b64.length > 0) {
        const videoEl = document.getElementById(`video-feed-${camId}`);
        const phEl = document.getElementById(`feed-placeholder-${camId}`);
        if (videoEl && phEl) {
            videoEl.src = `data:image/jpeg;base64,${data.frame_b64}`;
            videoEl.classList.remove('hidden');
            phEl.classList.add('hidden');
        }
    }
}

// ==========================================
// History Log Rendering
// ==========================================
function renderHistory(historyArray) {
    if (els.historyList) {
        els.historyList.innerHTML = '';
        historyArray.forEach(item => addHistoryItem(item, false));
    }
}

function addHistoryItem(item, prepend = true) {
    if (!els.historyList) return;
    
    const div = document.createElement('div');
    div.className = `history-item status-${item.status}`;
    
    const timeOnly = item.waktu.split(' ')[1] || item.waktu; // extract HH:MM:SS
    
    div.innerHTML = `
        <div class="hist-info">
            <span class="hist-time">${timeOnly} <b style="color:var(--accent-primary)">[${item.kamera_id}]</b></span>
            <span class="hist-desc">Status: ${item.status}</span>
        </div>
        <div class="hist-count">
            <i class='bx bx-user'></i> ${item.jumlah_orang}
        </div>
    `;
    
    if (prepend) {
        els.historyList.prepend(div);
        // Keep only last 50 items in DOM globally
        if (els.historyList.children.length > 50) {
            els.historyList.removeChild(els.historyList.lastChild);
        }
    } else {
        els.historyList.appendChild(div);
    }
}

// ==========================================
// Utils: Status Monitor & FPS Counter
// ==========================================
function checkCameraStatus() {
    for (const [camId, state] of Object.entries(cameraState)) {
        // Update FPS display
        const fpsEl = document.getElementById(`fps-${camId}`);
        if (fpsEl) {
            fpsEl.innerHTML = `<i class='bx bx-tachometer'></i> ${state.frameCount} FPS`;
            state.frameCount = 0;
        }
        
        // Check offline status
        if (Date.now() - state.lastFrameTime > 3000) {
            const videoEl = document.getElementById(`video-feed-${camId}`);
            const phEl = document.getElementById(`feed-placeholder-${camId}`);
            if (videoEl) videoEl.classList.add('hidden');
            if (phEl) phEl.classList.remove('hidden');
            
            // Mark status as offline
            const sc = document.getElementById(`status-card-${camId}`);
            if (sc) sc.setAttribute('data-status', 'UNKNOWN');
            const cs = document.getElementById(`crowd-status-${camId}`);
            if (cs) cs.textContent = 'OFFLINE';
        }
    }
}

window.onload = init;
