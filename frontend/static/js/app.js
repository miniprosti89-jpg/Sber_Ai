document.addEventListener('DOMContentLoaded', () => {
    /* ==================== ЭЛЕМЕНТЫ ==================== */
    const authOverlay   = document.getElementById('authOverlay');
    const authForm      = document.getElementById('authForm');
    const authName      = document.getElementById('authName');
    const authEmail     = document.getElementById('authEmail');
    const authAvatar    = document.getElementById('authAvatar');
    const authConsent   = document.getElementById('authConsent');
    const authError     = document.getElementById('authError');

    const userAvatarImg = document.getElementById('userAvatarImg');
    const userNameLabel = document.getElementById('userNameLabel');
    const logoutBtn     = document.getElementById('logoutBtn');

    const sendBtn       = document.getElementById('sendBtn');
    const finishBtn     = document.getElementById('finishBtn');
    const userInput     = document.getElementById('userInput');
    const chatMessages  = document.getElementById('chatMessages');
    const analysisList  = document.getElementById('analysisList');

    const menuButtons   = document.querySelectorAll('.menu-btn');
    const sections      = document.querySelectorAll('.app-section');
    const navRegistry   = document.getElementById('navRegistry');
    const navMeds       = document.getElementById('navMeds');
    const nextStepContainer = document.getElementById('nextStepContainer');
    const goToRegistryBtn   = document.getElementById('goToRegistryBtn');
    const ticketSummary     = document.getElementById('ticketSummary');
    const confirmRegistryBtn= document.getElementById('confirmRegistryBtn');
    const simUploadBtn      = document.getElementById('simUploadBtn');

    const soapS = document.getElementById('soapS');
    const soapO = document.getElementById('soapO');
    const soapA = document.getElementById('soapA');
    const soapP = document.getElementById('soapP');

    const doctorEmailInput = document.getElementById('doctorEmailInput');
    const sendPdfBtn       = document.getElementById('sendPdfBtn');
    const emailStatus      = document.getElementById('emailStatus');

    const prescriptionsList = document.getElementById('prescriptionsList');
    const remindersList     = document.getElementById('remindersList');
    const rxName     = document.getElementById('rxName');
    const rxDosage   = document.getElementById('rxDosage');
    const rxSchedule = document.getElementById('rxSchedule');
    const addRxBtn   = document.getElementById('addRxBtn');
    const remMed     = document.getElementById('remMed');
    const remTime    = document.getElementById('remTime');
    const addRemBtn  = document.getElementById('addRemBtn');

    const DEFAULT_AVATAR = '../static/img/default_avatar.svg';

    /* ==================== СОСТОЯНИЕ ==================== */
    const state = {
        user: null,
        confirmedSymptoms: [],
        currentQuestion: 'Опишите ваше состояние или симптомы.',
        finished: false,
        busy: false,
        reminders: [],
        prescriptions: [],
    };

    /* ==================== АВТОРИЗАЦИЯ (LOCK / UNLOCK) ==================== */
    function setAuthLocked(locked) {
        // Класс на body полностью скрывает шапку и контент приложения, пока не выполнен вход
        document.body.classList.toggle('auth-locked', locked);
        // Дублируем inline-стилем на самом оверлее — гарантированный результат даже без CSS
        if (locked) {
            authOverlay.style.display = 'flex';
        } else {
            authOverlay.style.display = 'none';
        }
    }

    function applyUser(user) {
        state.user = user || {};
        userNameLabel.textContent = state.user.name || 'гость';
        userAvatarImg.src = state.user.avatar || DEFAULT_AVATAR;

        // Мгновенно перебрасываем пользователя в чат
        menuButtons.forEach(b => b.classList.remove('active'));
        const chatBtn = document.querySelector('.menu-btn[data-mode="chat"]');
        if (chatBtn) chatBtn.classList.add('active');
        sections.forEach(sec => {
            sec.classList.remove('active-section');
            if (sec.id === 'section-chat') sec.classList.add('active-section');
        });

        if (doctorEmailInput && state.user.email) {
            doctorEmailInput.value = state.user.email;
        }
    }

    async function checkAuth() {
        setAuthLocked(true);
        try {
            const r = await fetch('/api/me', { credentials: 'same-origin' });
            if (r.ok) {
                const data = await r.json();
                applyUser(data.user);
                setAuthLocked(false);
                await loadUserData();
                return;
            }
        } catch (e) { /* нет соединения — оставляем оверлей */ }
        setAuthLocked(true);
    }

    authForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        authError.textContent = '';

        if (!authConsent.checked) {
            authError.textContent = 'Необходимо согласие на обработку персональных данных (152-ФЗ).';
            return;
        }
        if (!authName.value.trim() || !authEmail.value.trim()) {
            authError.textContent = 'Заполните имя и email.';
            return;
        }

        const fd = new FormData();
        fd.append('name', authName.value.trim());
        fd.append('email', authEmail.value.trim());
        fd.append('consent', 'true');
        if (authAvatar.files[0]) fd.append('avatar', authAvatar.files[0]);

        const submitBtn = authForm.querySelector('.auth-submit');
        submitBtn.disabled = true;
        submitBtn.textContent = 'Входим...';

        try {
            const r = await fetch('/api/login', {
                method: 'POST',
                body: fd,
                credentials: 'same-origin',
            });
            const data = await r.json();
            if (!r.ok) {
                authError.textContent = data.error || 'Не удалось войти';
                return;
            }

            applyUser(data.user);
            setAuthLocked(false);

            // Сброс серверной сессии жалоб
            fetch('/api/reset', { method: 'POST', credentials: 'same-origin' }).catch(() => {});
            await loadUserData();
        } catch (err) {
            authError.textContent = 'Ошибка соединения с сервером.';
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Войти в систему';
        }
    });

    logoutBtn.addEventListener('click', async () => {
        try { await fetch('/api/logout', { method: 'POST', credentials: 'same-origin' }); } catch (e) {}
        // Обнуляем форму и возвращаемся к экрану входа
        authForm.reset();
        authError.textContent = '';
        applyUser(null);
        setAuthLocked(true);
    });

    /* ==================== ХЕЛПЕРЫ ==================== */
    function escapeHtml(str) {
        const d = document.createElement('div');
        d.textContent = str == null ? '' : String(str);
        return d.innerHTML;
    }

    function addMessage(text, sender) {
        const msg = document.createElement('div');
        msg.className = `message ${sender === 'user' ? 'user-message' : 'ai-message'}`;
        msg.textContent = text;
        chatMessages.appendChild(msg);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function setBusy(v) {
        state.busy = v;
        sendBtn.disabled   = v || state.finished;
        finishBtn.disabled = v || state.finished;
        userInput.disabled = v || state.finished;
    }

    /* ==================== НАВИГАЦИЯ ==================== */
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

            if (targetMode === 'registry') loadSoap();
            if (targetMode === 'medications') loadUserData();
        });
    });

    /* ==================== ЧАТ / АНАМНЕЗ ==================== */
    function addSymptomCard(text) {
        const placeholder = analysisList.querySelector('.journal-placeholder');
        if (placeholder) placeholder.remove();

        const card = document.createElement('div');
        card.className = 'journal-card';
        card.innerHTML = `<b>Жалоба:</b> ${escapeHtml(text)}`;
        analysisList.appendChild(card);
    }

    async function confirmSymptom(text, container) {
        container.querySelector('.action-buttons').innerHTML =
            '<span style="font-size:13px; color:#ffffff; font-weight:bold;">✓ Добавлено в журнал жалоб</span>';
        addSymptomCard(text);
        state.confirmedSymptoms.push({ question: state.currentQuestion, answer: text });
        nextStepContainer.style.display = 'block';

        setBusy(true);
        try {
            const resp = await fetch('/api/complaints', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ text, question: state.currentQuestion })
            });
            const data = await resp.json();

            if (data.question) {
                state.currentQuestion = data.question;
                addMessage(data.question, 'ai');
            } else {
                addMessage(data.error || 'Не удалось получить уточняющий вопрос.', 'ai');
            }
        } catch (e) {
            addMessage('Ошибка связи с сервером.', 'ai');
        }
        setBusy(false);
        if (!state.finished) userInput.focus();
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
        state.finished = true;
        sendBtn.disabled = true;
        finishBtn.disabled = true;
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
        if (!text || state.busy || state.finished) return;

        addMessage(text, 'user');
        userInput.value = '';

        setBusy(true);
        let emergency = false;
        try {
            const r = await fetch('/api/triage', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ text })
            });
            emergency = (await r.json()).emergency === true;
        } catch (e) { /* сервер недоступен — продолжаем */ }
        setBusy(false);

        if (emergency) { showEmergency(); return; }

        setTimeout(() => {
            const aiMsgContainer = document.createElement('div');
            aiMsgContainer.className = 'message ai-message';
            aiMsgContainer.innerHTML = `
                <div>Обработано: <b>«${escapeHtml(text)}»</b>.<br>Внести симптом в журнал жалоб?</div>
                <div class="action-buttons">
                    <button class="act-btn btn-yes" type="button">Да</button>
                    <button class="act-btn btn-no" type="button">Нет</button>
                </div>
            `;
            chatMessages.appendChild(aiMsgContainer);
            chatMessages.scrollTop = chatMessages.scrollHeight;

            aiMsgContainer.querySelector('.btn-yes')
                .addEventListener('click', () => confirmSymptom(text, aiMsgContainer));

            aiMsgContainer.querySelector('.btn-no').addEventListener('click', () => {
                aiMsgContainer.querySelector('.action-buttons').innerHTML =
                    '<span style="font-size:13px; color:#e5e7eb;">✗ Отклонено</span>';
                addMessage(state.currentQuestion || 'Опишите ваше состояние или симптомы.', 'ai');
            });
        }, 400);
    }

    sendBtn.addEventListener('click', handleUserSubmit);
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleUserSubmit();
    });

    finishBtn.addEventListener('click', () => {
        if (state.busy || state.finished) return;
        if (state.confirmedSymptoms.length === 0) {
            addMessage('Пока нет ни одной подтверждённой жалобы. Опишите, что вас беспокоит.', 'ai');
            return;
        }
        state.finished = true;
        setBusy(false);
        addMessage('Спасибо! Я собрал информацию для врача. Нажмите «К протоколу ЕМИАС» справа.', 'ai');
    });

    /* ==================== ПЕРЕХОД К ПРОТОКОЛУ ==================== */
    goToRegistryBtn.addEventListener('click', () => {
        navRegistry.disabled = false;
        navRegistry.click();
        ticketSummary.innerHTML = `<b>Собранные данные для протокола:</b><br>` +
            state.confirmedSymptoms.map(s =>
                `<div style="margin-top:8px;"><span style="color:#5f6368;">Вопрос ИИ: ${escapeHtml(s.question)}</span><br>• ${escapeHtml(s.answer)}</div>`
            ).join('');
    });

    /* ==================== SOAP ==================== */
    async function loadSoap() {
        try {
            const r = await fetch('/api/soap', { credentials: 'same-origin' });
            if (!r.ok) return;
            const data = await r.json();
            soapS.textContent = data.soap.S;
            soapO.textContent = data.soap.O;
            soapA.textContent = data.soap.A;
            soapP.textContent = data.soap.P;
        } catch (e) { /* ignore */ }
    }

    confirmRegistryBtn.addEventListener('click', () => {
        alert('Данные успешно переданы в защищённый контур ЕМИАС!');
        navMeds.disabled = false;
        navMeds.click();
    });

    /* ==================== ОТПРАВКА PDF ВРАЧУ ==================== */
    sendPdfBtn.addEventListener('click', async () => {
        const email = (doctorEmailInput.value || '').trim();
        if (!email || !email.includes('@')) {
            emailStatus.textContent = 'Укажите корректный email врача.';
            emailStatus.style.color = '#b3261e';
            return;
        }
        sendPdfBtn.disabled = true;
        emailStatus.style.color = '#235342';
        emailStatus.textContent = 'Формируем PDF и отправляем...';
        try {
            const r = await fetch('/api/send-protocol', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ email })
            });
            const data = await r.json();
            if (!r.ok) {
                emailStatus.style.color = '#b3261e';
                emailStatus.textContent = 'Ошибка: ' + (data.error || 'не удалось отправить');
            } else if (data.mode === 'simulated') {
                emailStatus.style.color = '#1a8263';
                emailStatus.textContent = `✉️ PDF сформирован и отправлен на ${data.to} (демо-режим SMTP).`;
            } else {
                emailStatus.style.color = '#1a8263';
                emailStatus.textContent = `✉️ PDF успешно отправлен врачу на ${data.to}.`;
            }
        } catch (e) {
            emailStatus.style.color = '#b3261e';
            emailStatus.textContent = 'Ошибка соединения с сервером.';
        } finally {
            sendPdfBtn.disabled = false;
        }
    });

    /* ==================== РЕЦЕПТЫ И НАПОМИНАНИЯ ==================== */
    function renderPrescriptions() {
        if (!state.prescriptions.length) {
            prescriptionsList.innerHTML = '<li class="med-empty">Здесь появятся ваши рецепты</li>';
            return;
        }
        prescriptionsList.innerHTML = state.prescriptions.map(p => `
            <li>
                💊 <b>${escapeHtml(p.name)}</b>
                ${p.dosage ? '— ' + escapeHtml(p.dosage) : ''}
                ${p.schedule ? ' · ' + escapeHtml(p.schedule) : ''}
                <button class="mini-del" data-kind="rx" data-id="${p.id}" type="button">✕</button>
            </li>
        `).join('');
        prescriptionsList.querySelectorAll('.mini-del').forEach(b => {
            b.addEventListener('click', () => removePrescription(b.dataset.id));
        });
    }

    function renderReminders() {
        if (!state.reminders.length) {
            remindersList.innerHTML = '<li class="med-empty">Напоминаний пока нет</li>';
            return;
        }
        const sorted = [...state.reminders].sort((a, b) =>
            new Date(a.time).getTime() - new Date(b.time).getTime());
        remindersList.innerHTML = sorted.map(r => {
            const dt = new Date(r.time);
            const when = isNaN(dt) ? r.time : dt.toLocaleString('ru-RU', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' });
            return `<li>⏰ <b>${escapeHtml(r.med)}</b> — ${escapeHtml(when)}
                ${r.note ? ' · ' + escapeHtml(r.note) : ''}
                <button class="mini-del" data-kind="rem" data-id="${r.id}" type="button">✕</button></li>`;
        }).join('');
        remindersList.querySelectorAll('.mini-del').forEach(b => {
            b.addEventListener('click', () => removeReminder(b.dataset.id));
        });
    }

    async function loadUserData() {
        try {
            const r = await fetch('/api/user-data', { credentials: 'same-origin' });
            if (!r.ok) return;
            const data = await r.json();
            state.prescriptions = data.prescriptions || [];
            state.reminders     = data.reminders || [];
            renderPrescriptions();
            renderReminders();
        } catch (e) { /* ignore */ }
    }

    async function addPrescription() {
        const name = rxName.value.trim();
        if (!name) return;
        const payload = { name, dosage: rxDosage.value.trim(), schedule: rxSchedule.value.trim() };
        rxName.value = rxDosage.value = rxSchedule.value = '';
        try {
            const r = await fetch('/api/prescriptions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify(payload)
            });
            const data = await r.json();
            state.prescriptions = data.prescriptions || state.prescriptions;
            renderPrescriptions();
        } catch (e) { /* ignore */ }
    }

    async function removePrescription(id) {
        try {
            const r = await fetch(`/api/prescriptions/${id}`, { method: 'DELETE', credentials: 'same-origin' });
            const data = await r.json();
            state.prescriptions = data.prescriptions || [];
            renderPrescriptions();
        } catch (e) { /* ignore */ }
    }

    async function addReminder() {
        const med = remMed.value.trim();
        const time = remTime.value;
        if (!med || !time) return;
        const payload = { med, time };
        remMed.value = ''; remTime.value = '';
        try {
            const r = await fetch('/api/reminders', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify(payload)
            });
            const data = await r.json();
            state.reminders = data.reminders || state.reminders;
            renderReminders();
        } catch (e) { /* ignore */ }
    }

    async function removeReminder(id) {
        try {
            const r = await fetch(`/api/reminders/${id}`, { method: 'DELETE', credentials: 'same-origin' });
            const data = await r.json();
            state.reminders = data.reminders || [];
            renderReminders();
        } catch (e) { /* ignore */ }
    }

    addRxBtn.addEventListener('click', addPrescription);
    addRemBtn.addEventListener('click', addReminder);

    /* ==================== НАПОМИНАНИЯ (уведомления) ==================== */
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission().catch(() => {});
    }

    const firedReminders = new Set();
    setInterval(() => {
        const now = Date.now();
        state.reminders.forEach(r => {
            if (firedReminders.has(r.id)) return;
            const t = new Date(r.time).getTime();
            if (!isNaN(t) && t <= now && now - t < 120000) {
                firedReminders.add(r.id);
                const text = `Пора принять: ${r.med}`;
                if ('Notification' in window && Notification.permission === 'granted') {
                    new Notification('ХелпИнатор', { body: text });
                }
                const li = document.createElement('li');
                li.style.background = '#fff3cd';
                li.innerHTML = `🔔 <b>${escapeHtml(r.med)}</b> — напоминание сработало`;
                remindersList.prepend(li);
            }
        });
    }, 20000);

    /* ==================== OCR ==================== */
    simUploadBtn.addEventListener('click', async () => {
        const file = ocrFileInput.files[0];
        if (!file) {
            ocrFileInput.click();
            return;
        }
        const ocrStatus = document.getElementById('ocrStatus');
        ocrStatus.textContent = 'Обрабатываем файл...';
        try {
            const fd = new FormData();
            fd.append('file', file);
            const r = await fetch('/api/ocr', { method: 'POST', body: fd, credentials: 'same-origin' });
            const data = await r.json();
            if (data.extracted_meds) {
                for (const m of data.extracted_meds) {
                    try {
                        const rr = await fetch('/api/prescriptions', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            credentials: 'same-origin',
                            body: JSON.stringify({
                                name: m.name,
                                schedule: m.schedule,
                                dosage: ''
                            })
                        });
                        const dd = await rr.json();
                        state.prescriptions = dd.prescriptions || state.prescriptions;
                    } catch (e) { /* ignore */ }
                }
                renderPrescriptions();
                ocrStatus.textContent = '✓ Распознано и добавлено в рецепты.';
            } else {
                ocrStatus.textContent = 'Не удалось распознать.';
            }
        } catch (e) {
            ocrStatus.textContent = 'Ошибка OCR.';
        }
    });

    ocrFileInput.addEventListener('change', () => {
        const ocrStatus = document.getElementById('ocrStatus');
        if (ocrFileInput.files[0]) {
            ocrStatus.textContent = 'Файл выбран: ' + ocrFileInput.files[0].name;
        }
    });

    /* ==================== СТАРТ ==================== */
    checkAuth();
});