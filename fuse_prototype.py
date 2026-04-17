#!/usr/bin/env python3
"""
Простейший FUSE-прототип для демонстрации идеи.
Монтирует виртуальную папку с несколькими фейковыми файлами.
"""

import os
import sys
import logging
from fuse import FUSE, FuseOSError, Operations

# Настраиваем логирование, чтобы видеть, что происходит
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(message)s')

class SimpleCloudFS(Operations):
    """Простая FUSE-файловая система-заглушка"""
    
    def __init__(self):
        # Эмулируем содержимое облачной папки
        # Это вместо реального API и БД
        self.files = {
            '/': {
                'type': 'dir',
                'children': ['hello.txt', 'фото.jpg', 'Документы']
            },
            '/hello.txt': {
                'type': 'file',
                'content': b'Hello from FUSE! Этот файл эмулирует облачный файл.\n',
                'size': 52,
                'permissions': 0o644
            },
            '/фото.jpg': {
                'type': 'file',
                'content': b'[ЭТО ЭМУЛЯЦИЯ ФОТОГРАФИИ]',
                'size': 30,
                'permissions': 0o644
            },
            '/Документы': {
                'type': 'dir',
                'children': ['report.doc', 'data.txt']
            },
            '/Документы/report.doc': {
                'type': 'file',
                'content': b'Отчет за март: продажи выросли на 20%\n',
                'size': 45,
                'permissions': 0o644
            },
            '/Документы/data.txt': {
                'type': 'file',
                'content': b'1,2,3,4,5\n6,7,8,9,10\n',
                'size': 20,
                'permissions': 0o644
            }
        }
    
    def _get_node(self, path):
        """Вспомогательный метод: получить информацию о файле/папке"""
        # Нормализуем путь
        if path.endswith('/') and path != '/':
            path = path[:-1]
        
        if path in self.files:
            return self.files[path]
        return None
    
    # ========== ОСНОВНЫЕ МЕТОДЫ FUSE ==========
    
    def getattr(self, path, fh=None):
        """Вызывается при: ls -l, stat, файловый менеджер смотрит свойства"""
        logging.debug(f"getattr({path})")
        
        node = self._get_node(path)
        if node is None:
            raise FuseOSError(2)  # ENOENT - файл не найден
        
        # Формируем атрибуты, как у реального файла
        if node['type'] == 'dir':
            return {
                'st_mode': (0o755 | 0o40000),  # директория
                'st_nlink': 2,
                'st_size': 4096,
                'st_ctime': 1234567890,
                'st_mtime': 1234567890,
                'st_atime': 1234567890,
            }
        else:  # файл
            return {
                'st_mode': (node['permissions'] | 0o100000),  # обычный файл
                'st_nlink': 1,
                'st_size': node['size'],
                'st_ctime': 1234567890,
                'st_mtime': 1234567890,
                'st_atime': 1234567890,
            }
    
    def readdir(self, path, fh):
        """Вызывается когда открывают папку: ls, файловый менеджер"""
        logging.debug(f"readdir({path})")
        
        node = self._get_node(path)
        if node is None or node['type'] != 'dir':
            raise FuseOSError(2)  # ENOENT
        
        # Всегда возвращаем . и .. (текущая и родительская папка)
        entries = ['.', '..']
        
        # Добавляем содержимое папки
        if 'children' in node:
            entries.extend(node['children'])
        
        return entries
    
    def open(self, path, flags):
        """Вызывается перед чтением файла"""
        logging.debug(f"open({path}, flags={flags})")
        
        node = self._get_node(path)
        if node is None or node['type'] != 'file':
            raise FuseOSError(2)  # ENOENT
        
        # Проверяем права (упрощённо)
        if (flags & 0o3) != 0:  # если пытаются писать
            raise FuseOSError(13)  # EACCES - запрещено (у нас read-only)
        
        return 0
    
    def read(self, path, size, offset, fh):
        """Вызывается когда читают файл: cat, cp, открытие в редакторе"""
        logging.debug(f"read({path}, size={size}, offset={offset})")
        
        node = self._get_node(path)
        if node is None or node['type'] != 'file':
            raise FuseOSError(2)  # ENOENT
        
        content = node['content']
        # Возвращаем запрошенный кусок файла
        return content[offset:offset+size]
    
    # ========== ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ ДЛЯ РЕАЛИЗМА ==========
    
    def access(self, path, mode):
        """Проверка прав доступа"""
        logging.debug(f"access({path}, mode={mode})")
        # В прототипе всегда разрешаем
        return 0
    
    def statfs(self, path):
        """Информация о свободном месте (для df)"""
        logging.debug(f"statfs({path})")
        return {
            'f_bsize': 4096,
            'f_blocks': 1000000,
            'f_bavail': 500000,
            'f_files': 10000,
            'f_ffree': 5000,
        }
    
    def release(self, path, fh):
        """Закрытие файла"""
        logging.debug(f"release({path})")
        return 0

def main():
    if len(sys.argv) != 2:
        print(f"Использование: {sys.argv[0]} <точка_монтирования>")
        print(f"Пример: {sys.argv[0]} ~/test_mount")
        sys.exit(1)
    
    mount_point = sys.argv[1]
    
    # Создаём папку для монтирования, если её нет
    os.makedirs(mount_point, exist_ok=True)
    
    print(f"🔧 Монтируем виртуальную файловую систему в {mount_point}")
    print("📁 Содержимое:")
    print("   - hello.txt (приветственный файл)")
    print("   - фото.jpg (эмуляция изображения)")
    print("   - Документы/ (папка с report.doc и data.txt)")
    print("")
    print("🔥 Теперь откройте эту папку в файловом менеджере")
    print("   или выполните: ls -la", mount_point)
    print("")
    print("🛑 Для отмонтирования нажмите Ctrl+C")
    print("-" * 50)
    
    # Запускаем FUSE (в foreground, чтобы можно было остановить Ctrl+C)
    fuse = FUSE(SimpleCloudFS(), mount_point, foreground=True, nothreads=False)
    
    # Эта строка не выполнится, пока FUSE не отмонтируют
    print("✅ Файловая система отмонтирована")

if __name__ == '__main__':
    main()