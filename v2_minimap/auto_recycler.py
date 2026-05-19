# -*- coding: utf-8 -*-
"""
自动回收模块 - 打开背包 → 找"自动回收"按钮 → 点击回收
需要用户提供按钮截图（recycle_button.png）放在脚本同目录
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
# 回收按钮模板图片路径（用户提供截图）
RECYCLE_TEMPLATE = os.path.join(SCRIPT_DIR, 'recycle_button.png')


class AutoRecycler:
    """自动回收器 - 找图点击回收按钮"""

    def __init__(self):
        self.enabled = False
        self.hwnd = None
        self.client_rect = None

        # 背包快捷键（默认F9）
        self.bag_key = 'F9'

        # 找图参数
        self.template_path = RECYCLE_TEMPLATE
        self.match_threshold = 0.8   # 模板匹配阈值
        self.last_recycle_time = 0   # 上次回收时间
        self.recycle_interval = 60   # 回收间隔（秒），避免频繁开背包

        # 按钮模板缓存
        self._template = None
        self._template_w = 0
        self._template_h = 0

    def set_hwnd(self, hwnd: int):
        """设置窗口句柄"""
        self.hwnd = hwnd
        if hwnd:
            self.client_rect = win32gui.GetClientRect(hwnd)

    def load_template(self, template_path: Optional[str] = None) -> bool:
        """
        加载回收按钮的模板图片
        如果文件不存在，会提示用户截图
        返回: True=加载成功
        """
        if template_path:
            self.template_path = template_path

        if not os.path.exists(self.template_path):
            logger.warning(
                f"回收按钮模板不存在: {self.template_path}\n"
                f"请打开背包后截取'自动回收'按钮图片，保存为 recycle_button.png"
            )
            self._template = None
            return False

        try:
            template = cv2.imread(self.template_path)
            if template is None:
                logger.error(f"无法读取模板图片: {self.template_path}")
                return False

            self._template = template
            self._template_h, self._template_w = template.shape[:2]
            logger.info(f"回收按钮模板加载成功: {self.template_w}x{self.template_h}")
            return True
        except Exception as e:
            logger.error(f"加载模板失败: {e}")
            return False

    def _capture_client(self) -> Optional[np.ndarray]:
        """后台截取游戏客户区全屏（BGR格式）"""
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

    def _send_key(self, key_char: str):
        """向窗口发送按键（PostMessage）"""
        if not self.hwnd:
            return
        try:
            if key_char.startswith('F') and key_char[1:].isdigit():
                f_num = int(key_char[1:])
                vk = win32con.VK_F1 + f_num - 1
            elif key_char.isdigit():
                vk = win32con.VK_0 + int(key_char)
            elif len(key_char) == 1 and key_char.isalpha():
                vk = win32api.VkKeyScan(key_char.upper()) & 0xFF
            else:
                key_map = {'Enter': win32con.VK_RETURN, 'Space': win32con.VK_SPACE}
                vk = key_map.get(key_char)
                if not vk:
                    return
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, vk, 0)
            time.sleep(0.05)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, vk, 0)
        except Exception as e:
            logger.debug(f"按键[{key_char}]: {e}")

    def _click_at(self, client_x: int, client_y: int):
        """在客户区坐标点击鼠标（PostMessage）"""
        if not self.hwnd:
            return
        try:
            # 坐标打包为 lParam（LOWORD=x, HIWORD=y）
            lparam = win32api.MAKELONG(client_x, client_y)
            win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
            time.sleep(0.05)
            win32gui.PostMessage(self.hwnd, win32con.WM_LBUTTONUP, 0, lparam)
            time.sleep(0.1)
        except Exception as e:
            logger.debug(f"点击失败: {e}")

    def _find_button(self, screen: np.ndarray) -> Optional[tuple]:
        """
        在游戏画面中找回收按钮
        返回: (client_x, client_y) 按钮中心坐标，没找到返回 None
        """
        if self._template is None:
            logger.debug("模板未加载，跳过找图")
            return None

        try:
            # 模板匹配
            result = cv2.matchTemplate(screen, self._template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val >= self.match_threshold:
                # 计算按钮中心坐标（相对于客户区）
                cx = max_loc[0] + self._template_w // 2
                cy = max_loc[1] + self._template_h // 2
                logger.info(f"找到回收按钮! 坐标=({cx},{cy}) 匹配度={max_val:.2f}")
                return (cx, cy)
            else:
                logger.debug(f"未找到回收按钮（最佳匹配={max_val:.2f} <= {self.match_threshold}）")
                return None
        except Exception as e:
            logger.error(f"找图失败: {e}")
            return None

    def recycle_once(self) -> bool:
        """
        执行一次回收操作
        流程：开背包 → 找按钮 → 点击回收 → 关背包
        返回: True=回收成功 False=失败
        """
        if not self.enabled or not self.hwnd:
            return False

        # 检查回收间隔
        now = time.time()
        if now - self.last_recycle_time < self.recycle_interval:
            return False

        if self._template is None:
            if not self.load_template():
                return False

        logger.info("=== 开始自动回收 ===")

        # 1. 打开背包（F9）
        logger.info("打开背包...")
        self._send_key(self.bag_key)
        time.sleep(0.5)  # 等背包界面出来

        # 2. 截取游戏画面
        screen = self._capture_client()
        if screen is None:
            logger.warning("截图失败，关背包退出")
            self._send_key(self.bag_key)
            return False

        # 3. 找回收按钮
        btn_pos = self._find_button(screen)
        if btn_pos is None:
            logger.warning("未找到回收按钮，关背包退出")
            self._send_key(self.bag_key)
            return False

        # 4. 点击回收按钮
        logger.info(f"点击回收按钮: {btn_pos}")
        self._click_at(btn_pos[0], btn_pos[1])
        time.sleep(0.3)

        # 5. 关背包（再按一次F9）
        self._send_key(self.bag_key)

        self.last_recycle_time = now
        logger.info("=== 回收完成 ===")
        return True

    def try_recycle(self) -> bool:
        """
        智能回收 - 检查间隔后才执行
        适合在挂机循环中每轮调用
        """
        if not self.enabled:
            return False
        if time.time() - self.last_recycle_time < self.recycle_interval:
            return False
        return self.recycle_once()