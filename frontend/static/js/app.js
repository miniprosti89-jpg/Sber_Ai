document.addEventListener('DOMContentLoaded', () => {
    const sendBtn = document.getElementById('sendBtn');
    const userInput = document.getElementById('userInput');
    const chatMessages = document.getElementById('chatMessages');
    const analysisList = document.getElementById('analysisList');

    // Элементы навигации
    const modeButtons = document.querySelectorAll('.mode-btn');
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
    modeButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.disabled) return;
            modeButtons.forEach(b => b.classList.remove('active'));
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
        const emptyMsg = analysisList.querySelector('.empty-analysis');
        if (emptyMsg) emptyMsg.remove();

        const card = document.createElement('div');
        card.className = 'analysis-card';
        card.innerHTML = `
            <div class="analysis-card-title">Жалоба пациента</div>
            <div class="analysis-card-text">${escapeHtml(text)}</div>
        `;
        analysisList.appendChild(card);
    }

    function setBusy(v) {
        busy = v;
        sendBtn.disabled = v || finished;
        userInput.disabled = v || finished;
    }

    async function confirmSymptom(text, container) {
        container.querySelector('.action-buttons').innerHTML = '<span style="font-size:12px; color:#137333; font-weight:600;">✓ Зафиксировано</span>';
        addSymptomCard(text);
        confirmedSymptoms.push(text);
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

    function handleUserSubmit() {
        const text = userInput.value.trim();
        if (!text || busy || finished) return;

        addMessage(text, 'user');
        userInput.value = '';

        setTimeout(() => {
            const aiMsgContainer = document.createElement('div');
            aiMsgContainer.className = 'message ai-message';
            aiMsgContainer.innerHTML = `
                <div>Обнаружен симптом: <b>«${escapeHtml(text)}»</b>.<br>Добавить в медицинскую карту для врача?</div>
                <div class="action-buttons">
                    <button class="action-btn btn-yes">Да</button>
                    <button class="action-btn btn-no">Нет</button>
                </div>
            `;
            chatMessages.appendChild(aiMsgContainer);
            chatMessages.scrollTop = chatMessages.scrollHeight;

            aiMsgContainer.querySelector('.btn-yes').addEventListener('click', () => confirmSymptom(text, aiMsgContainer));

            aiMsgContainer.querySelector('.btn-no').addEventListener('click', () => {
                aiMsgContainer.querySelector('.action-buttons').innerHTML = '<span style="font-size:12px; color:#5f6368;">✗ Пропущено</span>';
                // Нет — задаём вопрос заново
                addMessage(currentQuestion || 'Опишите ваше состояние или симптомы.', 'ai');
            });
        }, 400);
    }

    sendBtn.addEventListener('click', handleUserSubmit);
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleUserSubmit();
    });

    // Переход в режим Регистратуры
    goToRegistryBtn.addEventListener('click', () => {
        navRegistry.disabled = false;
        navRegistry.click(); // Переключаем вкладку

        // Заполняем данные талона
        ticketSummary.innerHTML = `<b>Симптомы для терапевта:</b><br>` + confirmedSymptoms.map(s => `• ${s}`).join('<br>');
    });

    // Подтверждение записи в регистратуре -> разблокировка плана лечения
    confirmRegistryBtn.addEventListener('click', () => {
        alert('Запись успешно подтверждена! Направление передано в ЕМИАС.');
        navMeds.disabled = false;
        navMeds.click(); // Переключаем на план лечения
    });

    // Симуляция загрузки справки врача
    simUploadBtn.addEventListener('click', () => {
        alert('Заключение врача успешно получено из электронной медкарты! План приема лекарств обновлен.');
    });
});