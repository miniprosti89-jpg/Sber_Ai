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

    function handleUserSubmit() {
        const text = userInput.value.trim();
        if (!text) return;

        addMessage(text, 'user');
        userInput.value = '';

        setTimeout(() => {
            const aiMsgContainer = document.createElement('div');
            aiMsgContainer.className = 'message ai-message';
            aiMsgContainer.innerHTML = `
                <div>Обработано: <b>«${text}»</b>.<br>Внести симптом в журнал жалоб?</div>
                <div class="action-buttons">
                    <button class="act-btn btn-yes">Да</button>
                    <button class="act-btn btn-no">Нет</button>
                </div>
            `;
            chatMessages.appendChild(aiMsgContainer);
            chatMessages.scrollTop = chatMessages.scrollHeight;

            const btnYes = aiMsgContainer.querySelector('.btn-yes');
            const btnNo = aiMsgContainer.querySelector('.btn-no');

            btnYes.addEventListener('click', () => {
                const placeholder = analysisList.querySelector('.journal-placeholder');
                if (placeholder) placeholder.remove();

                const card = document.createElement('div');
                card.className = 'journal-card';
                card.innerHTML = `<b>Жалоба:</b> ${text}`;
                analysisList.appendChild(card);

                confirmedSymptoms.push(text);
                nextStepContainer.style.display = 'block';

                aiMsgContainer.querySelector('.action-buttons').innerHTML = '<span style="font-size:13px; color:#ffffff; font-weight:bold;">✓ Добавлено в журнал жалоб</span>';
            });

            btnNo.addEventListener('click', () => {
                aiMsgContainer.querySelector('.action-buttons').innerHTML = '<span style="font-size:13px; color:#e5e7eb;">✗ Отклонено</span>';
            });

        }, 600);
    }

    sendBtn.addEventListener('click', handleUserSubmit);
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleUserSubmit();
    });

    goToRegistryBtn.addEventListener('click', () => {
        navRegistry.disabled = false;
        navRegistry.click();
        ticketSummary.innerHTML = `<b>Собранные данные для протокола:</b><br>` + confirmedSymptoms.map(s => `• ${s}`).join('<br>');
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