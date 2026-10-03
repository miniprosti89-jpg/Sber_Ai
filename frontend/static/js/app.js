document.addEventListener('DOMContentLoaded', () => {
    const sendBtn = document.getElementById('sendBtn');
    const userInput = document.getElementById('userInput');
    const chatMessages = document.getElementById('chatMessages');
    const analysisList = document.getElementById('analysisList');

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

        // Добавляем сообщение пользователя
        addMessage(text, 'user');
        userInput.value = '';

        // Имитация ответа ИИ с предложением анализа
        setTimeout(() => {
            const aiMsgContainer = document.createElement('div');
            aiMsgContainer.className = 'message ai-message';

            aiMsgContainer.innerHTML = `
                <div>Ваш текст обработан: <b>«${text}»</b>.<br>Добавить этот пункт в структурированный анамнез?</div>
                <div class="action-buttons">
                    <button class="action-btn btn-yes">Да</button>
                    <button class="action-btn btn-no">Нет</button>
                </div>
            `;

            chatMessages.appendChild(aiMsgContainer);
            chatMessages.scrollTop = chatMessages.scrollHeight;

            // Обработка кликов по кнопкам Да / Нет
            const btnYes = aiMsgContainer.querySelector('.btn-yes');
            const btnNo = aiMsgContainer.querySelector('.btn-no');

            btnYes.addEventListener('click', () => {
                // Удаляем заглушку "пусто" если она первая
                const emptyMsg = analysisList.querySelector('.empty-analysis');
                if (emptyMsg) {
                    emptyMsg.remove();
                }

                // Добавляем карточку в боковую панель анализа
                const card = document.createElement('div');
                card.className = 'analysis-card';
                card.innerHTML = `
                    <div class="analysis-card-title">Подтвержденный факт</div>
                    <div class="analysis-card-text">${text}</div>
                `;
                analysisList.appendChild(card);
                analysisList.scrollTop = analysisList.scrollHeight;

                // Блокируем кнопки после выбора
                aiMsgContainer.querySelector('.action-buttons').innerHTML = '<span style="font-size:12px; color:#137333; font-weight:600;">✓ Добавлено в карту</span>';
            });

            btnNo.addEventListener('click', () => {
                aiMsgContainer.querySelector('.action-buttons').innerHTML = '<span style="font-size:12px; color:#5f6368;">✗ Отклонено</span>';
            });

        }, 800);
    }

    sendBtn.addEventListener('click', handleUserSubmit);
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            handleUserSubmit();
        }
    });
});