import os
import sys
import requests
from dotenv import load_dotenv

# Принудительная кодировка UTF-8 для Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv(override=True)

TOKEN = os.getenv('VK_CLOUD_AUTH_TOKEN')
NEUTRON_URL = 'https://infra.mail.ru:9696/v2.0'
NOVA_URL = 'https://infra.mail.ru:8774/v2.1'
VM_ID = os.getenv('VM_ID')

if not TOKEN:
    print("Токен не найден в .env")
    sys.exit(1)

headers = {
    'X-Auth-Token': TOKEN,
    'Content-Type': 'application/json'
}

def get_vm_interfaces():
    """Получить список ID портов, подключенных к целевой ВМ"""
    try:
        url = f"{NOVA_URL}/servers/{VM_ID}/os-interface"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            return [iface['port_id'] for iface in resp.json().get('interfaceAttachments', [])]
    except Exception:
        pass
    return []

SAFE_IP = os.getenv('SAFE_IP')
if not SAFE_IP:
    print("SAFE_IP не найден в .env. Укажите IP основного интерфейса ВМ.")
    sys.exit(1)

def detach_and_delete(port_id):
    print(f"Отключение порта {port_id} от ВМ...")
    try:
        requests.delete(f"{NOVA_URL}/servers/{VM_ID}/os-interface/{port_id}", headers=headers, timeout=10)
    except Exception as e:
        print(f"   Ошибка отключения (возможно уже отключен): {e}")
    
    print(f"Удаление порта {port_id}...")
    try:
        requests.delete(f"{NEUTRON_URL}/ports/{port_id}", headers=headers, timeout=10)
        print("   Удален")
        return True
    except Exception as e:
        print(f"   Ошибка удаления: {e}")
        return False

def cleanup():
    print("Анализ портов...")
    
    try:
        resp = requests.get(f"{NEUTRON_URL}/ports", headers=headers, timeout=30)
        resp.raise_for_status()
        all_ports = resp.json().get('ports', [])
    except Exception as e:
        print(f"Ошибка получения списка портов: {e}")
        return

    deleted_count = 0
    
    for port in all_ports:
        port_id = port.get('id')
        device_id = port.get('device_id')
        ips = [ip['ip_address'] for ip in port.get('fixed_ips', [])]
        
        # Если это наш SAFE_IP - пропускаем
        if SAFE_IP in ips:
            print(f"Порт {port_id} ({ips}) ЗАЩИЩЕН (SAFE_IP). Пропуск.")
            continue
            
        # Если порт висит (не привязан) - удаляем
        if not device_id:
             print(f"Found detached port {port_id} ({ips})")
             if detach_and_delete(port_id):
                 deleted_count += 1
                 
        # Если порт привязан к НАШЕЙ ВМ, но это не SAFE_IP - удаляем
        elif device_id == VM_ID:
             print(f"Found attached EXTRA port {port_id} ({ips}) on our VM")
             if detach_and_delete(port_id):
                 deleted_count += 1
                 
    print(f"\nОчистка завершена. Удалено портов: {deleted_count}")


if __name__ == "__main__":
    cleanup()