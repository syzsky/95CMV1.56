# -*- coding: utf-8 -*-
"""
自动寻路下图模块 - 自动走到地图入口下到下一层
支持预设路线和路径点导航
"""

import time
import logging
import win32gui
import win32con
import win32api
import numpy as np
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)


class NavWaypoint:
    def __init__(self, x: int, y: int, action: str = 'walk',
                 action_param: str = '', wait_after: float = 1.0):
        self.x = x
        self.y = y
        self.action = action  # walk/click/key/wait/npc
        self.action_param = action_param
        self.wait_after = wait_after


PRESET_ROUTES = {
    '盟重省->石墓阵': {
        'start_map': '盟重省',
        'waypoints': [
            NavWaypoint(305, 340, 'walk', '', 0.5),
            NavWaypoint(315, 340, 'walk', '', 1.0),
            NavWaypoint(300, 320, 'click', '', 2.0),
        ]
    },
    '盟重省->猪洞': {
        'start_map': '盟重省',
        'waypoints': [
            NavWaypoint(320, 310, 'walk', '', 0.5),
            NavWaypoint(330, 295, 'walk', '', 1.0),
        ]
    },
    '盟重省->蜈蚣洞': {
        'start_map': '盟重省',
        'waypoints': [
            NavWaypoint(280, 340, 'walk', '', 0.5),
            NavWaypoint(270, 355, 'walk', '', 1.0),
        ]
    },
    '比奇省->矿区': {
        'start_map': '比奇省',
        'waypoints': [
            NavWaypoint(400, 250, 'walk', '', 0.5),
            NavWaypoint(410, 240, 'walk', '', 1.0),
        ]
    },
}


class AutoNavigator:
    def __init__(self):
        self.enabled = False
        self.hwnd = None
        self.active_route = None
        self._waypoint_index = 0
        self._is_navigating = False
        self.arrive_distance = 5
        self.nav_timeout = 120
        self._nav_start_time = 0

    def set_hwnd(self, hwnd: int):
        self.hwnd = hwnd

    def send_key(self, key_char: str, duration: float = 0.1):
        if not self.hwnd:
            return
        try:
            vk = win32api.VkKeyScan(key_char) & 0xFF
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, vk, 0)
            time.sleep(duration)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, vk, 0)
        except Exception as e:
            logger.debug(f"按键[{key_char}]: {e}")

    def get_routes_for_map(self, map_name: str) -> list:
        routes = []
        for name, route in PRESET_ROUTES.items():
            if route['start_map'] in map_name or map_name in route['start_map']:
                routes.append(name)
        return routes

    def start_route(self, route_name: str):
        if route_name not in PRESET_ROUTES:
            logger.warning(f"未知路线: {route_name}")
            return
        self.active_route = route_name
        self._waypoint_index = 0
        self._is_navigating = True
        self._nav_start_time = time.time()
        logger.info(f"寻路: {route_name}")

    def stop(self):
        self._is_navigating = False
        self.active_route = None
        self._waypoint_index = 0
        logger.info("停止寻路")

    def update(self, coords=None, full_screen=None) -> str:
        if not self.enabled or not self._is_navigating:
            return 'idle'
        if not self.active_route:
            self._is_navigating = False
            return 'idle'
        if time.time() - self._nav_start_time > self.nav_timeout:
            logger.warning(f"超时: {self.active_route}")
            self.stop()
            return 'failed'

        route = PRESET_ROUTES[self.active_route]
        wps = route['waypoints']
        if self._waypoint_index >= len(wps):
            self._is_navigating = False
            logger.info(f"到达: {self.active_route}")
            return 'arrived'

        wp = wps[self._waypoint_index]
        if coords:
            dx = wp.x - coords[0]
            dy = wp.y - coords[1]
            dist = abs(dx) + abs(dy)
            if dist <= self.arrive_distance:
                self._do_action(wp)
                self._waypoint_index += 1
                time.sleep(wp.wait_after)
            else:
                self._move(dx, dy)
        else:
            self._do_action(wp)
            self._waypoint_index += 1
            time.sleep(wp.wait_after)
        return 'navigating'

    def _move(self, dx: int, dy: int):
        if abs(dx) > abs(dy):
            if dx > 0:
                self.send_key('D', 0.3)
            else:
                self.send_key('A', 0.3)
        else:
            if dy > 0:
                self.send_key('S', 0.3)
            else:
                self.send_key('W', 0.3)

    def _do_action(self, wp: NavWaypoint):
        if wp.action == 'click':
            self.send_key('Enter', 0.1)
            logger.info("点击入口")
        elif wp.action == 'key':
            self.send_key(wp.action_param, 0.2)
            logger.info(f"按键: {wp.action_param}")
        elif wp.action == 'npc':
            for k in ['Space', 'Enter', 'Space']:
                self.send_key(k, 0.1)
                time.sleep(0.5)
            logger.info("NPC对话")
        elif wp.action == 'wait':
            t = float(wp.action_param or 2)
            time.sleep(t)

    def auto_detect(self, map_name: str):
        if not self.enabled:
            return
        routes = self.get_routes_for_map(map_name)
        if routes and not self._is_navigating:
            logger.info(f"在{map_name}，可用路线: {routes}")
            self.start_route(routes[0])