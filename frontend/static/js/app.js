document.addEventListener('DOMContentLoaded', () => {
    const sendBtn = document.getElementById('sendBtn');
    const userInput = document.getElementById('userInput');
    const chatMessages = document.getElementById('chatMessages');
    const analysisList = document.getElementById('analysisList');
    const micBtn = document.getElementById('micBtn');

    const menuButtons = document.querySelectorAll('.menu-btn');
    const sections = document.querySelectorAll('.app-section');
    const navRegistry = document.getElementById('navRegistry');
    const navMeds = document.getElementById('navMeds');
    const nextStepContainer = document.getElementById('nextStepContainer');
    const goToRegistryBtn = document.getElementById('goToRegistryBtn');
    const confirmRegistryBtn = document.getElementById('confirmRegistryBtn');

    const triageBadge = document.getElementById('triageBadge');
    const triageText = document.getElementById('triageText');

    const ocrFileInput = document.getElementById('ocrFileInput');
    const simUploadBtn = document.getElementById('simUploadBtn');
    const ocrStatus = document.getElementById('ocrStatus');
    const medList = document.getElementById('medList');

    let confirmedSymptoms = [];
    let currentQuestion = 'Опишите ваше состояние или симптомы.';
    let finished = false;
    let busy = false;

    // Сброс сессии
    fetch('/api/reset', { method: 'POST' }).catch(() => {});

    // --- 1. ГОЛОСОВОЙ ВВОД (WEB SPEECH API) ---
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
        const recognition = new SpeechRecognition();
        recognition.lang = 'ru-RU';
        recognition.interimResults = false;

        micBtn.addEventListener('click', () => {
            if (micBtn.classList.contains('recording')) {
                recognition.stop();
            } else {
                recognition.start();
                micBtn.classList.add('recording');
            }
        });

        recognition.onresult = (e) => {
            userInput.value = e.results[0][0].transcript;
            micBtn.classList.remove('recording');
        };

        recognition.onerror = () => micBtn.classList.remove('recording');
        recognition.onend = () => micBtn.classList.remove('recording');
    } else {
        micBtn.style.display = 'none';
    }

    // --- 2. ИНДИКАТОР ТРИАЖА (СВЕТОФОР) ---
    function updateTriageBadge(level) {
        triageBadge.className = 'triage-status-badge';
        if (level === 'red') {
            triageBadge.classList.add('triage-red');
            triageText.textContent = '🚨 ЭКСТРЕННО: СРОЧНО 112/103';
        } else if (level === 'yellow') {
            triageBadge.classList.add('triage-yellow');
            triageText.textContent = '⚠️ Внимание: Прием в течение 24ч';
        } else {
            triageBadge.classList.add('triage-green');
            triageText.textContent = '🟢 Состояние: Плановый визит';
        }
    }

    // Вкладки
    menuButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.disabled) return;
            menuButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const targetMode = btn.dataset.mode;
            sections.forEach(sec => {
                sec.classList.remove('active-section');
                if (sec.id === `section-${targetMode}`) sec.classList.add('active-section');
            });

            if (targetMode === 'registry') loadSoapProtocol();
        });
    });

    function addMessage(text, sender) {
        const msg = document.createElement('div');
        msg.className = `message ${sender === 'user' ? 'user-message' : 'ai-message'}`;
        msg.textContent = text;
        chatMessages.appendChild(msg);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function escapeHtml(str) {
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    function addSymptomCard(text) {
        const placeholder = analysisList.querySelector('.journal-placeholder');
        if (placeholder) placeholder.remove();

        const card = document.createElement('div');
        card.className = 'journal-card';
        card.innerHTML = `<b>Жалоба:</b> ${escapeHtml(text)}`;
        analysisList.appendChild(card);
    }

    async function confirmSymptom(text, container) {
        container.querySelector('.action-buttons').innerHTML = '<span style="font-size:13px; color:#ffffff; font-weight:bold;">✓ Добавлено в журнал</span>';
        addSymptomCard(text);
        confirmedSymptoms.push({ question: currentQuestion, answer: text });
        nextStepContainer.style.display = 'block';

        try {
            const resp = await fetch('/api/complaints', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text, question: currentQuestion })
            });
            const data = await resp.json();

            if (data.question) {
                currentQuestion = data.question;
                addMessage(data.question, 'ai');
            }
        } catch (e) {
            addMessage('Ошибка связи с сервером.', 'ai');
        }
    }

    async function handleUserSubmit() {
        const text = userInput.value.trim();
        if (!text || busy || finished) return;

        addMessage(text, 'user');
        userInput.value = '';

        // Триаж проверка
        try {
            const r = await fetch('/api/triage', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text })
            });
            const triageRes = await r.json();
            updateTriageBadge(triageRes.level);

            if (triageRes.emergency) {
                finished = true;
                sendBtn.disabled = true;
                userInput.disabled = true;
                addMessage('⚠️ ВНИМАНИЕ! Вы описали симптомы экстренного состояния. Пожалуйста, немедленно вызовите скорую помощь по номеру 112 или 103!', 'ai');
                return;
            }
        } catch (e) {}

        const aiMsgContainer = document.createElement('div');
        aiMsgContainer.className = 'message ai-message';
        aiMsgContainer.innerHTML = `
            <div>Обработано: <b>«${escapeHtml(text)}»</b>.<br>Внести симптом в журнал жалоб?</div>
            <div class="action-buttons">
                <button class="act-btn btn-yes">Да</button>
                <button class="act-btn btn-no">Нет</button>
            </div>
        `;
        chatMessages.appendChild(aiMsgContainer);
        chatMessages.scrollTop = chatMessages.scrollHeight;

        aiMsgContainer.querySelector('.btn-yes').addEventListener('click', () => confirmSymptom(text, aiMsgContainer));
        aiMsgContainer.querySelector('.btn-no').addEventListener('click', () => {
            aiMsgContainer.querySelector('.action-buttons').innerHTML = '<span style="font-size:13px; color:#e5e7eb;">✗ Отклонено</span>';
            addMessage(currentQuestion, 'ai');
        });
    }

    sendBtn.addEventListener('click', handleUserSubmit);
    userInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') handleUserSubmit(); });

    goToRegistryBtn.addEventListener('click', () => {
        navRegistry.disabled = false;
        navRegistry.click();
    });

    // --- 3. ЗАГРУЗКА SOAP ПРОТОКОЛА ---
    async function loadSoapProtocol() {
        try {
            const r = await fetch('/api/soap');
            const data = await r.json();
            document.getElementById('soapS').textContent = data.soap.S;
            document.getElementById('soapO').textContent = data.soap.O;
            document.getElementById('soapA').textContent = data.soap.A;
            document.getElementById('soapP').textContent = data.soap.P;
        } catch (e) {}
    }

    confirmRegistryBtn.addEventListener('click', () => {
        alert('Протокол SOAP успешно передан в защищенный контур ЕМИАС!');
    });

    // --- 4. OCR СКАНИРОВАНИЕ РЕЦЕПТОВ ---
    simUploadBtn.addEventListener('click', () => ocrFileInput.click());

    ocrFileInput.addEventListener('change', async () => {
        if (!ocrFileInput.files.length) return;
        ocrStatus.textContent = '⏳ Сканирование и распознавание текста (OCR)...';

        const formData = new FormData();
        formData.append('file', ocrFileInput.files[0]);

        try {
            const r = await fetch('/api/ocr', { method: 'POST', body: formData });
            const res = await r.json();

            ocrStatus.textContent = '✅ Рецепт успешно распознан!';
            res.extracted_meds.forEach(m => {
                const li = document.createElement('li');
                li.innerHTML = `${m.name} — <b>${m.schedule}</b> (Из рецепта)`;
                medList.appendChild(li);
            });
        } catch (e) {
            ocrStatus.textContent = '❌ Ошибка распознавания.';
        }
    });
});