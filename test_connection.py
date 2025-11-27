#!/usr/bin/env python3
"""
Тестирование подключения к VK Cloud API
"""

import os
import sys
from dotenv import load_dotenv
import requests

load_dotenv(override=True)

VK_CLOUD_TOKEN = os.getenv('VK_CLOUD_AUTH_TOKEN')
PROJECT_ID = os.getenv('VK_CLOUD_PROJECT_ID')
NOVA_API_URL = 'https://infra.mail.ru:8774/v2.1'
NEUTRON_API_URL = 'https://infra.mail.ru:9696/v2.0'

VM_ID = os.getenv('VM_ID')
EXTERNAL_NETWORK_ID = os.getenv('EXTERNAL_NETWORK_ID')

def test_connection():
    """Тестирование подключения к API"""
    print("Проверка подключения к VK Cloud API")
    print("=" * 60)
    
    # Проверка конфигурации
    checks = {
        "VK_CLOUD_AUTH_TOKEN": VK_CLOUD_TOKEN,
        "VK_CLOUD_PROJECT_ID": PROJECT_ID,
        "VM_ID": VM_ID,
        "EXTERNAL_NETWORK_ID": EXTERNAL_NETWORK_ID,
        "NOVA_API_URL": NOVA_API_URL,
        "NEUTRON_API_URL": NEUTRON_API_URL
    }
    
    print("\nКонфигурация:")
    for key, value in checks.items():
        status = "OK" if value else "ОШИБКА"
        display_value = value[:20] + "..." if len(str(value)) > 20 else value
        print(f"  {status} {key}: {display_value}")
    
    if not all(checks.values()):
        print("\nНе все параметры конфигурации установлены!")
        return False
    
    # Тест API
    print("\nТестирование API запросов:")
    
    headers = {
        'X-Auth-Token': VK_CLOUD_TOKEN,
        'Content-Type': 'application/json'
    }
    
    # Тест 1: Проверка Neutron API (сети)
    try:
        print(f"  Checking Neutron API ({NEUTRON_API_URL})...")
        url = f"{NEUTRON_API_URL}/networks"
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            print("  Neutron API доступен")
            
            networks = response.json().get('networks', [])
            ext_net = next((n for n in networks if n['id'] == EXTERNAL_NETWORK_ID or n['name'] == EXTERNAL_NETWORK_ID), None)
            
            if ext_net:
                print(f"     Внешняя сеть найдена: {ext_net.get('name')}")
            else:
                print(f"     Сеть {EXTERNAL_NETWORK_ID} не найдена. Доступно сетей: {len(networks)}")
        else:
            print(f"  Ошибка Neutron API: {response.status_code}")
            print(f"     {response.text}")
            return False
            
    except Exception as e:
        print(f"  Ошибка подключения к Neutron: {e}")
        return False
    
    # Тест 2: Проверка Nova API (серверы)
    try:
        print(f"  Checking Nova API ({NOVA_API_URL})...")
        url = f"{NOVA_API_URL}/servers/{VM_ID}"
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            print("  Nova API доступен и ВМ найдена")
            vm_info = response.json().get('server', {})
            print(f"     Статус: {vm_info.get('status')}")
            print(f"     Имя: {vm_info.get('name')}")
        elif response.status_code == 404:
            print(f"  ВМ не найдена (ID: {VM_ID})")
            
            # Попытка получить список всех серверов
            try:
                list_url = f"{NOVA_API_URL}/servers/detail"
                list_resp = requests.get(list_url, headers=headers, timeout=10)
                if list_resp.status_code == 200:
                    servers = list_resp.json().get('servers', [])
                    print("\n  Доступные серверы в проекте:")
                    if not servers:
                        print("     (нет серверов)")
                    for srv in servers:
                        print(f"     - {srv['name']} (ID: {srv['id']}) | Status: {srv['status']}")
                else:
                    print(f"  Не удалось получить список серверов: {list_resp.status_code}")
            except Exception as list_e:
                print(f"  Ошибка при получении списка серверов: {list_e}")
                
            return False
        else:
            print(f"  Ошибка Nova API: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"  Ошибка подключения к Nova: {e}")
        return False
    
    print("\nВсе проверки пройдены успешно!")
    return True

if __name__ == '__main__':
    success = test_connection()
    sys.exit(0 if success else 1)