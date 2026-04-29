// --- INICIALIZAÇÃO ---
const socket = io();
const notificationSound = new Audio('/static/sounds/notification.mp3');
let currentTicketId = null;
let currentContactName = null;

document.addEventListener('DOMContentLoaded', () => {
    // Carrega a aba padrão
    loadTickets('open');

    // Inicia o contador das badges
    updateBadges();
    setInterval(updateBadges, 5000);

    // Desbloqueio de áudio
    document.body.addEventListener('click', () => {
        if (notificationSound.muted) {
            notificationSound.muted = false;
            notificationSound.play().then(() => {
                notificationSound.pause();
                notificationSound.currentTime = 0;
            }).catch(() => {});
        }
    }, { once: true });

    setupUpload();
});

// ==========================================
// UPLOAD (MANTIDO)
// ==========================================
function setupUpload() {
    const btnAttach = document.getElementById('btnAttach');
    const fileInput = document.getElementById('fileInput');

    if (btnAttach && fileInput) {
        btnAttach.addEventListener('click', () => {
            if (currentTicketId) fileInput.click();
        });

        fileInput.addEventListener('change', async () => {
            if (fileInput.files.length === 0 || !currentTicketId) return;

            const file = fileInput.files[0];
            const formData = new FormData();
            formData.append('file', file);

            const icon = btnAttach.querySelector('i');
            const originalIconClass = icon.className;
            icon.className = 'fas fa-spinner fa-spin';

            try {
                const res = await fetch(`/chat/tickets/${currentTicketId}/upload`, { method: 'POST', body: formData });
                if (!res.ok) throw new Error('Falha no upload');
            } catch (e) {
                console.error(e);
                alert('Erro ao enviar arquivo.');
            } finally {
                fileInput.value = '';
                icon.className = originalIconClass;
            }
        });
    }
}

// ==========================================
// FUNÇÕES AUXILIARES
// ==========================================
function formatTime(isoString, short = false) {
    if (!isoString) return '';
    const date = new Date(isoString);

    if (short) {
        return date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    }

    return date.toLocaleString('pt-BR', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit'
    });
}

// ==========================================
// BADGES (CONTADORES) - NOVO
// ==========================================
function updateBadges() {
    fetch('/chat/tickets/counts')
        .then(r => r.json())
        .then(data => {
            const bOpen = document.getElementById('badgeOpen');
            const bPend = document.getElementById('badgePending');

            if (bOpen) {
                bOpen.innerText = data.open;
                bOpen.style.display = data.open > 0 ? 'inline-block' : 'none';
            }
            if (bPend) {
                bPend.innerText = data.pending;
                bPend.style.display = data.pending > 0 ? 'inline-block' : 'none';
            }
        })
        .catch(e => console.error("Erro badge:", e));
}

// ==========================================
// LÓGICA DE TICKETS (ATUALIZADA COM FLAGS)
// ==========================================
async function loadTickets(scope, silent = false) {
    // scope: 'open' (visual) -> api: 'me'
    // scope: 'pending' (visual) -> api: 'pending'

    let apiScope = scope;
    if (scope === 'open') apiScope = 'me';

    if (!silent) {
        document.querySelectorAll('.nav-link').forEach(el => el.classList.remove('active'));
        const links = document.querySelectorAll('.nav-link');
        links.forEach(l => {
            if (l.getAttribute('onclick')?.includes(scope)) l.classList.add('active');
        });
    }

    const listDiv = document.getElementById('ticketsList');
    if (!silent) listDiv.innerHTML = '<p class="text-center mt-3 text-muted small"><i class="fas fa-spinner fa-spin"></i> Carregando...</p>';

    try {
        // MANDA O SCOPE CORRETO PARA A API
        const res = await fetch(`/chat/tickets?scope=${apiScope}`);
        if (res.status === 401 || res.status === 403) { window.location.href = '/login'; return; }

        const tickets = await res.json();
        listDiv.innerHTML = '';

        if (!tickets || tickets.length === 0) {
            listDiv.innerHTML = '<p class="text-center mt-3 small text-muted">Nenhum ticket encontrado.</p>';
            return;
        }

        tickets.forEach(t => {
            const item = document.createElement('div');
            const isActive = currentTicketId && String(currentTicketId) === String(t.id);

            item.id = `ticket-item-${t.id}`;
            item.className = `ticket-item ${isActive ? 'active' : ''}`;
            item.onclick = () => openTicket(t.id, t.contact_name, t.profile_pic);

            // Avatar
            let imgHtml = '';
            if (t.profile_pic && t.profile_pic !== 'null' && t.profile_pic !== '') {
                imgHtml = `<img src="${t.profile_pic}" class="rounded-circle flex-shrink-0" style="width: 45px; height: 45px; object-fit: cover;">`;
            } else {
                const initial = t.contact_name ? t.contact_name.charAt(0).toUpperCase() : '?';
                imgHtml = `<div class="rounded-circle bg-secondary text-white fw-bold d-flex align-items-center justify-content-center flex-shrink-0" style="width: 45px; height: 45px;">${initial}</div>`;
            }

            // Preview MSG
            let lastMsg = t.last_msg_content || '📝 Novo chamado';
            if (lastMsg.includes('/static/') || lastMsg.match(/\.(jpg|png|mp3|ogg|pdf)$/i)) {
                lastMsg = '📎 Mídia/Arquivo';
            }

            // --- FLAGS (NOVO) ---
            let flagsHtml = '';
            // Flag da Fila
            flagsHtml += `<span class="badge me-1" style="background-color: ${t.queue_color}; font-size: 0.65rem; color: #fff;">${t.queue_name}</span>`;

            // Flag do Operador (Se tiver dono e não for eu - útil para admin)
            if (t.operator_name) {
                flagsHtml += `<span class="badge bg-dark me-1" style="font-size: 0.65rem;"><i class="fas fa-headset me-1"></i> ${t.operator_name}</span>`;
            }

            item.innerHTML = `
                <div class="d-flex align-items-center w-100">
                    <div class="me-3 position-relative">${imgHtml}</div>
                    <div class="flex-grow-1 overflow-hidden">
                        <div class="d-flex justify-content-between align-items-center mb-1">
                            <span class="ticket-name text-truncate fw-bold">${t.contact_name}</span>
                            <span class="ticket-date text-muted small">${formatTime(t.created_at, true)}</span>
                        </div>
                        <div class="mb-1">${flagsHtml}</div>
                        <div class="text-truncate text-muted small" id="preview-${t.id}">${lastMsg}</div>
                    </div>
                    <span id="badge-${t.id}" class="badge bg-success rounded-circle p-1 d-none ms-2" style="width:10px;height:10px;"> </span>
                </div>`;

            listDiv.appendChild(item);
        });
    } catch (e) { console.error(e); }
}

// Abertura do Ticket
async function openTicket(ticketId, contactName, profilePic) {
    currentTicketId = ticketId;
    currentContactName = contactName;

    document.querySelectorAll('.ticket-item').forEach(el => el.classList.remove('active'));
    document.getElementById(`ticket-item-${ticketId}`)?.classList.add('active');
    const badge = document.getElementById(`badge-${ticketId}`);
    if (badge) badge.classList.add('d-none');

    document.getElementById('activeContactName').innerText = contactName;
    document.getElementById('activeContactStatus').innerText = 'Carregando...';

    // Avatar do Header
    const headerAvatarDiv = document.getElementById('activeChatAvatar');
    if (headerAvatarDiv) {
        if (profilePic && profilePic !== 'null' && profilePic !== '') {
            headerAvatarDiv.innerHTML = `<img src="${profilePic}" class="rounded-circle shadow-sm" style="width: 45px; height: 45px; object-fit: cover; border: 2px solid var(--bg-header);">`;
        } else {
            const initial = contactName.charAt(0).toUpperCase();
            headerAvatarDiv.innerHTML = `<div class="rounded-circle bg-secondary text-white d-flex align-items-center justify-content-center shadow-sm" style="width: 45px; height: 45px; border: 2px solid var(--bg-header);"><span class="fw-bold fs-5">${initial}</span></div>`;
        }
    }

    document.getElementById('messageInput').disabled = false;
    document.getElementById('btnSend').disabled = false;
    document.getElementById('btnCloseTicket').classList.remove('d-none');
    document.getElementById('btnAttach').disabled = false;

    setTimeout(() => document.getElementById('messageInput').focus(), 100);

    const messagesDiv = document.getElementById('messagesList');
    messagesDiv.innerHTML = '<p class="text-center mt-5 text-muted"><i class="fas fa-spinner fa-spin"></i> Carregando...</p>';

    try {
        const res = await fetch(`/chat/tickets/${ticketId}/messages`);
        const messages = await res.json();

        // Se a requisição de mensagens foi bem sucedida, atualizamos o status
        // A própria chamada ao endpoint já fez a atribuição se necessário
        document.getElementById('activeContactStatus').innerText = 'Em atendimento';

        messagesDiv.innerHTML = '';

        if (messages.length === 0) {
            messagesDiv.innerHTML = '<div class="text-center mt-5 opacity-50"><i class="fab fa-whatsapp fa-3x"></i><p>Mande um "Oi"!</p></div>';
        } else {
            messages.forEach(appendMessage);
            scrollToBottom();
        }

        // Atualiza contadores (pois pode ter saído da fila)
        updateBadges();

    } catch (e) {
        messagesDiv.innerHTML = '<p class="text-center text-danger">Erro ao carregar mensagens.</p>';
    }
}

// === RENDERIZAÇÃO DE MENSAGENS (COM LÓGICA DO BOT) ===
function appendMessage(msg) {
    const messagesDiv = document.getElementById('messagesList');
    const divRow = document.createElement('div');

    const isOperator = msg.sender === 'operator';
    const isBot = msg.sender === 'bot';

    // Classes de posicionamento
    let rowClass = 'msg-left'; // Cliente
    if (isOperator) rowClass = 'msg-right';
    if (isBot) rowClass = 'msg-center'; // Novo estilo

    const senderName = isOperator ? 'Você' : (currentContactName || 'Cliente');

    divRow.className = `msg-row ${rowClass}`;

    // Nome (Não exibe se for Bot)
    const nameHtml = (rowClass !== 'msg-center') ? `<div class="small fw-bold mb-1" style="color: var(--accent-color)">${senderName}</div>` : '';

    let content = msg.content || '';
    content = String(content).replace(/\\/g, '/').trim();

    let mediaUrl = content;
    if (content.includes('/static/uploads/')) {
        const filename = content.split('/').pop();
        mediaUrl = `/chat/media/${filename}`;
    }

    // Detecção de Tipo
    let type = msg.type;
    const lowerContent = content.toLowerCase();

    const isImageFile = /\.(jpg|jpeg|png|gif|webp|bmp)(\?.*)?$/.test(lowerContent);
    const isAudioFile = /\.(mp3|ogg|wav|m4a|opus|aac)(\?.*)?$/.test(lowerContent);
    const isVideoFile = /\.(mp4|mov|avi|mkv|webm)(\?.*)?$/.test(lowerContent);
    const isInternalPath = content.includes('/static/') || content.includes('/media/');

    if (type === 'text' && (isInternalPath || isImageFile || isAudioFile || isVideoFile)) {
        if (isImageFile) type = 'image';
        else if (isAudioFile) type = 'audio';
        else if (isVideoFile) type = 'video';
        else type = 'document';
    }

    let contentHtml = '';

    if (type === 'image') {
        contentHtml = `<div class="text-center"><img src="${mediaUrl}" class="img-fluid rounded shadow-sm" style="max-height: 300px; cursor: pointer; min-width: 100px; background-color: #f0f0f0;" onclick="window.open('${mediaUrl}', '_blank')" alt="Imagem"></div>`;
    }
    else if (type === 'audio') {
        const cacheBuster = mediaUrl.includes('?') ? mediaUrl : mediaUrl + '?t=' + new Date().getTime();
        contentHtml = `<div style="min-width: 260px;" class="d-flex align-items-center bg-light rounded p-1"><audio controls preload="metadata" style="width: 100%; height: 40px;"><source src="${cacheBuster}" type="audio/mpeg"><source src="${cacheBuster}" type="audio/ogg">Áudio indisponível.</audio></div>`;
    }
    else if (type === 'video') {
        contentHtml = `<div class="text-center"><video controls class="img-fluid rounded shadow-sm" style="max-height: 300px; max-width: 100%;"><source src="${mediaUrl}">Vídeo indisponível.</video></div>`;
    }
    else if (type === 'document' || type === 'application') {
        const fileName = content.split('/').pop() || 'Arquivo';
        contentHtml = `<a href="${mediaUrl}" target="_blank" class="d-flex align-items-center text-decoration-none p-2 bg-light rounded border" style="color: #333;"><i class="fas fa-file-download fa-2x text-primary me-3"></i><div style="overflow: hidden;"><span class="d-block fw-bold text-truncate" style="max-width: 200px; font-size: 0.9rem;">${fileName}</span><small class="text-muted">Clique para baixar</small></div></a>`;
    }
    else {
        let formattedText = content.replace(/\n/g, '<br>');
        const urlRegex = /(https?:\/\/[^\s]+)/g;
        formattedText = formattedText.replace(urlRegex, '<a href="$1" target="_blank" style="color: inherit; text-decoration: underline;">$1</a>');
        contentHtml = `<div style="word-wrap: break-word;">${formattedText}</div>`;
    }

    divRow.innerHTML = `
        <div class="msg-bubble">
            ${nameHtml}
            ${contentHtml}
            <div class="msg-time" style="text-align: right; font-size: 0.65rem; opacity: 0.7; margin-top: 4px;">
                ${formatTime(msg.timestamp)}
            </div>
        </div>`;

    messagesDiv.appendChild(divRow);
    scrollToBottom();
}

function scrollToBottom() {
    const div = document.getElementById('messagesList');
    if(div) div.scrollTop = div.scrollHeight;
}

// ==========================================
// FORMULÁRIO E AÇÕES
// ==========================================

const sendForm = document.getElementById('sendForm');
if (sendForm) {
    sendForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const input = document.getElementById('messageInput');
        const content = input.value.trim();
        if (!content || !currentTicketId) return;
        input.value = '';
        try {
            await fetch(`/chat/tickets/${currentTicketId}/messages`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ content })
            });
        } catch (e) { console.error(e); }
    });
}

const btnClose = document.getElementById('btnCloseTicket');
if (btnClose) {
    btnClose.addEventListener('click', async () => {
        if (!currentTicketId || !confirm("Encerrar atendimento?")) return;
        try {
            await fetch(`/chat/tickets/${currentTicketId}/close`, { method: 'POST' });
            document.getElementById('messagesList').innerHTML = '<p class="text-center mt-5 text-muted">Atendimento encerrado.</p>';
            loadTickets('open');
            currentTicketId = null;

            document.getElementById('activeContactName').innerText = 'Selecione um chat';
            document.getElementById('activeContactStatus').innerText = 'Aguardando...';
            document.getElementById('activeChatAvatar').innerHTML = `<div class="rounded-circle bg-secondary text-white d-flex align-items-center justify-content-center shadow-sm" style="width: 45px; height: 45px; border: 2px solid var(--bg-header);"><i class="fas fa-user"></i></div>`;

            document.getElementById('messageInput').disabled = true;
            document.getElementById('btnSend').disabled = true;
            document.getElementById('btnCloseTicket').classList.add('d-none');
            document.getElementById('btnAttach').disabled = true;
            updateBadges();

        } catch (e) { alert('Erro ao encerrar'); }
    });
}

// ==========================================
// SOCKET IO (AJUSTADO PARA ATRIBUIÇÃO)
// ==========================================
socket.on('new_message', (data) => {
    if (data.sender !== 'operator') {
        notificationSound.currentTime = 0;
        notificationSound.play().catch(()=>{});
    }
    if (currentTicketId && String(data.ticket_id) === String(currentTicketId)) {
        appendMessage(data);
    }
    const previewDiv = document.getElementById(`preview-${data.ticket_id}`);
    const badge = document.getElementById(`badge-${data.ticket_id}`);
    if (previewDiv) {
        let newMsg = data.content || 'Nova mensagem';
        if (newMsg.match(/(\.jpg|\.png|\.mp3|\.pdf)/i)) newMsg = '📎 Mídia';
        previewDiv.innerHTML = newMsg;

        if (badge && (!currentTicketId || String(currentTicketId) !== String(data.ticket_id))) {
            badge.classList.remove('d-none');
        }
    } else {
        // Se a mensagem chegou e não está na lista, recarrega a lista ativa
        // O contador de badges vai atualizar no próximo ciclo do setInterval
        const activeTab = document.querySelector('.nav-link.active');
        if (activeTab) {
            const scope = activeTab.getAttribute('onclick').includes('open') ? 'open' : 'pending';
            loadTickets(scope, true);
        }
        updateBadges();
    }
});

// EVENTO DE ATRIBUIÇÃO AUTOMÁTICA
socket.on('ticket_assigned', (data) => {
    // Se eu estou vendo a lista da Fila ('pending') e um ticket foi atribuído,
    // ele deve sumir da minha lista (ou ir para 'open' se fui eu quem peguei).
    const activeTab = document.querySelector('.nav-link.active');
    if (activeTab) {
        const scope = activeTab.getAttribute('onclick').includes('open') ? 'open' : 'pending';
        loadTickets(scope, true);
    }
    updateBadges();
});

// ==========================================
// MODAL NOVA CONVERSA (MANTIDO)
// ==========================================

const newChatModal = document.getElementById('newChatModal');
if (newChatModal) {
    newChatModal.addEventListener('shown.bs.modal', () => {
        fetchContacts('');
        document.getElementById('contactSearchInput').focus();
    });
}

const searchInput = document.getElementById('contactSearchInput');
if (searchInput) {
    let debounceTimer;
    searchInput.addEventListener('input', (e) => {
        clearTimeout(debounceTimer);
        const query = e.target.value;
        debounceTimer = setTimeout(() => {
            fetchContacts(query);
        }, 300);
    });
}

async function fetchContacts(query) {
    const listDiv = document.getElementById('contactSearchResults');
    if(!query && listDiv.innerHTML.trim() === '') listDiv.innerHTML = '<div class="text-center mt-5 text-muted"><i class="fas fa-spinner fa-spin"></i> Buscando...</div>';

    try {
        const res = await fetch(`/chat/contacts/search?q=${encodeURIComponent(query)}`);
        if (!res.ok) return;

        const contacts = await res.json();
        listDiv.innerHTML = '';

        if (contacts.length === 0) {
            listDiv.innerHTML = `<div class="text-center mt-5 text-muted opacity-50"><i class="far fa-address-book fa-2x"></i><p>Nenhum contato.</p></div>`;
            return;
        }

        const header = document.createElement('div');
        header.className = "p-2 border-bottom fw-bold text-muted bg-light small";
        header.innerText = "CONTATOS";
        listDiv.appendChild(header);

        contacts.forEach(c => {
            const item = document.createElement('div');
            item.className = 'contact-item d-flex align-items-center gap-3 p-3 border-bottom';

            let imgHtml = `<div class="rounded-circle d-flex align-items-center justify-content-center text-white fw-bold shadow-sm" style="width: 45px; height: 45px; font-size: 1.1rem; background-color: #ced0d1;">${c.name.charAt(0).toUpperCase()}</div>`;
            if (c.profile_pic) imgHtml = `<img src="${c.profile_pic}" class="rounded-circle shadow-sm" style="width: 45px; height: 45px; object-fit: cover;">`;

            const cleanPhone = c.remote_jid ? c.remote_jid.split('@')[0] : '';

            let btnHtml = '';
            if(c.open_ticket_id) {
                btnHtml = `<button class="btn btn-sm btn-outline-primary" onclick="openExistingChat('${c.open_ticket_id}', '${c.name}', '${c.profile_pic}')">ABRIR</button>`;
            } else {
                btnHtml = `<button class="btn btn-sm btn-success rounded-circle" onclick='createTicket({"contact_id": "${c.id}"})'><i class="fas fa-plus"></i></button>`;
            }

            item.innerHTML = `
                ${imgHtml}
                <div class="flex-grow-1" style="min-width: 0;">
                    <div class="fw-bold text-truncate">${c.name}</div>
                    <div class="text-muted small">+${cleanPhone}</div>
                </div>
                ${btnHtml}
            `;
            listDiv.appendChild(item);
        });
    } catch (e) { console.error(e); }
}

async function startManualChat() {
    const ddi = document.getElementById('ddiSelect').value;
    const raw = document.getElementById('manualPhoneInput').value;
    const clean = raw.replace(/\D/g, '');
    if (clean.length < 8) { alert('Número inválido'); return; }
    createTicket({ phone: ddi + clean });
}

async function createTicket(payload) {
    try {
        const res = await fetch('/chat/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        const txt = await res.text();
        let data;
        try { data = JSON.parse(txt); } catch(e) { throw new Error(txt); }

        if (!res.ok) throw new Error(data.error);

        bootstrap.Modal.getInstance(document.getElementById('newChatModal')).hide();
        document.getElementById('manualPhoneInput').value = '';
        if(searchInput) searchInput.value = '';

        await loadTickets('open');
        openTicket(data.ticket_id, data.contact_name);
    } catch (e) {
        console.error(e);
        alert('Erro ao criar conversa.');
    }
}

function openExistingChat(tid, name, pic) {
    bootstrap.Modal.getInstance(document.getElementById('newChatModal')).hide();
    const item = document.getElementById(`ticket-item-${tid}`);
    if(item) item.click();
    else openTicket(tid, name, pic);
}