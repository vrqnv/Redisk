import yadisk
from urllib.parse import urlsplit
from webdav3.client import Client as WebDAVClient

try:
    from .config import YANDEX_TOKEN, NEXTCLOUD_CONFIG
except ImportError:
    from config import YANDEX_TOKEN, NEXTCLOUD_CONFIG


class CloudAPI:
    def __init__(self):
        self.yandex = None
        try:
            self.yandex = yadisk.YaDisk(token=YANDEX_TOKEN)
            if self.yandex.check_token():
                print("Яндекс.Диск: подключен")
            else:
                print("Яндекс.Диск: неверный токен")
                self.yandex = None
        except Exception as e:
            print(f"Яндекс.Диск: ошибка - {e}")
            self.yandex = None

        self.nextcloud = None
        if NEXTCLOUD_CONFIG:
            try:
                parsed = urlsplit(NEXTCLOUD_CONFIG["url"])
                hostname = f"{parsed.scheme}://{parsed.netloc}"
                root = parsed.path if parsed.path else "/"
                self.nextcloud = WebDAVClient({
                    'webdav_hostname': hostname,
                    'webdav_root': root,
                    'webdav_login': NEXTCLOUD_CONFIG['login'],
                    'webdav_password': NEXTCLOUD_CONFIG['password']
                })
                self.nextcloud.list("/")
                print("NextCloud: подключен")
            except Exception as e:
                print(f"NextCloud: ошибка - {e}")
                self.nextcloud = None
        else:
            print("NextCloud: не настроен")


    def yandex_list_files(self, path="/"):
        if not self.yandex:
            print("Яндекс.Диск не подключен")
            return []
        
        try:
            result = []
            for item in self.yandex.listdir(path):
                file_info = {
                    'name': item.name,
                    'type': 'dir' if item.is_dir else 'file',
                    'size': item.size if hasattr(item, 'size') else 0,
                    'modified': 0
                }
                if hasattr(item, 'modified') and item.modified:
                    file_info['modified'] = int(item.modified.timestamp())
                result.append(file_info)
            return result
        except Exception as e:
            print(f"Ошибка списка файлов Яндекса: {e}")
            return []
    
    def yandex_download(self, cloud_path, local_path):
        if not self.yandex:
            print("Яндекс.Диск не подключен")
            return False
        
        try:
            self.yandex.download(cloud_path, local_path)
            print(f"Скачан: {cloud_path} -> {local_path}")
            return True
        except Exception as e:
            print(f"Ошибка скачивания: {e}")
            return False
    
    def yandex_upload(self, local_path, cloud_path):
        if not self.yandex:
            print("Яндекс.Диск не подключен")
            return False
        
        try:
            self.yandex.upload(local_path, cloud_path)
            print(f"Загружен: {local_path} -> {cloud_path}")
            return True
        except Exception as e:
            print(f"Ошибка загрузки: {e}")
            return False
    
    def yandex_delete(self, cloud_path):
        if not self.yandex:
            print("Яндекс.Диск не подключен")
            return False
        
        try:
            self.yandex.remove(cloud_path)
            print(f"Удалён: {cloud_path}")
            return True
        except Exception as e:
            print(f"Ошибка удаления: {e}")
            return False
    
    def yandex_mkdir(self, path):
        if not self.yandex:
            print("Яндекс.Диск не подключен")
            return False
        
        try:
            self.yandex.mkdir(path)
            print(f"Создана папка: {path}")
            return True
        except Exception as e:
            print(f"Ошибка создания папки: {e}")
            return False
    
    def yandex_create_share_link(self, cloud_path):
        if not self.yandex:
            print("Яндекс.Диск не подключен")
            return None
        
        try:
            self.yandex.publish(cloud_path)
            meta = self.yandex.get_meta(cloud_path)
            public_url = meta.public_url
            print(f"Ссылка создана: {public_url}")
            return public_url
        except Exception as e:
            print(f"Ошибка создания ссылки: {e}")
            return None

    def nextcloud_list_files(self, path="/"):
        if not self.nextcloud:
            print("NextCloud не подключен")
            return []
        
        try:
            items = self.nextcloud.list(path)
            result = []
            for item in items:
                file_info = {
                    'name': item.get('name', ''),
                    'type': 'dir' if item.get('is_dir', False) else 'file',
                    'size': item.get('size', 0),
                    'modified': item.get('modified', 0)
                }
                result.append(file_info)
            return result
        except Exception as e:
            print(f"Ошибка списка файлов NextCloud: {e}")
            return []
    
    def nextcloud_download(self, cloud_path, local_path):
        if not self.nextcloud:
            print("NextCloud не подключен")
            return False
        
        try:
            self.nextcloud.download_file(cloud_path, local_path)
            print(f"Скачан: {cloud_path} -> {local_path}")
            return True
        except Exception as e:
            print(f"Ошибка скачивания: {e}")
            return False
    
    def nextcloud_upload(self, local_path, cloud_path):
        if not self.nextcloud:
            print("NextCloud не подключен")
            return False
        
        try:
            self.nextcloud.upload_file(local_path, cloud_path)
            print(f"Загружен: {local_path} -> {cloud_path}")
            return True
        except Exception as e:
            print(f"Ошибка загрузки: {e}")
            return False
    
    def nextcloud_delete(self, cloud_path):
        if not self.nextcloud:
            print("NextCloud не подключен")
            return False
        
        try:
            self.nextcloud.clean(cloud_path)
            print(f"Удалён: {cloud_path}")
            return True
        except Exception as e:
            print(f"Ошибка удаления: {e}")
            return False
    
    def nextcloud_mkdir(self, path):
        if not self.nextcloud:
            print("NextCloud не подключен")
            return False
        
        try:
            self.nextcloud.mkdir(path)
            print(f"Создана папка: {path}")
            return True
        except Exception as e:
            print(f"Ошибка создания папки: {e}")
            return False
    
    def nextcloud_create_share_link(self, cloud_path):
        if not self.nextcloud:
            print("NextCloud не подключен")
            return None
        
        print("Создание ссылок для NextCloud пока не реализовано")
        return None


if __name__ == "__main__":   
    api = CloudAPI()
