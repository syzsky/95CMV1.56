# -*- coding: utf-8 -*-
"""
自动补给模块 - 回城后找杂货铺NPC → 买药 → 修装备
所有操作通过找图识别按钮，鼠标点击执行
需要用户提供按钮截图放在脚本同目录
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

    # 需要的按钮模板文件名
    TEMPLATES = {
        'buy': 'shop_buy.png',           # "购买" 对话框选项
        'repair': 'shop_repair.png',      # "修理" 对话框选项
        'buy_all': 'shop_buy_all.png',    # "全部购买" 按钮
        'repair_all': 'shop_repair_all.png', # "全部修理" 按钮
        'close': 'shop_close.png',        # 关闭按钮
    }

    def __init__(self):
        self.enabled = False
        self.hwnd = None
        self.client_rect = None

        # 杂货铺NPC坐标（盟重省）
        self.npc_x = 330
        self.npc_y = 330

        # 对话行号
        self.buy_row = 1      # "购买"是第几行
        self.repair_row = 2   # "修理"是第几行

        # 补给间隔（秒）
        self.supply_interval = 300  # 默认5分钟

        self.last_supply_time = 0
        self._templates = {}

        # 背包快捷键
        self.bag_key = 'F9'

    def set_hwnd(self, hwnd: int):
        self.hwnd = hwnd
        if hwnd:
            self.client_rect = win32gui.GetClientRect(hwnd)

    def load_templates(self) -> bool:
        """加载所有按钮模板"""
        all_ok = True
        for name, filename in self.TEMPLATES.items():
            path = os.path.join(SCRIPT_DIR, filename)
            if os.path.exists(path):
                template = cv2.imread(path)
                if template is not None:
                    self._templates[name] = template
                    logger.info(f"模板加载成功: {filename} ({template.shape[1]}x{template.shape[0]})")
                else:
                    logger.warning(f"模板读取失败: {filename}")
                    all_ok = False
            else:
                logger.warning(f"模板不存在: {filename}（请截图后保存到此路径）")
                all_ok = False
        return all_ok

    def _capture_client(self) -> Optional[np.ndarray]:
        """截取游戏客户区全屏"""
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

    def _find_template(self, screen: np.ndarray, name: str, threshold: float = 0.8) -> Optional[tuple]:
        """在画面中找指定模板，返回中心坐标"""
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
        except Exception as e:
            logger.debug(f"找图[{name}]失败: {e}")
            return None

    def _send_key(self, key_char: str):
        """发送按键"""
        if not self.hwnd:
            return
        try:
            if key_char.startswith('F') and key_char[1:].isdigit():
                f_num = int(key_char[1:])
                vk = win32con.VK_F1 + f_num - 1
            elif key_char.isdigit():
                vk = win32con.VK_0 + int(key_char)
            elif key_char.upper() == 'ENTER':
                vk = win32con.VK_RETURN
            elif key_char.upper() == 'SPACE':
                vk = win32con.VK_SPACE
            elif len(key_char) == 1 and key_char.isalpha():
                vk = win32api.VkKeyScan(key_char.upper()) & 0xFF
            else:
                return
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, vk, 0)
            time.sleep(0.05)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, vk, 0)
        except Exception as e:
            logger.debug(f"按键[{key_char}]: {e}")

    def _click_at(self, client_x: int, client_y: int):
        """在客户区坐标点击鼠标"""
        if not self.hwnd:
            return
        try:
            lparam = win32api.MAKELONG(client_x, client_y)
            win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
            time.sleep(0.05)
            win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONUP, 0, lparam)
            time.sleep(0.3)
        except Exception as e:
            logger.debug(f"点击失败: {e}")

    def _click_dialog_row(self, row: int):
        """点击对话框某一行"""
        # 对话框第一行大概Y坐标，每行高度
        first_row_y = 240
        row_height = 30
        click_x = 400

        cy = first_row_y + (row - 1) * row_height
        logger.info(f"点击对话框第{row}行: ({click_x}, {cy})")
        self._click_at(click_x, cy)

    def _wait_and_find(self, template_name: str, timeout: float = 3.0) -> Optional[tuple]:
        """等待模板出现并找到它"""
        start = time.time()
        while time.time() - start < timeout:
            screen = self._capture_client()
            if screen is not None:
                pos = self._find_template(screen, template_name)
                if pos:
                    return pos
            time.sleep(0.3)
        return None

    def buy_potions(self) -> bool:
        """
        执行购买药品
        流程：找NPC→Enter→点"购买"行→点"全部购买"→关闭
        """
        if not self.hwnd:
            return False

        logger.info("=== 开始购买药品 ===")

        # 1. 找杂货铺NPC（通过坐标走过去，按Enter对话）
        # TODO: 颜色检测找NPC黄色名字走过去
        self._send_key('Enter')
        time.sleep(1.0)

        # 2. 点"购买"行
        if 'buy' in self._templates:
            btn = self._wait_and_find('buy', 2.0)
            if btn:
                logger.info(f"找到购买按钮: {btn}")
                self._click_at(btn[0], btn[1])
            else:
                logger.info("未找到购买模板，用行号点击")
                self._click_dialog_row(self.buy_row)
        else:
            self._click_dialog_row(self.buy_row)
        time.sleep(1.0)

        # 3. 点"全部购买"
        if 'buy_all' in self._templates:
            btn = self._wait_and_find('buy_all', 2.0)
            if btn:
                logger.info(f"找到全部购买: {btn}")
                self._click_at(btn[0], btn[1])
                time.sleep(0.5)

        # 4. 关闭商店
        if 'close' in self._templates:
            btn = self._find_template(self._capture_client(), 'close')
            if btn:
                self._click_at(btn[0], btn[1])
                time.sleep(0.5)

        # 5. 按 Esc 确保关掉（万一没关掉）
        self._send_key('Esc')
        time.sleep(0.3)

        logger.info("=== 购买完成 ===")
        return True

    def repair_equipment(self) -> bool:
        """
        执行修理装备
        流程：找NPC→Enter→点"修理"行→点"全部修理"→关闭
        """
        if not self.hwnd:
            return False

        logger.info("=== 开始修理装备 ===")

        # 1. 对话
        self._send_key('Enter')
        time.sleep(1.0)

        # 2. 点"修理"行
        if 'repair' in self._templates:
            btn = self._wait_and_find('repair', 2.0)
            if btn:
                logger.info(f"找到修理按钮: {btn}")
                self._click_at(btn[0], btn[1])
            else:
                self._click_dialog_row(self.repair_row)
        else:
            self._click_dialog_row(self.repair_row)
        time.sleep(1.0)

        # 3. 点"全部修理"
        if 'repair_all' in self._templates:
            btn = self._wait_and_find('repair_all', 2.0)
            if btn:
                logger.info(f"找到全部修理: {btn}")
                self._click_at(btn[0], btn[1])
                time.sleep(0.5)

        # 4. 关闭
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
        执行一次完整补给
        买药 → 修理 → 返回
        """
        now = time.time()
        if now - self.last_supply_time < self.supply_interval:
            return False

        logger.info("========== 开始回城补给 ==========")

        # 走到杂货铺NPC位置（通过坐标走向NPC）
        # TODO: 导航到NPC坐标
        time.sleep(0.5)

        self.buy_potions()
        time.sleep(0.5)
        self.repair_equipment()

        self.last_supply_time = now
        logger.info("========== 补给完成 ==========")
        return True