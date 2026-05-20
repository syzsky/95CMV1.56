# -*- coding: utf-8 -*-
"""
统一按键/鼠标工具类
使用 keybd_event + mouse_event 模拟真实物理按键
（PostMessage 对很多私服无效，因为私服不处理消息队列）
"""
import time
import logging
import ctypes
import win32con
import win32api
from typing import Optional

logger = logging.getLogger(__name__)

user32 = ctypes.windll.user32

# 虚拟键码映射（处理特殊键）
SPECIAL_KEYS = {
    'Enter': win32con.VK_RETURN,
    'Space': win32con.VK_SPACE,
    'Esc': win32con.VK_ESCAPE,
    'Tab': win32con.VK_TAB,
    'Back': win32con.VK_BACK,
    'Shift': win32con.VK_SHIFT,
    'Ctrl': win32con.VK_CONTROL,
    'Alt': win32con.VK_MENU,
    'Up': win32con.VK_UP,
    'Down': win32con.VK_DOWN,
    'Left': win32con.VK_LEFT,
    'Right': win32con.VK_RIGHT,
    'F1': win32con.VK_F1,
    'F2': win32con.VK_F2,
    'F3': win32con.VK_F3,
    'F4': win32con.VK_F4,
    'F5': win32con.VK_F5,
    'F6': win32con.VK_F6,
    'F7': win32con.VK_F7,
    'F8': win32con.VK_F8,
    'F9': win32con.VK_F9,
    'F10': win32con.VK_F10,
    'F11': win32con.VK_F11,
    'F12': win32con.VK_F12,
}


def _get_vk(key_char: str) -> Optional[int]:
    """将按键字符串转换为虚拟键码"""
    if not key_char:
        return None

    # 特殊键 F1-F12
    if key_char.upper() in SPECIAL_KEYS:
        return SPECIAL_KEYS[key_char.upper()]

    # F键（兼容 'F1' 格式）
    if key_char.upper().startswith('F') and key_char[1:].isdigit():
        f_num = int(key_char[1:])
        if 1 <= f_num <= 24:
            return win32con.VK_F1 + f_num - 1

    # 数字键
    if key_char.isdigit():
        return ord(key_char)

    # 字母键
    if len(key_char) == 1 and key_char.isalpha():
        return win32api.VkKeyScan(key_char.upper()) & 0xFF

    # 其他特殊键名
    key_map = {
        'ENTER': win32con.VK_RETURN,
        'SPACE': win32con.VK_SPACE,
        'ESC': win32con.VK_ESCAPE,
        'TAB': win32con.VK_TAB,
        'BACK': win32con.VK_BACK,
    }
    return key_map.get(key_char.upper())


def send_key(key_char: str, duration: float = 0.05):
    """
    发送按键模拟（keybd_event）
    要求游戏窗口在前台（被激活）
    key_char: 按键字符或名称，如 'A', '1', 'F1', 'Enter', 'Space'
    duration: 按键按下持续时间（秒）
    """
    vk = _get_vk(key_char)
    if vk is None:
        logger.debug(f"未知按键: {key_char}")
        return

    try:
        user32.keybd_event(vk, 0, 0, 0)        # keydown
        time.sleep(duration)
        user32.keybd_event(vk, 0, 2, 0)        # keyup (2 = KEYEVENTF_KEYUP)
    except Exception as e:
        logger.debug(f"按键[{key_char}]失败: {e}")


def send_key_enter(duration: float = 0.05):
    """按回车"""
    send_key('Enter', duration)


def click_at(hwnd: int, client_x: int, client_y: int):
    """
    在游戏窗口的客户区坐标点击鼠标
    使用 SetCursorPos + mouse_event 实现真实物理点击
    hwnd: 窗口句柄
    client_x, client_y: 客户区相对坐标
    """
    if not hwnd:
        return

    try:
        # 客户区坐标转屏幕坐标
        screen_pos = win32api.ClientToScreen(hwnd, (client_x, client_y))

        # 移动鼠标到目标位置
        user32.SetCursorPos(screen_pos[0], screen_pos[1])
        time.sleep(0.05)

        # 鼠标左键按下
        user32.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.05)

        # 鼠标左键释放
        user32.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.1)

        logger.debug(f"点击: ({client_x}, {client_y}) -> 屏幕({screen_pos[0]}, {screen_pos[1]})")
    except Exception as e:
        logger.debug(f"点击失败 ({client_x},{client_y}): {e}")


def client_to_screen(hwnd: int, client_x: int, client_y: int) -> tuple:
    """客户区坐标转屏幕坐标"""
    try:
        return win32api.ClientToScreen(hwnd, (client_x, client_y))
    except:
        return (0, 0)