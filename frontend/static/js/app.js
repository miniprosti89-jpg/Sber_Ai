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

    function handleUserSubmit() {
        const text = userInput.value.trim();
        if (!text) return;

        addMessage(text, 'user');
        userInput.value = '';

        setTimeout(() => {
            const aiMsgContainer = document.createElement('div');
            aiMsgContainer.className = 'message ai-message';
            aiMsgContainer.innerHTML = `
                <div>Обнаружен симптом: <b>«${text}»</b>.<br>Добавить в медицинскую карту для врача?</div>
                <div class="action-buttons">
                    <button class="action-btn btn-yes">Да</button>
                    <button class="action-btn btn-no">Нет</button>
                </div>
            `;
            chatMessages.appendChild(aiMsgContainer);
            chatMessages.scrollTop = chatMessages.scrollHeight;

            const btnYes = aiMsgContainer.querySelector('.btn-yes');
            const btnNo = aiMsgContainer.querySelector('.btn-no');

            btnYes.addEventListener('click', () => {
                const emptyMsg = analysisList.querySelector('.empty-analysis');
                if (emptyMsg) emptyMsg.remove();

                const card = document.createElement('div');
                card.className = 'analysis-card';
                card.innerHTML = `
                    <div class="analysis-card-title">Жалоба пациента</div>
                    <div class="analysis-card-text">${text}</div>
                `;
                analysisList.appendChild(card);

                confirmedSymptoms.push(text);

                // Показываем кнопку перехода к регистрации после добавления хотя бы одного симптома
                nextStepContainer.style.display = 'block';

                aiMsgContainer.querySelector('.action-buttons').innerHTML = '<span style="font-size:12px; color:#137333; font-weight:600;">✓ Зафиксировано</span>';
            });

            btnNo.addEventListener('click', () => {
                aiMsgContainer.querySelector('.action-buttons').innerHTML = '<span style="font-size:12px; color:#5f6368;">✗ Пропущено</span>';
            });

        }, 800);
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