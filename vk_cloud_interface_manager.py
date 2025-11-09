#!/usr/bin/env python3
"""
VK Cloud Network Interface Manager
Управление сетевыми интерфейсами для поиска IP-адресов в определённых диапазонах
"""

import os
import sys
import time
import logging
import signal
import json
from typing import List, Dict, Tuple, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

# Загрузка переменных окружения
load_dotenv()

# ===== КОНФИГУРАЦИЯ =====

VK_CLOUD_TOKEN = os.getenv('VK_CLOUD_AUTH_TOKEN')
PROJECT_ID = os.getenv('VK_CLOUD_PROJECT_ID')
REGION = os.getenv('VK_CLOUD_REGION', 'RegionOne')
API_URL = os.getenv('VK_CLOUD_API_URL', 'https://api.cloud.vk.com')

VM_ID = os.getenv('VM_ID')
EXTERNAL_NETWORK_ID = os.getenv('EXTERNAL_NETWORK_ID', 'ext-net')
NUM_PORTS = int(os.getenv('NUM_PORTS', '5'))

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

IP_RANGE_1_START = os.getenv('IP_RANGE_1_START', '95.163.248.10')
IP_RANGE_1_END = os.getenv('IP_RANGE_1_END', '95.163.251.250')
IP_RANGE_2_START = os.getenv('IP_RANGE_2_START', '217.16.24.1')
IP_RANGE_2_END = os.getenv('IP_RANGE_2_END', '217.16.27.253')

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = os.getenv('LOG_FILE', 'vk_cloud_manager.log')

IP_WAIT_TIMEOUT = int(os.getenv('IP_WAIT_TIMEOUT', '60'))
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '2'))
MAX_RETRIES = int(os.getenv('MAX_RETRIES', '3'))

# ===== ЛОГИРОВАНИЕ =====

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE) if LOG_FILE else logging.NullHandler()
    ]
)
logger = logging.getLogger(__name__)

# ===== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ =====

created_ports = []
shutdown_requested = False


# ===== ФУНКЦИИ ВАЛИДАЦИИ =====

def validate_config():
    """Проверка обязательных параметров конфигурации"""
    errors = []
    
    if not VK_CLOUD_TOKEN:
        errors.append("VK_CLOUD_AUTH_TOKEN не установлен")
    if not PROJECT_ID:
        errors.append("VK_CLOUD_PROJECT_ID не установлен")
    if not VM_ID:
        errors.append("VM_ID не установлен")
    if not EXTERNAL_NETWORK_ID:
        errors.append("EXTERNAL_NETWORK_ID не установлен")
    
    if errors:
        logger.error("❌ Ошибки конфигурации:")
        for error in errors:
            logger.error(f"  - {error}")
        return False
    
    logger.info("✅ Конфигурация валидна")
    return True


# ===== HTTP СЕССИЯ =====

def create_session():
    """Создание сессии с retry стратегией"""
    session = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=0.3,
        status_forcelist=(500, 502, 504)
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session


# ===== API ЗАПРОСЫ =====

def get_headers():
    """Получить заголовки для API запросов"""
    return {
        'X-Auth-Token': VK_CLOUD_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }


def create_port(session: requests.Session, network_id: str) -> Optional[Dict]:
    """Создать сетевой порт"""
    try:
        url = f"{API_URL}/v2.0/ports"
        payload = {
            "port": {
                "network_id": network_id,
                "admin_state_up": True
            }
        }
        
        response = session.post(url, json=payload, headers=get_headers(), timeout=30)
        response.raise_for_status()
        
        port_data = response.json().get('port')
        logger.info(f"✅ Порт создан: {port_data.get('id')}")
        return port_data
        
    except Exception as e:
        logger.error(f"❌ Ошибка при создании порта: {e}")
        return None


def attach_port_to_vm(session: requests.Session, port_id: str) -> bool:
    """Подключить порт к виртуальной машине"""
    try:
        url = f"{API_URL}/v2.1/servers/{VM_ID}/os-interface"
        payload = {
            "interfaceAttachment": {
                "port_id": port_id
            }
        }
        
        response = session.post(url, json=payload, headers=get_headers(), timeout=30)
        response.raise_for_status()
        
        logger.info(f"✅ Порт {port_id} подключен к ВМ")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка при подключении порта: {e}")
        return False


def get_port_info(session: requests.Session, port_id: str) -> Optional[Dict]:
    """Получить информацию о порте (включая IP)"""
    try:
        url = f"{API_URL}/v2.0/ports/{port_id}"
        response = session.get(url, headers=get_headers(), timeout=30)
        response.raise_for_status()
        
        return response.json().get('port')
        
    except Exception as e:
        logger.error(f"❌ Ошибка при получении информации о порте: {e}")
        return None


def detach_port_from_vm(session: requests.Session, port_id: str) -> bool:
    """Отключить порт от виртуальной машины"""
    try:
        url = f"{API_URL}/v2.1/servers/{VM_ID}/os-interface/{port_id}"
        response = session.delete(url, headers=get_headers(), timeout=30)
        response.raise_for_status()
        
        logger.info(f"✅ Порт {port_id} отключен от ВМ")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка при отключении порта: {e}")
        return False


def delete_port(session: requests.Session, port_id: str) -> bool:
    """Удалить сетевой порт"""
    try:
        url = f"{API_URL}/v2.0/ports/{port_id}"
        response = session.delete(url, headers=get_headers(), timeout=30)
        response.raise_for_status()
        
        logger.info(f"✅ Порт {port_id} удален")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка при удалении порта: {e}")
        return False


# ===== ПРОВЕРКА IP =====

def ip_to_int(ip: str) -> int:
    """Преобразовать IP адрес в число"""
    parts = ip.split('.')
    return (int(parts[0]) << 24) + (int(parts[1]) << 16) + (int(parts[2]) << 8) + int(parts[3])


def check_ip_in_range(ip: str, range_start: str, range_end: str) -> bool:
    """Проверить находится ли IP в диапазоне"""
    try:
        ip_num = ip_to_int(ip)
        start_num = ip_to_int(range_start)
        end_num = ip_to_int(range_end)
        return start_num <= ip_num <= end_num
    except:
        return False


def is_ip_in_allowed_ranges(ip: str) -> bool:
    """Проверить находится ли IP в разрешённых диапазонах"""
    if check_ip_in_range(ip, IP_RANGE_1_START, IP_RANGE_1_END):
        logger.info(f"🎯 IP {ip} найден в диапазоне 1: {IP_RANGE_1_START}-{IP_RANGE_1_END}")
        return True
    
    if check_ip_in_range(ip, IP_RANGE_2_START, IP_RANGE_2_END):
        logger.info(f"🎯 IP {ip} найден в диапазоне 2: {IP_RANGE_2_START}-{IP_RANGE_2_END}")
        return True
    
    return False


def extract_ip(port_info: Dict) -> Optional[str]:
    """Извлечь IP адрес из информации о порте"""
    try:
        fixed_ips = port_info.get('fixed_ips', [])
        if fixed_ips and len(fixed_ips) > 0:
            return fixed_ips[0].get('ip_address')
    except:
        pass
    return None


# ===== TELEGRAM УВЕДОМЛЕНИЯ =====

def send_telegram_message(message: str) -> bool:
    """Отправить сообщение в Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.warning(f"⚠️  Не удалось отправить Telegram сообщение: {e}")
        return False


# ===== ОСНОВНАЯ ЛОГИКА =====

def cleanup_all_ports(session: requests.Session):
    """Очистить все созданные порты при ошибке"""
    logger.info("🧹 Удаление всех созданных портов...")
    
    for port_id in created_ports:
        detach_port_from_vm(session, port_id)
        time.sleep(1)
        delete_port(session, port_id)
    
    created_ports.clear()


def run_iteration(iteration: int) -> Tuple[bool, Optional[str]]:
    """Запустить одну итерацию попытки"""
    logger.info(f"\n{'='*60}")
    logger.info(f"🔄 Попытка #{iteration}")
    logger.info(f"{'='*60}")
    
    session = create_session()
    ports_to_check = []
    
    try:
        # 1. Создание портов
        logger.info(f"📌 Создание {NUM_PORTS} портов...")
        for i in range(NUM_PORTS):
            if shutdown_requested:
                raise KeyboardInterrupt("Получена команда завершения")
            
            port_info = create_port(session, EXTERNAL_NETWORK_ID)
            if port_info:
                ports_to_check.append(port_info['id'])
                created_ports.append(port_info['id'])
            time.sleep(0.5)
        
        if not ports_to_check:
            logger.error("❌ Не удалось создать порты")
            return False, None
        
        # 2. Подключение портов к ВМ
        logger.info(f"🔗 Подключение портов к ВМ...")
        for port_id in ports_to_check:
            if shutdown_requested:
                raise KeyboardInterrupt("Получена команда завершения")
            
            attach_port_to_vm(session, port_id)
            time.sleep(0.5)
        
        # 3. Ожидание получения IP адресов
        logger.info(f"⏳ Ожидание получения IP адресов (до {IP_WAIT_TIMEOUT} сек)...")
        start_time = time.time()
        
        while time.time() - start_time < IP_WAIT_TIMEOUT:
            if shutdown_requested:
                raise KeyboardInterrupt("Получена команда завершения")
            
            for port_id in ports_to_check[:]:
                port_info = get_port_info(session, port_id)
                if not port_info:
                    continue
                
                ip = extract_ip(port_info)
                if ip:
                    logger.info(f"📍 Порт {port_id}: IP = {ip}")
                    
                    # Проверка IP на соответствие диапазонам
                    if is_ip_in_allowed_ranges(ip):
                        logger.info(f"\n✨ УСПЕХ! Найден нужный IP: {ip}")
                        send_telegram_message(f"✨ Найден IP: {ip}")
                        
                        # Отключение остальных портов
                        logger.info("🧹 Удаление лишних портов...")
                        for other_port_id in ports_to_check:
                            if other_port_id != port_id:
                                detach_port_from_vm(session, other_port_id)
                                time.sleep(0.5)
                                delete_port(session, other_port_id)
                                created_ports.remove(other_port_id)
                        
                        return True, ip
            
            time.sleep(CHECK_INTERVAL)
        
        # 4. Если IP не найден - удаление всех портов
        logger.warning("⚠️  IP адреса не найдены в диапазонах. Удаление портов...")
        cleanup_all_ports(session)
        return False, None
    
    except KeyboardInterrupt as e:
        logger.warning(f"🛑 Процесс прерван: {e}")
        cleanup_all_ports(session)
        raise
    
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        cleanup_all_ports(session)
        return False, None
    
    finally:
        session.close()


def signal_handler(sig, frame):
    """Обработчик сигнала Ctrl+C"""
    global shutdown_requested
    shutdown_requested = True
    logger.warning("\n🛑 Получена команда завершения (Ctrl+C)")
    logger.info("Выполняется очистка... Пожалуйста, подождите.")


def main():
    """Основная функция"""
    signal.signal(signal.SIGINT, signal_handler)
    
    logger.info("🚀 VK Cloud Network Interface Manager")
    logger.info(f"Начало работы: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Валидация конфигурации
    if not validate_config():
        sys.exit(1)
    
    # Запуск итераций
    iteration = 0
    while iteration < MAX_RETRIES:
        if shutdown_requested:
            break
        
        iteration += 1
        success, found_ip = run_iteration(iteration)
        
        if success and found_ip:
            logger.info(f"\n✅ ЗАВЕРШЕНО УСПЕШНО!")
            logger.info(f"Найденный IP: {found_ip}")
            send_telegram_message(f"✅ Процесс завершён. IP: {found_ip}")
            sys.exit(0)
        
        if shutdown_requested:
            break
        
        if iteration < MAX_RETRIES:
            logger.info(f"⏳ Ожидание перед следующей попыткой...")
            for i in range(10):
                if shutdown_requested:
                    break
                time.sleep(1)
    
    logger.error(f"❌ Не удалось найти IP после {iteration} попыток")
    send_telegram_message(f"❌ Не удалось найти IP после {iteration} попыток")
    sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("🛑 Программа завершена пользователем")
        sys.exit(0)
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
        sys.exit(1)
