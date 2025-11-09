#!/usr/bin/env python3
"""
Тестирование подключения к VK Cloud API
"""

import os
import sys
from dotenv import load_dotenv
import requests

load_dotenv()

VK_CLOUD_TOKEN = os.getenv('VK_CLOUD_AUTH_TOKEN')
PROJECT_ID = os.getenv('VK_CLOUD_PROJECT_ID')
API_URL = os.getenv('VK_CLOUD_API_URL', 'https://api.cloud.vk.com')
VM_ID = os.getenv('VM_ID')
EXTERNAL_NETWORK_ID = os.getenv('EXTERNAL_NETWORK_ID')

def test_connection():
    """Тестирование подключения к API"""
    print("🔍 Проверка подключения к VK Cloud API")
    print("=" * 60)
    
    # Проверка конфигурации
    checks = {
        "VK_CLOUD_AUTH_TOKEN": VK_CLOUD_TOKEN,
        "VK_CLOUD_PROJECT_ID": PROJECT_ID,
        "VM_ID": VM_ID,
        "EXTERNAL_NETWORK_ID": EXTERNAL_NETWORK_ID,
        "VK_CLOUD_API_URL": API_URL
    }
    
    print("\n📋 Конфигурация:")
    for key, value in checks.items():
        status = "✅" if value else "❌"
        display_value = value[:20] + "..." if len(str(value)) > 20 else value
        print(f"  {status} {key}: {display_value}")
    
    if not all(checks.values()):
        print("\n❌ Не все параметры конфигурации установлены!")
        return False
    
    # Тест API
    print("\n🌐 Тестирование API запросов:")
    
    headers = {
        'X-Auth-Token': VK_CLOUD_TOKEN,
        'Content-Type': 'application/json'
    }
    
    # Тест 1: Получение информации о проекте
    try:
        url = f"{API_URL}/v2.0/networks"
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            print("  ✅ Подключение к API успешно")
        else:
            print(f"  ❌ Ошибка API: {response.status_code}")
            print(f"     {response.text}")
            return False
            
    except Exception as e:
        print(f"  ❌ Ошибка подключения: {e}")
        return False
    
    # Тест 2: Получение информации о ВМ
    try:
        url = f"{API_URL}/v2.1/servers/{VM_ID}"
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            print("  ✅ ВМ найдена и доступна")
            vm_info = response.json().get('server', {})
            print(f"     Статус: {vm_info.get('status')}")
            print(f"     Имя: {vm_info.get('name')}")
        elif response.status_code == 404:
            print(f"  ❌ ВМ не найдена (ID: {VM_ID})")
            return False
        else:
            print(f"  ❌ Ошибка при получении информации о ВМ: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"  ❌ Ошибка при получении информации о ВМ: {e}")
        return False
    
    # Тест 3: Проверка сети
    try:
        url = f"{API_URL}/v2.0/networks"
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            networks = response.json().get('networks', [])
            ext_net = next((n for n in networks if n['id'] == EXTERNAL_NETWORK_ID or n['name'] == EXTERNAL_NETWORK_ID), None)
            
            if ext_net:
                print(f"  ✅ Внешняя сеть найдена: {ext_net.get('name')}")
            else:
                print(f"  ⚠️  Сеть не найдена. Доступные сети:")
                for net in networks:
                    print(f"     - {net['name']} ({net['id']})")
                    
    except Exception as e:
        print(f"  ⚠️  Ошибка при проверке сети: {e}")
    
    print("\n✅ Все проверки пройдены успешно!")
    return True

if __name__ == '__main__':
    success = test_connection()
    sys.exit(0 if success else 1)
