document.addEventListener('DOMContentLoaded', () => {
    const sendBtn = document.getElementById('sendBtn');
    const userInput = document.getElementById('userInput');
    const chatMessages = document.getElementById('chatMessages');
    const analysisList = document.getElementById('analysisList');

    const menuButtons = document.querySelectorAll('.menu-btn');
    const sections = document.querySelectorAll('.app-section');
    const navRegistry = document.getElementById('navRegistry');
    const navMeds = document.getElementById('navMeds');
    const nextStepContainer = document.getElementById('nextStepContainer');
    const goToRegistryBtn = document.getElementById('goToRegistryBtn');
    const ticketSummary = document.getElementById('ticketSummary');
    const confirmRegistryBtn = document.getElementById('confirmRegistryBtn');
    const simUploadBtn = document.getElementById('simUploadBtn');

    let confirmedSymptoms = [];

    // Переключение режимов (вкладок)
    menuButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.disabled) return;
            menuButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const targetMode = btn.dataset.mode;
            sections.forEach(sec => {
                sec.classList.remove('active-section');
                if (sec.id === `section-${targetMode}`) {
                    sec.classList.add('active-section');
                }
            });
        });
    });

    function addMessage(text, sender) {
        const msg = document.createElement('div');
        msg.className = `message ${sender === 'user' ? 'user-message' : 'ai-message'}`;
        msg.textContent = text;
        chatMessages.appendChild(msg);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    let currentQuestion = 'Опишите ваше состояние или симптомы.';   // последний вопрос ИИ
    let finished = false;
    let busy = false;

    // Новая сессия — чистим json с жалобами
    fetch('/api/reset', { method: 'POST' }).catch(() => {});

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

    function setBusy(v) {
        busy = v;
        sendBtn.disabled = v || finished;
        userInput.disabled = v || finished;
    }

    async function confirmSymptom(text, container) {
        container.querySelector('.action-buttons').innerHTML = '<span style="font-size:13px; color:#ffffff; font-weight:bold;">✓ Добавлено в журнал жалоб</span>';
        addSymptomCard(text);
        confirmedSymptoms.push({ question: currentQuestion, answer: text });
        nextStepContainer.style.display = 'block';

        setBusy(true);
        try {
            const resp = await fetch('/api/complaints', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text, question: currentQuestion })
            });
            const data = await resp.json();

            if (data.done) {
                finished = true;
                addMessage('Спасибо! Я собрал достаточно информации для врача. Переходите к записи.', 'ai');
            } else if (data.question) {
                currentQuestion = data.question;
                addMessage(data.question, 'ai');
            } else {
                addMessage(data.error || 'Не удалось получить уточняющий вопрос.', 'ai');
            }
        } catch (e) {
            addMessage('Ошибка связи с сервером.', 'ai');
        }
        setBusy(false);
        if (!finished) userInput.focus();
    }

    const EMERGENCY_HTML = `
        <div style="color:#b3261e; font-weight:700; font-size:16px;">⚠️ Это может быть неотложное состояние!</div>
        <div style="margin-top:8px;">Прекратите общение с ассистентом и <b>срочно позвоните в скорую помощь</b>.
        Не ждите записи к врачу и не пытайтесь добраться самостоятельно.</div>
        <div style="margin-top:10px; line-height:1.7;">
            📞 <b>112</b> — единый номер экстренных служб<br>
            📞 <b>103</b> — скорая медицинская помощь<br>
            📞 <b>8-800-100-01-12</b> — телефон для звонков с мобильных, если 112 недоступен
        </div>
        <div style="margin-top:10px;">Назовите диспетчеру адрес и опишите, что с вами происходит.</div>
    `;

    function showEmergency() {
        finished = true;
        sendBtn.disabled = true;
        userInput.disabled = true;
        userInput.placeholder = 'Диалог остановлен. Позвоните 112 или 103.';
        const msg = document.createElement('div');
        msg.className = 'message ai-message';
        msg.style.border = '2px solid #b3261e';
        msg.innerHTML = EMERGENCY_HTML;
        chatMessages.appendChild(msg);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    async function handleUserSubmit() {
        const text = userInput.value.trim();
        if (!text || busy || finished) return;

        addMessage(text, 'user');
        userInput.value = '';

        // Проверка на экстренное состояние до любых вопросов
        setBusy(true);
        let emergency = false;
        try {
            const r = await fetch('/api/triage', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text })
            });
            emergency = (await r.json()).emergency === true;
        } catch (e) { /* сервер недоступен — продолжаем обычный диалог */ }
        setBusy(false);

        if (emergency) {
            showEmergency();
            return;
        }

        setTimeout(() => {
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
                // Нет — задаём вопрос заново
                addMessage(currentQuestion || 'Опишите ваше состояние или симптомы.', 'ai');
            });
        }, 400);
    }

    sendBtn.addEventListener('click', handleUserSubmit);
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleUserSubmit();
    });

    goToRegistryBtn.addEventListener('click', () => {
        navRegistry.disabled = false;
        navRegistry.click();
        ticketSummary.innerHTML = `<b>Собранные данные для протокола:</b><br>` + confirmedSymptoms.map(s =>
            `<div style="margin-top:8px;"><span style="color:#5f6368;">Вопрос ИИ: ${escapeHtml(s.question)}</span><br>• ${escapeHtml(s.answer)}</div>`
        ).join('');
    });

    confirmRegistryBtn.addEventListener('click', () => {
        alert('Данные успешно переданы в защищенный контур ЕМИАС!');
        navMeds.disabled = false;
        navMeds.click();
    });

    simUploadBtn.addEventListener('click', () => {
        alert('Справка успешно обработана OCR-модулем. Календарь приема обновлен.');
    });
});