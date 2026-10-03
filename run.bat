@echo off
chcp 65001 > nul
echo === Запуск установки и сервера ИИ-помощника СберМедИИ ===

:: Проверка наличия Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [Ошибка] Python не найден! Установите Python и добавьте его в PATH.
    pause
    exit /b
)

:: Создание виртуального окружения, если его нет
if not exist venv (
    echo [1/4] Создание виртуального окружения (venv)...
    python -m venv venv
) else (
    echo [1/4] Виртуальное окружение уже существует.
)

:: Активация окружения и обновление pip
echo [2/4] Обновление менеджера пакетов...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip

:: Установка зависимостей
if exist requirements.txt (
    echo [3/4] Установка зависимостей из requirements.txt...
    pip install -r requirements.txt
) else (
    echo [3/4] Файл requirements.txt не найден! Устанавливаем fastapi и uvicorn вручную...
    pip install fastapi uvicorn
)

:: Запуск сервера
echo [4/4] Запуск сервера Uvicorn...
echo Откройте в браузере: http://127.0.0.1:8000
uvicorn server:app --reload

pause