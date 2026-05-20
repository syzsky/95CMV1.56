# -*- coding: utf-8 -*-
"""
统一截图工具类
使用 PIL.ImageGrab 前台截图（兼容 DirectX 游戏）
很多私服用 DirectX 渲染，BitBlt 后台截图会返回黑屏
"""
import time
import logging
import win32gui
import numpy as np
import cv2
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# 屏幕外的隐藏位置
HIDE_X = -10000
HIDE_Y = -10000


def _move_window_out(hwnd: int):
    """把窗口临时移到屏幕外（不截图它）"""
    if hwnd:
        try:
            win32gui.SetWindowPos(hwnd, 0, HIDE_X, HIDE_Y, 0, 0,
                                  0x0001 | 0x0002 | 0x0010)  # SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
        except:
            pass


def _move_window_back(hwnd: int):
    """把窗口移回屏幕（恢复）"""
    if hwnd:
        try:
            win32gui.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                                  0x0001 | 0x0002 | 0x0004 | 0x0010)  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE
        except:
            pass


def capture_client(hwnd: int, hide_hwnd: Optional[int] = None) -> Optional[np.ndarray]:
    """
    截取游戏窗口的客户区画面（BGR 格式，OpenCV 兼容）
    使用 PIL.ImageGrab 前台截图，兼容 DirectX 游戏
    hwnd: 窗口句柄
    hide_hwnd: 可选，截图前临时移开的窗口（如 GUI 主窗口），截完移回
    返回: BGR numpy 数组，失败返回 None
    """
    if not hwnd:
        return None

    # 先把要隐藏的窗口移开
    _move_window_out(hide_hwnd)
    time.sleep(0.05)

    try:
        from PIL import ImageGrab

        # 获取客户区在屏幕上的位置
        client_left, client_top = win32gui.ClientToScreen(hwnd, (0, 0))
        client_rect = win32gui.GetClientRect(hwnd)
        client_width = client_rect[2] - client_rect[0]
        client_height = client_rect[3] - client_rect[1]

        if client_width <= 0 or client_height <= 0:
            logger.debug("窗口尺寸无效")
            return None

        # 前台截图（兼容 DirectX）
        screenshot = ImageGrab.grab(bbox=(
            client_left, client_top,
            client_left + client_width,
            client_top + client_height
        ))

        # 转换为 OpenCV 格式
        img = np.array(screenshot)
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        return img

    except Exception as e:
        logger.debug(f"前台截图失败: {e}")
        return None

    finally:
        # 无论成功失败，都把隐藏的窗口移回来
        _move_window_back(hide_hwnd)


def capture_client_region(hwnd: int, x: int, y: int, w: int, h: int,
                          hide_hwnd: Optional[int] = None) -> Optional[np.ndarray]:
    """
    截取客户区指定区域
    x, y: 客户区相对坐标
    w, h: 区域宽高
    hide_hwnd: 可选，截图前临时移开的窗口
    """
    full = capture_client(hwnd, hide_hwnd=hide_hwnd)
    if full is None:
        return None

    img_h, img_w = full.shape[:2]
    x1 = max(0, min(x, img_w - 1))
    y1 = max(0, min(y, img_h - 1))
    x2 = min(x + w, img_w)
    y2 = min(y + h, img_h)

    if x2 <= x1 or y2 <= y1:
        return None

    return full[y1:y2, x1:x2]


def get_client_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """获取客户区尺寸 (left, top, right, bottom) 相对值"""
    if not hwnd:
        return None
    try:
        return win32gui.GetClientRect(hwnd)
    except:
        return None