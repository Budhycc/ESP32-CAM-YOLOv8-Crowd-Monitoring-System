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
let globalHistoryData = [];

// Global DOM
const els = {
    connectionDot: document.getElementById('connection-dot'),
    connectionStatus: document.getElementById('connection-status'),
    camerasContainer: document.getElementById('cameras-container'),
    historyList: document.getElementById('history-list'),
    hwBadge: document.getElementById('hw-badge'),
    btnSettings: document.getElementById('btn-settings'),
    btnDownloadReport: document.getElementById('btn-download-report'),
    btnViewReport: document.getElementById('btn-view-report'),
    reportModal: document.getElementById('report-modal'),
    btnCloseReport: document.getElementById('btn-close-report'),
    fullHistoryList: document.getElementById('full-history-list'),
    settingsModal: document.getElementById('settings-modal'),
    btnCloseModal: document.getElementById('btn-close-modal'),
    btnSaveRoom: document.getElementById('btn-save-room'),
    btnCancelEdit: document.getElementById('btn-cancel-edit'),
    formTitle: document.getElementById('form-title'),
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

let editingOldRoomId = null;

function resetForm() {
    els.inputRoomId.value = '';
    els.inputCapacity.value = '';
    els.inputEsp32Id.value = '';
    editingOldRoomId = null;
    
    // Reset UI text & buttons
    els.formTitle.textContent = 'Add Room';
    els.btnSaveRoom.textContent = 'Save';
    els.btnCancelEdit.classList.add('hidden');
}

function setupModalEvents() {
    els.btnSettings.addEventListener('click', () => {
        els.settingsModal.classList.remove('hidden');
    });
    if (els.btnDownloadReport) {
        els.btnDownloadReport.addEventListener('click', downloadHistoryReport);
    }
    if (els.btnViewReport) {
        els.btnViewReport.addEventListener('click', () => {
            renderFullHistoryReport();
            els.reportModal.classList.remove('hidden');
        });
    }
    if (els.btnCloseReport) {
        els.btnCloseReport.addEventListener('click', () => {
            els.reportModal.classList.add('hidden');
        });
    }
    els.btnCloseModal.addEventListener('click', () => {
        els.settingsModal.classList.add('hidden');
        resetForm();
    });
    els.btnCancelEdit.addEventListener('click', () => {
        resetForm();
    });
    els.btnSaveRoom.addEventListener('click', () => {
        const roomId = els.inputRoomId.value.trim();
        const capacity = parseInt(els.inputCapacity.value);
        const esp32Id = els.inputEsp32Id.value.trim();
        if (roomId && !isNaN(capacity)) {
            ws.send(JSON.stringify({
                action: 'add_room',
                room_id: roomId,
                old_room_id: editingOldRoomId,
                capacity: capacity,
                esp32_id: esp32Id
            }));
            resetForm();
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

// Force reconnect when user switches back to the tab (bypasses browser background throttling)
document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
        if (!ws || ws.readyState === WebSocket.CLOSED) {
            console.log("Tab is visible again. Forcing reconnect...");
            connectWebSocket();
        }
    }
});

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
        if (data.history) {
            globalHistoryData = data.history.slice();
            renderHistory(data.history);
        }
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
    } else if (data.type === "camera_sleep") {
        const camId = data.kamera_id;
        if (cameraState[camId]) {
            cameraState[camId].isSleeping = true;
            const videoEl = document.getElementById(`video-feed-${camId}`);
            const phEl = document.getElementById(`feed-placeholder-${camId}`);
            const cs = document.getElementById(`crowd-status-${camId}`);
            
            if (videoEl) videoEl.classList.add('hidden');
            if (phEl) {
                phEl.classList.remove('hidden');
                phEl.innerHTML = `<i class='bx bx-sleepy'></i><p>STANDBY (Ruangan Kosong)</p>`;
            }
            if (cs) cs.textContent = 'STANDBY';
        }
    }
    else if (data.type === 'detection_update') {
        const camId = data.kamera_id;
        
        // Prevent race condition: ignore stale "Unassigned" frames if the ESP is already mapped
        if (camId.startsWith("Unassigned (")) {
            const espId = camId.slice(12, -1);
            if (currentRooms.some(r => r.esp32_id === espId)) {
                return; // Skip rendering this frame, it's a ghost from before the assignment
            }
        } else {
            // It's a named room. Ensure the room actually still exists!
            // If it was just deleted, a stale frame might try to resurrect it.
            if (!currentRooms.some(r => r.room_id === camId)) {
                return; // Skip rendering this frame, it's a ghost from before deletion
            }
        }
        
        ensureCameraCard(camId, data);
        updateCameraUI(camId, data);
        
        const currentStatus = data.status || 'UNKNOWN';
        if (cameraState[camId].lastStatus !== currentStatus) {
            cameraState[camId].lastStatus = currentStatus;
            globalHistoryData.unshift(data);
            addHistoryItem(data);
        }
    }
}

window.editRoom = function(roomId, capacity, esp32Id) {
    editingOldRoomId = roomId;
    els.inputRoomId.value = roomId;
    els.inputCapacity.value = capacity;
    els.inputEsp32Id.value = esp32Id === 'null' || !esp32Id ? '' : esp32Id;
    
    // Update UI text
    els.formTitle.textContent = `Edit Room`;
    els.btnSaveRoom.textContent = 'Update';
    els.btnCancelEdit.classList.remove('hidden');
    
    els.inputRoomId.focus();
}

function renderRoomList(rooms) {
    els.settingsRoomList.innerHTML = '';
    rooms.forEach(room => {
        const espText = room.esp32_id ? `<br><small style="color:var(--text-muted)">Mapped to: ${room.esp32_id}</small>` : '';
        const safeEspId = room.esp32_id ? `'${room.esp32_id}'` : 'null';
        const li = document.createElement('li');
        li.innerHTML = `
            <span><strong>${room.room_id}</strong> (Cap: ${room.capacity})${espText}</span>
            <div style="display: flex; gap: 0.5rem;">
                <button class="btn-primary" onclick="editRoom('${room.room_id}', ${room.capacity}, ${safeEspId})" style="padding: 0.3rem 0.8rem; font-size: 0.8rem;">Edit</button>
                <button class="btn-danger" onclick="deleteRoom('${room.room_id}')" style="padding: 0.3rem 0.8rem; font-size: 0.8rem;">Delete</button>
            </div>
        `;
        li.style.display = 'flex';
        li.style.justifyContent = 'space-between';
        li.style.alignItems = 'center';
        els.settingsRoomList.appendChild(li);
    });
}

function renderActiveEsps() {
    if (!els.activeEspsList) return;
    els.activeEspsList.innerHTML = '';
    
    const mappedEsps = new Set(currentRooms.map(r => r.esp32_id).filter(id => id));

    if (activeEsps.length === 0) {
        els.activeEspsList.innerHTML = '<li style="color:var(--text-muted)">No ESP32s connected.</li>';
        return;
    }

    activeEsps.forEach(id => {
        if (id === "Unknown") return;
        
        const isMapped = mappedEsps.has(id);
        const li = document.createElement('li');
        li.style.cursor = 'pointer';
        
        if (isMapped) {
            const roomName = currentRooms.find(r => r.esp32_id === id)?.room_id || 'Unknown';
            li.innerHTML = `
                <span><strong>${id}</strong> <small style="color:var(--status-warning)">(Assigned to ${roomName})</small></span>
            `;
        } else {
            li.innerHTML = `
                <span><strong>${id}</strong> <small style="color:var(--accent-color)">(Click to assign)</small></span>
            `;
        }

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

    const room = currentRooms.find(r => r.room_id === camId);
    let savedBbox = true;
    let savedRes = 'VGA';
    let savedFps = 0;
    
    if (room) {
        if (room.show_bbox !== undefined) savedBbox = (room.show_bbox === 1 || room.show_bbox === true);
        if (room.resolution) savedRes = room.resolution;
        if (room.fps !== undefined && room.fps !== null) savedFps = room.fps;
    } else {
        const lsBbox = localStorage.getItem(`bbox-${camId}`);
        const lsRes = localStorage.getItem(`res-${camId}`);
        const lsFps = localStorage.getItem(`fps-${camId}`);
        savedBbox = lsBbox !== null ? lsBbox === 'true' : true;
        savedRes = lsRes || 'VGA';
        savedFps = lsFps !== null ? parseInt(lsFps) : 0;
    }

    // Initialize state
    cameraState[camId] = {
        lastFrameTime: Date.now(),
        frameCount: 0,
        fps: 0,
        capacity: data.kapasitas || data.capacity || 0,
        lastStatus: null, // Added to track status changes and prevent log spam
        showBbox: savedBbox,
        isSleeping: false
    };

    // Create DOM element
    const cardHtml = `
        <div class="camera-card glass-panel fade-in" id="card-${camId}">
            <div class="panel-header">
                <h2><i class='bx bx-broadcast'></i> Live Feed</h2>
                <div style="display: flex; gap: 10px; align-items: center;">
                    <button class="btn-icon" onclick="toggleFullscreen('${camId}')" title="Full Screen"><i class='bx bx-fullscreen'></i></button>
                    <span class="badge" id="camera-id-${camId}">${camId}</span>
                </div>
            </div>
            
            <div class="feed-container" id="feed-container-${camId}" style="position: relative;">
                <img id="video-feed-${camId}" src="" alt="Waiting for stream..." class="hidden" style="width: 100%; height: auto; display: block;">
                <canvas id="bbox-canvas-${camId}" class="hidden" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none;"></canvas>
                <div id="feed-placeholder-${camId}" class="placeholder">
                    <i class='bx bx-sleepy'></i>
                    <p>No video stream</p>
                </div>
            </div>
            
            <div class="feed-meta" style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <span id="timestamp-${camId}"><i class='bx bx-time-five'></i> --:--:--</span>
                    <span id="fps-${camId}"><i class='bx bx-tachometer'></i> 0 FPS</span>
                    <span id="latency-${camId}"><i class='bx bx-stopwatch'></i> -- ms</span>
                    <span id="resolution-${camId}"><i class='bx bx-expand'></i> --x--</span>
                </div>
                <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 4px;">
                    <label style="display: flex; align-items: center; cursor: pointer; font-size: 0.8rem; gap: 5px; color: var(--text-secondary);">
                        <input type="checkbox" id="toggle-bbox-${camId}" ${cameraState[camId].showBbox ? 'checked' : ''} onchange="cameraState['${camId}'].showBbox = this.checked; updateBboxSetting('${camId}', this.checked);"> Tampilkan Box
                    </label>
                    <div style="display: flex; gap: 5px; flex-wrap: wrap;">
                        <select id="res-select-${camId}" onchange="changeResolution('${camId}', this.value)" style="font-size: 0.8rem; padding: 2px 5px; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); color: white; border-radius: 4px; outline: none; cursor: pointer;">
                            <option style="color: black" value="QVGA" ${savedRes === 'QVGA' ? 'selected' : ''}>QVGA (320x240)</option>
                            <option style="color: black" value="VGA" ${savedRes === 'VGA' ? 'selected' : ''}>VGA (640x480)</option>
                            <option style="color: black" value="SVGA" ${savedRes === 'SVGA' ? 'selected' : ''}>SVGA (800x600)</option>
                            <option style="color: black" value="XGA" ${savedRes === 'XGA' ? 'selected' : ''}>XGA (1024x768)</option>
                            <option style="color: black" value="HD" ${savedRes === 'HD' ? 'selected' : ''}>HD (1280x720)</option>
                        </select>
                        <select id="fps-select-${camId}" onchange="changeFps('${camId}', this.value)" style="font-size: 0.8rem; padding: 2px 5px; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); color: white; border-radius: 4px; outline: none; cursor: pointer;">
                            <option style="color: black" value="0" ${savedFps === 0 ? 'selected' : ''}>⚡ Dinamis (Max)</option>
                            <option style="color: black" value="2" ${savedFps === 2 ? 'selected' : ''}>2 FPS</option>
                            <option style="color: black" value="5" ${savedFps === 5 ? 'selected' : ''}>5 FPS</option>
                            <option style="color: black" value="10" ${savedFps === 10 ? 'selected' : ''}>10 FPS</option>
                            <option style="color: black" value="15" ${savedFps === 15 ? 'selected' : ''}>15 FPS</option>
                            <option style="color: black" value="20" ${savedFps === 20 ? 'selected' : ''}>20 FPS</option>
                            <option style="color: black" value="25" ${savedFps === 25 ? 'selected' : ''}>25 FPS</option>
                        </select>
                    </div>
                </div>
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
    state.lastFrameTime = Date.now();
    state.frameCount++;
    state.isSleeping = false;
    state.capacity = data.kapasitas || state.capacity;

    // Update DOM
    document.getElementById(`capacity-${camId}`).textContent = state.capacity;
    document.getElementById(`person-count-${camId}`).textContent = data.jumlah_orang;
    document.getElementById(`timestamp-${camId}`).innerHTML = `<i class='bx bx-time-five'></i> ${data.waktu}`;
    if (data.latensi) {
        const latEl = document.getElementById(`latency-${camId}`);
        if (latEl) latEl.innerHTML = `<i class='bx bx-stopwatch'></i> ${data.latensi} ms`;
    }
    
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
        const canvasEl = document.getElementById(`bbox-canvas-${camId}`);
        
        if (videoEl && phEl) {
            videoEl.src = `data:image/jpeg;base64,${data.frame_b64}`;
            videoEl.classList.remove('hidden');
            phEl.classList.add('hidden');
            
            const handleImageLoad = () => {
                if (!videoEl.naturalWidth) return;
                
                // Update resolution text
                const resEl = document.getElementById(`resolution-${camId}`);
                if (resEl) {
                    resEl.innerHTML = `<i class='bx bx-expand'></i> ${videoEl.naturalWidth}x${videoEl.naturalHeight}`;
                }
                
                // Draw Bounding Boxes on Canvas
                if (canvasEl && state.showBbox) {
                    canvasEl.classList.remove('hidden');
                    const ctx = canvasEl.getContext('2d');
                    canvasEl.width = videoEl.clientWidth;
                    canvasEl.height = videoEl.clientHeight;
                    ctx.clearRect(0, 0, canvasEl.width, canvasEl.height);
                    
                    const scaleX = canvasEl.width / videoEl.naturalWidth;
                    const scaleY = canvasEl.height / videoEl.naturalHeight;
                    
                    if (data.deteksi_detail && data.deteksi_detail.length > 0) {
                        data.deteksi_detail.forEach(person => {
                            const [x1, y1, x2, y2] = person.bbox;
                            const conf = person.confidence;
                            
                            const rectX = x1 * scaleX;
                            const rectY = y1 * scaleY;
                            const rectW = (x2 - x1) * scaleX;
                            const rectH = (y2 - y1) * scaleY;
                            
                            ctx.strokeStyle = '#00ff00';
                            ctx.lineWidth = 2;
                            ctx.strokeRect(rectX, rectY, rectW, rectH);
                            
                            ctx.fillStyle = '#00ff00';
                            ctx.font = '14px Arial';
                            ctx.fillText(`Person ${conf.toFixed(2)}`, rectX, Math.max(rectY - 5, 15));
                        });
                    }
                } else if (canvasEl) {
                    canvasEl.classList.add('hidden');
                }
            };
            
            if (videoEl.complete) {
                handleImageLoad();
            } else {
                videoEl.onload = handleImageLoad;
            }
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
    
    const tr = document.createElement('tr');
    tr.className = `history-row`;
    
    const timeOnly = item.waktu.split(' ')[1] || item.waktu;
    let statusClass = item.status.toLowerCase();

    tr.innerHTML = `
        <td class="col-time"><i class='bx bx-time-five'></i> ${timeOnly}</td>
        <td class="col-room">${item.kamera_id}</td>
        <td class="col-status">
            <span class="hist-status-badge badge-${statusClass}">${item.status}</span>
        </td>
        <td class="col-count"><i class='bx bx-user'></i> ${item.jumlah_orang}</td>
    `;
    
    if (prepend) {
        els.historyList.prepend(tr);
        // Keep only last 50 items in DOM globally
        if (els.historyList.children.length > 50) {
            els.historyList.removeChild(els.historyList.lastChild);
        }
    } else {
        els.historyList.appendChild(tr);
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
            // Check if it's intentionally sleeping
            if (state.isSleeping) {
                continue; // It's in standby, let it be. UI already updated.
            }

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

function downloadHistoryReport() {
    if (globalHistoryData.length === 0) {
        alert("Tidak ada data riwayat untuk diunduh.");
        return;
    }
    
    let csvContent = "data:text/csv;charset=utf-8,";
    csvContent += "Waktu,Ruangan (Kamera ID),Jumlah Orang,Status,Kapasitas\n";
    
    globalHistoryData.forEach(row => {
        let time = row.waktu || "N/A";
        let camId = (row.kamera_id || "Unknown").replace(/,/g, " ");
        let count = row.jumlah_orang || 0;
        let status = row.status || "UNKNOWN";
        let capacity = row.kapasitas || cameraState[camId]?.capacity || 0;
        
        csvContent += `${time},${camId},${count},${status},${capacity}\n`;
    });
    
    const csvBlob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(csvBlob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    
    const dateStr = new Date().toISOString().split('T')[0];
    link.setAttribute("download", `Laporan_Keramaian_${dateStr}.csv`);
    
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

function renderFullHistoryReport() {
    if (!els.fullHistoryList) return;
    els.fullHistoryList.innerHTML = '';
    
    if (globalHistoryData.length === 0) {
        els.fullHistoryList.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 2rem; color: var(--text-muted);">Tidak ada data riwayat tersedia.</td></tr>';
        return;
    }

    globalHistoryData.forEach(item => {
        const tr = document.createElement('tr');
        tr.className = `history-row status-${item.status}`;
        
        let time = item.waktu || "N/A";
        let camId = item.kamera_id || "Unknown";
        let status = item.status || "UNKNOWN";
        let count = item.jumlah_orang || 0;
        let capacity = item.kapasitas || cameraState[camId]?.capacity || 0;
        
        let statusClass = status.toLowerCase();

        tr.innerHTML = `
            <td class="col-time"><i class='bx bx-time-five'></i> ${time}</td>
            <td class="col-room">${camId}</td>
            <td class="col-status">
                <span class="hist-status-badge badge-${statusClass}">${status}</span>
            </td>
            <td class="col-count"><i class='bx bx-user'></i> ${count}</td>
            <td class="col-capacity" style="font-weight: 700; text-align: center; color: var(--text-main);">${capacity}</td>
        `;
        
        els.fullHistoryList.appendChild(tr);
    });
}

window.updateBboxSetting = function(roomId, showBbox) {
    localStorage.setItem(`bbox-${roomId}`, showBbox);
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            action: 'update_bbox',
            room_id: roomId,
            show_bbox: showBbox
        }));
    }
}

window.changeResolution = function(roomId, res) {
    localStorage.setItem(`res-${roomId}`, res);
    const room = currentRooms.find(r => r.room_id === roomId);
    let esp32Id = room ? room.esp32_id : null;
    
    // If it's an unassigned camera, the camId itself contains the esp32_id
    if (roomId.startsWith("Unassigned (")) {
        esp32Id = roomId.slice(12, -1);
    }

    if (ws && ws.readyState === WebSocket.OPEN) {
        const payload = {
            action: 'set_resolution',
            room_id: roomId,
            resolution: res
        };
        if (esp32Id) payload.esp32_id = esp32Id;
        
        ws.send(JSON.stringify(payload));
        console.log(`Sent resolution change: ${res} for Room: ${roomId}, ESP32: ${esp32Id}`);
    } else {
        alert("Cannot change resolution: Not connected to server.");
    }
}

window.changeFps = function(roomId, fpsVal) {
    const parsedFps = parseInt(fpsVal);
    localStorage.setItem(`fps-${roomId}`, parsedFps);
    const room = currentRooms.find(r => r.room_id === roomId);
    let esp32Id = room ? room.esp32_id : null;
    
    if (roomId.startsWith("Unassigned (")) {
        esp32Id = roomId.slice(12, -1);
    }

    if (ws && ws.readyState === WebSocket.OPEN) {
        const payload = {
            action: 'set_fps',
            room_id: roomId,
            fps: parsedFps
        };
        if (esp32Id) payload.esp32_id = esp32Id;
        
        ws.send(JSON.stringify(payload));
        console.log(`Sent FPS change: ${parsedFps} for Room: ${roomId}, ESP32: ${esp32Id}`);
    } else {
        alert("Cannot change FPS: Not connected to server.");
    }
}

document.addEventListener('DOMContentLoaded', init);

// ==========================================
// Fullscreen Management
// ==========================================
function toggleFullscreen(camId) {
    const container = document.getElementById(`card-${camId}`);
    if (!container) return;

    if (!document.fullscreenElement && !document.webkitFullscreenElement && !document.msFullscreenElement) {
        if (container.requestFullscreen) {
            container.requestFullscreen();
        } else if (container.webkitRequestFullscreen) { /* Safari */
            container.webkitRequestFullscreen();
        } else if (container.msRequestFullscreen) { /* IE11 */
            container.msRequestFullscreen();
        }
    } else {
        if (document.exitFullscreen) {
            document.exitFullscreen();
        } else if (document.webkitExitFullscreen) { /* Safari */
            document.webkitExitFullscreen();
        } else if (document.msExitFullscreen) { /* IE11 */
            document.msExitFullscreen();
        }
    }
}
