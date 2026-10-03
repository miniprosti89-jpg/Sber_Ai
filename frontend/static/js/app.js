document.addEventListener('DOMContentLoaded', () => {
    const sendBtn = document.getElementById('sendBtn');
    const userInput = document.getElementById('userInput');
    const chatMessages = document.getElementById('chatMessages');
    const navButtons = document.querySelectorAll('.nav-btn');
    const scenarioTitle = document.getElementById('current-scenario-title');

    // Переключение сценариев в сайдбаре
    navButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            navButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            scenarioTitle.textContent = btn.textContent;

            // Очистка чата или смена контекста при необходимости
            chatMessages.innerHTML = `
                <div class="message ai-message">
                    Выбран сценарий: "${btn.textContent}". Чем я могу помочь?
                </div>
            `;
        });
    });

    // Функция отправки сообщения
    function sendMessage() {
        const text = userInput.value.trim();
        if (!text) return;

        // Добавляем сообщение пользователя
        const userMsg = document.createElement('div');
        userMsg.className = 'message user-message';
        userMsg.textContent = text;
        chatMessages.appendChild(userMsg);

        userInput.value = '';
        chatMessages.scrollTop = chatMessages.scrollHeight;

        // Имитация ответа ИИ (здесь потом будет запрос к твоему FastAPI бэкенду)
        setTimeout(() => {
            const aiMsg = document.createElement('div');
            aiMsg.className = 'message ai-message';
            aiMsg.textContent = 'Принято. Анализирую симптомы в соответствии с клиническими рекомендациями...';
            chatMessages.appendChild(aiMsg);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }, 1000);
    }

    sendBtn.addEventListener('click', sendMessage);
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });
});