# -*- coding: utf-8 -*-
"""
自动补给模块
检测快捷栏第1格是否有药（红药）
没药了就去杂货铺买药+修装备
"""

import time
import logging
import os
import win32gui
import win32con
import win32api
import win32ui
import numpy as np
import cv2
from typing import Optional

logger = logging.getLogger(__name__)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class SupplyManager:
    """自动补给管理器"""

    TEMPLATES = {
        'buy': 'shop_buy.png',
        'repair': 'shop_repair.png',
        'buy_all': 'shop_buy_all.png',
        'repair_all': 'shop_repair_all.png',
        'close': 'shop_close.png',
    }

    def __init__(self):
        self.enabled = False
        self.hwnd = None
        self.client_rect = None

        # 快捷栏第1格区域（相对于客户区）
        # 快捷栏在屏幕底部中间，每格约45x45像素
        # 不同分辨率需要调整，可以先截图告诉我位置
        self.slot1_x = 770
        self.slot1_y = 980
        self.slot1_w = 40
        self.slot1_h = 40

        # 判断标准：格子平均亮度低于此值就算空
        self.slot_empty_threshold = 30

        # 对话框行号
        self.buy_row = 1
        self.repair_row = 2

        # 补给间隔（防止反复回城）
        self.supply_interval = 120  # 回城后至少等2分钟再去

        self.last_supply_time = 0
        self._templates = {}
        self.bag_key = 'F9'

    def set_hwnd(self, hwnd: int):
        self.hwnd = hwnd
        if hwnd:
            self.client_rect = win32gui.GetClientRect(hwnd)

    def load_templates(self) -> bool:
        all_ok = True
        for name, filename in self.TEMPLATES.items():
            path = os.path.join(SCRIPT_DIR, filename)
            if os.path.exists(path):
                template = cv2.imread(path)
                if template is not None:
                    self._templates[name] = template
                    logger.info(f"模板加载: {filename}")
                else:
                    all_ok = False
            else:
                all_ok = False
        return all_ok

    def _capture_client(self) -> Optional[np.ndarray]:
        if not self.hwnd or not self.client_rect:
            return None
        try:
            cw = self.client_rect[2] - self.client_rect[0]
            ch = self.client_rect[3] - self.client_rect[1]
            hwndDC = win32gui.GetWindowDC(self.hwnd)
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            saveDC = mfcDC.CreateCompatibleDC()
            saveBitMap = win32ui.CreateBitmap()
            saveBitMap.CreateCompatibleBitmap(mfcDC, cw, ch)
            saveDC.SelectObject(saveBitMap)
            saveDC.BitBlt((0, 0), (cw, ch), mfcDC, (0, 0), win32con.SRCCOPY)
            bmpinfo = saveBitMap.GetInfo()
            bmpstr = saveBitMap.GetBitmapBits(True)
            img = np.frombuffer(bmpstr, dtype='uint8')
            img.shape = (bmpinfo['bmHeight'], bmpinfo['bmWidth'], 4)
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            win32gui.DeleteObject(saveBitMap.GetHandle())
            saveDC.DeleteDC()
            mfcDC.DeleteDC()
            win32gui.ReleaseDC(self.hwnd, hwndDC)
            return img
        except Exception as e:
            logger.debug(f"截图失败: {e}")
            return None

    def _find_template(self, screen: np.ndarray, name: str, threshold: float = 0.8):
        template = self._templates.get(name)
        if template is None:
            return None
        try:
            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val >= threshold:
                cx = max_loc[0] + template.shape[1] // 2
                cy = max_loc[1] + template.shape[0] // 2
                return (cx, cy)
            return None
        except:
            return None

    def _send_key(self, key_char: str):
        if not self.hwnd:
            return
        try:
            if key_char.startswith('F') and key_char[1:].isdigit():
                f_num = int(key_char[1:])
                vk = win32con.VK_F1 + f_num - 1
            elif key_char.isdigit():
                vk = ord(key_char)
            elif key_char.upper() == 'ENTER':
                vk = win32con.VK_RETURN
            elif key_char.upper() == 'SPACE':
                vk = win32con.VK_SPACE
            elif key_char.upper() == 'ESC':
                vk = win32con.VK_ESCAPE
            elif len(key_char) == 1 and key_char.isalpha():
                vk = win32api.VkKeyScan(key_char.upper()) & 0xFF
            else:
                return
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, vk, 0)
            time.sleep(0.05)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, vk, 0)
        except:
            pass

    def _click_at(self, client_x: int, client_y: int):
        if not self.hwnd:
            return
        try:
            lparam = win32api.MAKELONG(client_x, client_y)
            win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
            time.sleep(0.05)
            win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONUP, 0, lparam)
            time.sleep(0.3)
        except:
            pass

    def _click_dialog_row(self, row: int):
        """点击对话框某一行（默认坐标）"""
        first_row_y = 240
        row_height = 30
        click_x = 400
        cy = first_row_y + (row - 1) * row_height
        self._click_at(click_x, cy)

    def _wait_and_find(self, name: str, timeout: float = 3.0):
        start = time.time()
        while time.time() - start < timeout:
            screen = self._capture_client()
            if screen is not None:
                pos = self._find_template(screen, name)
                if pos:
                    return pos
            time.sleep(0.3)
        return None

    # ====== 新增：检测快捷栏第1格是否有药 ======

    def check_potion_slot(self) -> bool:
        """
        检查快捷栏第1格是否有药
        截图指定区域 → 算平均亮度 → 暗=没药
        返回: True=有药 / False=没药
        """
        if not self.hwnd:
            return True  # 没连上就当有药，避免误回城

        screen = self._capture_client()
        if screen is None:
            return True

        h, w = screen.shape[:2]

        # 检查坐标是否在画面范围内
        x1 = min(self.slot1_x, w - 10)
        y1 = min(self.slot1_y, h - 10)
        x2 = min(x1 + self.slot1_w, w)
        y2 = min(y1 + self.slot1_h, h)

        if x2 <= x1 or y2 <= y1:
            logger.warning(f"快捷栏区域超出画面 ({w}x{h})，请调整 slot1 坐标")
            return True

        # 截取格子区域
        slot = screen[y1:y2, x1:x2]

        # 算平均亮度（BGR转灰度）
        gray = cv2.cvtColor(slot, cv2.COLOR_BGR2GRAY)
        avg_brightness = float(np.mean(gray))

        has_potion = avg_brightness > self.slot_empty_threshold
        logger.debug(f"快捷栏第1格 亮度={avg_brightness:.1f} {'有药' if has_potion else '空了'}")
        return has_potion

    # ====== 购买和修理（保持不变） ======

    def buy_potions(self) -> bool:
        if not self.hwnd:
            return False
        logger.info("=== 开始购买药品 ===")

        self._send_key('Enter')
        time.sleep(1.0)

        if 'buy' in self._templates:
            btn = self._wait_and_find('buy', 2.0)
            if btn:
                self._click_at(btn[0], btn[1])
            else:
                self._click_dialog_row(self.buy_row)
        else:
            self._click_dialog_row(self.buy_row)
        time.sleep(1.0)

        if 'buy_all' in self._templates:
            btn = self._wait_and_find('buy_all', 2.0)
            if btn:
                self._click_at(btn[0], btn[1])
                time.sleep(0.5)

        if 'close' in self._templates:
            btn = self._find_template(self._capture_client(), 'close')
            if btn:
                self._click_at(btn[0], btn[1])
                time.sleep(0.5)

        self._send_key('Esc')
        time.sleep(0.3)
        logger.info("=== 购买完成 ===")
        return True

    def repair_equipment(self) -> bool:
        if not self.hwnd:
            return False
        logger.info("=== 开始修理装备 ===")

        self._send_key('Enter')
        time.sleep(1.0)

        if 'repair' in self._templates:
            btn = self._wait_and_find('repair', 2.0)
            if btn:
                self._click_at(btn[0], btn[1])
            else:
                self._click_dialog_row(self.repair_row)
        else:
            self._click_dialog_row(self.repair_row)
        time.sleep(1.0)

        if 'repair_all' in self._templates:
            btn = self._wait_and_find('repair_all', 2.0)
            if btn:
                self._click_at(btn[0], btn[1])
                time.sleep(0.5)

        if 'close' in self._templates:
            btn = self._find_template(self._capture_client(), 'close')
            if btn:
                self._click_at(btn[0], btn[1])
                time.sleep(0.5)

        self._send_key('Esc')
        time.sleep(0.3)
        logger.info("=== 修理完成 ===")
        return True

    def do_supply(self) -> bool:
        """
        主入口：先检查快捷栏第1格 → 有药就不去 → 没药才去买
        """
        if not self.enabled:
            return False

        # 先检查快捷栏第1格有没有药
        if self.check_potion_slot():
            return False  # 还有药，不用回城

        # 没药了，检查是否刚补给过（避免反复回城）
        now = time.time()
        if now - self.last_supply_time < self.supply_interval:
            logger.info("刚补给过不久，等冷却")
            return False

        logger.info("========== 快捷栏没药了，回城补给 ==========")

        # TODO: 走到杂货铺NPC
        time.sleep(0.5)

        self.buy_potions()
        time.sleep(0.5)
        self.repair_equipment()

        self.last_supply_time = now
        logger.info("========== 补给完成 ==========")
        return True