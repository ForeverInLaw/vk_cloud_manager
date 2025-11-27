#!/usr/bin/env python3
"""
VK Cloud Network Interface Manager
Управление сетевыми интерфейсами для поиска IP-адресов в определённых диапазонах
"""

import threading
from concurrent.futures import ThreadPoolExecutor
import requests
from requests.exceptions import ReadTimeout, ConnectTimeout
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import os
import sys
import time
import logging
import signal
import json
from typing import List, Dict, Tuple, Optional
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(override=True)

# ===== КОНФИГУРАЦИЯ =====

VK_CLOUD_TOKEN = os.getenv('VK_CLOUD_AUTH_TOKEN')
PROJECT_ID = os.getenv('VK_CLOUD_PROJECT_ID')
REGION = os.getenv('VK_CLOUD_REGION', 'RegionOne')

NOVA_API_URL = 'https://infra.mail.ru:8774/v2.1'
NEUTRON_API_URL = 'https://infra.mail.ru:9696/v2.0'

VM_ID = os.getenv('VM_ID')
EXTERNAL_NETWORK_ID = os.getenv('EXTERNAL_NETWORK_ID', 'ext-net')
NUM_PORTS = int(os.getenv('NUM_PORTS', '5'))
SAFE_IP = os.getenv('SAFE_IP')

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
MAX_RETRIES = int(os.getenv('MAX_RETRIES', '100'))
REQUEST_TIMEOUT = 60

# ===== ЛОГИРОВАНИЕ =====

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding='utf-8') if LOG_FILE else logging.NullHandler()
    ]
)
logger = logging.getLogger(__name__)

# ===== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ =====

stop_event = threading.Event()
pool_semaphore = None 
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
        logger.error("Ошибки конфигурации:")
        for error in errors:
            logger.error(f"  - {error}")
        return False
    
    logger.info("Конфигурация валидна")
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
    return {
        'X-Auth-Token': VK_CLOUD_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

def create_port(session: requests.Session, network_id: str) -> Optional[Dict]:
    """Создать сетевой порт"""
    try:
        url = f"{NEUTRON_API_URL}/ports"
        payload = {
            "port": {
                "network_id": network_id,
                "admin_state_up": True
            }
        }
        
        response = session.post(url, json=payload, headers=get_headers(), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        
        port_data = response.json().get('port')
        logger.info(f"Порт создан: {port_data.get('id')}")
        return port_data
        
    except Exception as e:
        error_msg = f"Ошибка при создании порта: {e}"
        if hasattr(e, 'response') and e.response is not None:
            error_msg += f"\nResponse: {e.response.text}"
        logger.error(error_msg)
        return None

def attach_port_to_vm(session: requests.Session, port_id: str) -> bool:
    """Подключить порт к виртуальной машине"""
    try:
        url = f"{NOVA_API_URL}/servers/{VM_ID}/os-interface"
        payload = {
            "interfaceAttachment": {
                "port_id": port_id
            }
        }
        
        response = session.post(url, json=payload, headers=get_headers(), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        
        logger.info(f"Порт {port_id} подключен к ВМ")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при подключении порта: {e}")
        return False

def get_port_info(session: requests.Session, port_id: str) -> Optional[Dict]:
    """Получить информацию о порте (включая IP)"""
    try:
        url = f"{NEUTRON_API_URL}/ports/{port_id}"
        response = session.get(url, headers=get_headers(), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        
        return response.json().get('port')
        
    except Exception as e:
        logger.error(f"Ошибка при получении информации о порте: {e}")
        return None

def detach_port_from_vm(session: requests.Session, port_id: str) -> bool:
    """Отключить порт от виртуальной машины"""
    try:
        url = f"{NOVA_API_URL}/servers/{VM_ID}/os-interface/{port_id}"
        response = session.delete(url, headers=get_headers(), timeout=REQUEST_TIMEOUT)
        if response.status_code != 404:
            response.raise_for_status()
        
        logger.info(f"Порт {port_id} отключен от ВМ")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при отключении порта: {e}")
        return False

def delete_port(session: requests.Session, port_id: str) -> bool:
    """Удалить сетевой порт"""
    try:
        url = f"{NEUTRON_API_URL}/ports/{port_id}"
        response = session.delete(url, headers=get_headers(), timeout=REQUEST_TIMEOUT)
        if response.status_code != 404:
             response.raise_for_status()
        
        logger.info(f"Порт {port_id} удален")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при удалении порта: {e}")
        return False

# ===== ПРОВЕРКА IP =====

def ip_to_int(ip: str) -> int:
    parts = ip.split('.')
    return (int(parts[0]) << 24) + (int(parts[1]) << 16) + (int(parts[2]) << 8) + int(parts[3])

def check_ip_in_range(ip: str, range_start: str, range_end: str) -> bool:
    try:
        ip_num = ip_to_int(ip)
        start_num = ip_to_int(range_start)
        end_num = ip_to_int(range_end)
        return start_num <= ip_num <= end_num
    except:
        return False

def is_ip_in_allowed_ranges(ip: str) -> bool:
    if check_ip_in_range(ip, IP_RANGE_1_START, IP_RANGE_1_END):
        logger.info(f"IP {ip} найден в диапазоне 1: {IP_RANGE_1_START}-{IP_RANGE_1_END}")
        return True
    
    if check_ip_in_range(ip, IP_RANGE_2_START, IP_RANGE_2_END):
        logger.info(f"IP {ip} найден в диапазоне 2: {IP_RANGE_2_START}-{IP_RANGE_2_END}")
        return True
    
    return False

def extract_ip(port_info: Dict) -> Optional[str]:
    try:
        fixed_ips = port_info.get('fixed_ips', [])
        if fixed_ips and len(fixed_ips) > 0:
            return fixed_ips[0].get('ip_address')
    except:
        pass
    return None

# ===== TELEGRAM УВЕДОМЛЕНИЯ =====

def send_telegram_message(message: str) -> bool:
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
        logger.warning(f"Не удалось отправить Telegram сообщение: {e}")
        return False

# ===== ОЧИСТКА =====

def cleanup_orphaned_ports(session: requests.Session):
    """Полная очистка всех лишних портов"""
    logger.info("Запуск агрессивной очистки портов...")
    try:
        url = f"{NEUTRON_API_URL}/ports"
        resp = session.get(url, headers=get_headers(), timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        all_ports = resp.json().get('ports', [])
        
        deleted_count = 0
        
        for port in all_ports:
            port_id = port.get('id')
            device_id = port.get('device_id')
            ips = [ip['ip_address'] for ip in port.get('fixed_ips', [])]
            
            if SAFE_IP in ips:
                logger.info(f"Порт {port_id} ({ips}) ЗАЩИЩЕН. Пропуск.")
                continue
            
            should_delete = False
            if not device_id:
                logger.info(f"Найден висячий порт {port_id} ({ips}). Удаляю...")
                should_delete = True
            elif device_id == VM_ID:
                logger.info(f"Найден лишний порт на ВМ {port_id} ({ips}). Отключаю и удаляю...")
                detach_port_from_vm(session, port_id)
                time.sleep(1)
                should_delete = True
            
            if should_delete:
                if delete_port(session, port_id):
                    deleted_count += 1
                    
        logger.info(f"Очистка завершена. Удалено: {deleted_count}")
            
    except Exception as e:
        logger.error(f"Ошибка при очистке портов: {e}")

# ===== ПОТОЧНАЯ ЛОГИКА =====

def worker_task(task_id: int):
    """Задача для одного потока: создать, проверить, удалить/оставить"""
    
    if stop_event.is_set() or shutdown_requested:
        pool_semaphore.release()
        return

    session = create_session()
    port_id = None
    
    try:
        logger.info(f"[Поток {task_id}] Начинаю поиск...")
        
        port_info = create_port(session, EXTERNAL_NETWORK_ID)
        if not port_info:
            logger.warning(f"[Поток {task_id}] Не удалось создать порт. Ретрай...")
            return 
            
        port_id = port_info['id']
        
        if stop_event.is_set():
            return

        if not attach_port_to_vm(session, port_id):
            return

        start_time = time.time()
        ip_found = False
        
        while time.time() - start_time < 40:
            if stop_event.is_set() or shutdown_requested:
                return

            port_info = get_port_info(session, port_id)
            if port_info:
                ip = extract_ip(port_info)
                if ip:
                    if is_ip_in_allowed_ranges(ip):
                        logger.info(f"\n[Поток {task_id}] НАЙДЕН IP: {ip}!")
                        send_telegram_message(f"Найден IP: {ip}")
                        stop_event.set()
                        ip_found = True
                        return
                    else:
                        logger.info(f"[Поток {task_id}] IP {ip} не подходит.")
                        break
            
            time.sleep(2)
            
    except Exception as e:
        logger.error(f"[Поток {task_id}] Ошибка: {e}")
        
    finally:
        should_cleanup = True
        if 'ip_found' in locals() and ip_found:
            should_cleanup = False
            
        if should_cleanup and port_id:
            logger.info(f"[Поток {task_id}] Удаление порта {port_id}...")
            detach_port_from_vm(session, port_id)
            time.sleep(1) 
            delete_port(session, port_id)
            
        session.close()
        pool_semaphore.release()

def signal_handler(sig, frame):
    """Обработчик сигнала Ctrl+C"""
    global shutdown_requested
    shutdown_requested = True
    stop_event.set()
    logger.warning("Получена команда завершения (Ctrl+C)")
    logger.info("Выполняется очистка... Пожалуйста, подождите.")

def main():
    """Основная функция"""
    global pool_semaphore
    signal.signal(signal.SIGINT, signal_handler)
    
    logger.info("VK Cloud Network Interface Manager (Multi-threaded)")
    logger.info(f"Начало работы: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if not validate_config():
        sys.exit(1)
        
    session = create_session()
    cleanup_orphaned_ports(session)
    session.close()
    
    pool_semaphore = threading.BoundedSemaphore(NUM_PORTS)
    
    logger.info(f"Запуск пула потоков ({NUM_PORTS} воркеров)...")
    
    with ThreadPoolExecutor(max_workers=NUM_PORTS) as executor:
        task_counter = 0
        
        while not stop_event.is_set() and not shutdown_requested:
            pool_semaphore.acquire() 
            
            if stop_event.is_set() or shutdown_requested:
                break
                
            task_counter += 1
            executor.submit(worker_task, task_counter)
            
            time.sleep(1.0)
            
    if stop_event.is_set():
        logger.info("Программа завершена: IP найден!")
    else:
        logger.info("Программа завершена пользователем")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
