#!/bin/bash

# VK Cloud Network Interface Manager - Скрипт запуска
# Для использования на Ubuntu/Linux серверах

set -e

echo "VK Cloud Network Interface Manager"
echo "======================================"

# Проверка Python
if ! command -v python3 &> /dev/null; then
    echo "Python3 не установлен"
    exit 1
fi

# Проверка файла .env
if [ ! -f ".env" ]; then
    echo "Файл .env не найден. Копирую из env.example..."
    cp env.example .env
    echo "Отредактируйте .env перед запуском"
    exit 1
fi

# Установка зависимостей если нужно
if [ ! -d "venv" ]; then
    echo "Создаю виртуальное окружение..."
    python3 -m venv venv
fi

# Активация виртуального окружения
source venv/bin/activate

# Установка зависимостей
echo "Установка зависимостей..."
pip install -r requirements.txt -q

# Запуск тестирования подключения
echo "Проверка подключения к API..."
python3 test_connection.py

# Запуск основного скрипта
echo "Запускаю основной скрипт..."
python3 vk_cloud_interface_manager.py

deactivate
