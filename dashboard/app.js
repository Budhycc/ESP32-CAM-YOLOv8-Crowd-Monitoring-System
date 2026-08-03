// ==========================================
// Dashboard Configuration & Variables
// ==========================================
const WS_URL = `ws://${window.location.hostname || '127.0.0.1'}:8765/ws/dashboard`;
let ws;
let reconnectInterval = 3000;
let lastFrameTime = Date.now();
let frameCount = 0;
let fpsInterval;

// DOM Elements
const els = {
    connectionDot: document.getElementById('connection-dot'),
    connectionStatus: document.getElementById('connection-status'),
    videoId: document.getElementById('camera-id'),
    videoFeed: document.getElementById('video-feed'),
    feedPlaceholder: document.getElementById('feed-placeholder'),
    timestamp: document.getElementById('timestamp'),
    fps: document.getElementById('fps'),
    statusCard: document.getElementById('status-card'),
    crowdStatus: document.getElementById('crowd-status'),
    statusDesc: document.getElementById('status-desc'),
    personCount: document.getElementById('person-count'),
    capacity: document.getElementById('capacity'),
    avgConfidence: document.getElementById('avg-confidence'),
    capacityPercentage: document.getElementById('capacity-percentage'),
    capacityBar: document.getElementById('capacity-bar'),
    historyList: document.getElementById('history-list')
};

// ==========================================
// Initialization & WebSocket Connection
// ==========================================
function init() {
    connectWebSocket();
    startFPSCounter();
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
        if(data.latest) updateUI(data.latest);
        if(data.history) renderHistory(data.history);
    } 
    else if (data.type === 'detection_update') {
        updateUI(data);
        updateVideoFrame(data.frame_b64);
        addHistoryItem(data);
        
        // Update FPS Counters
        frameCount++;
        lastFrameTime = Date.now();
    }
}

function updateStaticInfo(data) {
    els.videoId.textContent = data.kamera_id || 'CAM-01';
    els.capacity.textContent = data.kapasitas || 0;
}

function updateUI(data) {
    // Basic Metrics
    els.personCount.textContent = data.jumlah_orang;
    els.avgConfidence.textContent = Math.round(data.confidence_rata2 * 100);
    els.timestamp.innerHTML = `<i class='bx bx-time-five'></i> ${data.waktu}`;
    
    // Status Logic
    const statusStr = data.status || 'UNKNOWN';
    els.crowdStatus.textContent = statusStr;
    els.statusCard.setAttribute('data-status', statusStr);
    
    if(statusStr === 'Normal') {
        els.statusDesc.textContent = 'Crowd level is well within limits.';
    } else if(statusStr === 'Waspada') {
        els.statusDesc.textContent = 'Crowd is nearing maximum capacity.';
    } else if(statusStr === 'Padat') {
        els.statusDesc.textContent = 'Room capacity exceeded. Action required!';
    } else {
        els.statusDesc.textContent = 'Monitoring...';
    }

    // Capacity Progress Bar
    const capacity = data.kapasitas || 1;
    let percentage = (data.jumlah_orang / capacity) * 100;
    if(percentage > 100) percentage = 100;
    
    els.capacityPercentage.textContent = `${Math.round(percentage)}%`;
    els.capacityBar.style.width = `${percentage}%`;
    
    // Progress Bar Color based on status
    if (statusStr === 'Normal') els.capacityBar.style.backgroundColor = 'var(--status-safe)';
    else if (statusStr === 'Waspada') els.capacityBar.style.backgroundColor = 'var(--status-warning)';
    else if (statusStr === 'Padat') els.capacityBar.style.backgroundColor = 'var(--status-danger)';
}

function updateVideoFrame(base64String) {
    if (base64String && base64String.length > 0) {
        els.videoFeed.src = `data:image/jpeg;base64,${base64String}`;
        els.videoFeed.classList.remove('hidden');
        els.feedPlaceholder.classList.add('hidden');
    }
}

// ==========================================
// History Log Rendering
// ==========================================
function renderHistory(historyArray) {
    els.historyList.innerHTML = '';
    historyArray.forEach(item => addHistoryItem(item, false));
}

function addHistoryItem(item, prepend = true) {
    // Only add if status changes or it's a significant event to avoid spamming
    // For this implementation, we add everything but cap the list
    
    const div = document.createElement('div');
    div.className = `history-item status-${item.status}`;
    
    const timeOnly = item.waktu.split(' ')[1] || item.waktu; // extract HH:MM:SS
    
    div.innerHTML = `
        <div class="hist-info">
            <span class="hist-time">${timeOnly}</span>
            <span class="hist-desc">Status: ${item.status}</span>
        </div>
        <div class="hist-count">
            <i class='bx bx-user'></i> ${item.jumlah_orang}
        </div>
    `;
    
    if (prepend) {
        els.historyList.prepend(div);
        // Keep only last 20 items in DOM
        if (els.historyList.children.length > 20) {
            els.historyList.removeChild(els.historyList.lastChild);
        }
    } else {
        els.historyList.appendChild(div);
    }
}

// ==========================================
// Utils: FPS Counter
// ==========================================
function startFPSCounter() {
    fpsInterval = setInterval(() => {
        els.fps.innerHTML = `<i class='bx bx-tachometer'></i> ${frameCount} FPS`;
        frameCount = 0; // Reset every second
        
        // If no frames received in last 5 seconds, clear the screen
        if (Date.now() - lastFrameTime > 5000) {
            els.videoFeed.classList.add('hidden');
            els.feedPlaceholder.classList.remove('hidden');
        }
    }, 1000);
}

// Start App
window.onload = init;
