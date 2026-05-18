# -*- coding: utf-8 -*-
"""
道士自动技能模块 - 自动循环使用道士技能
功能：
1. 自动召唤神兽/骷髅（长冷却）
2. 自动治愈术（短冷却）
3. 自动施放状态技能（幽灵盾/神圣战甲术等 中冷却）
"""

import time
import logging
import win32gui
import win32con
import win32api
from typing import Optional

logger = logging.getLogger(__name__)


class TaoistSkillManager:
    """道士技能自动管理器"""

    def __init__(self):
        # 是否启用
        self.enabled = False

        # 窗口句柄（用于PostMessage）
        self.hwnd: Optional[int] = None

        # 各技能配置
        self.skills = {
            'summon': {
                'key': '3',           # 召唤快捷键
                'interval': 300,      # 召唤间隔（秒） 5分钟
                'last_use': 0,
                'name': '召唤神兽/骷髅',
                'enabled': True,
            },
            'heal': {
                'key': '4',           # 治愈术快捷键
                'interval': 15,       # 治愈间隔（秒）
                'last_use': 0,
                'name': '治愈术',
                'enabled': True,
            },
            'buff': {
                'key': '5',           # 状态技能快捷键
                'interval': 120,      # 状态技能间隔（秒） 2分钟
                'last_use': 0,
                'name': '幽灵盾/神圣战甲术',
                'enabled': True,
            },
        }
        # 启动延迟（秒）- 给游戏加载时间
        self.initial_delay = 5

    def set_hwnd(self, hwnd: int):
        """设置游戏窗口句柄"""
        self.hwnd = hwnd

    def update_config(self, skill_name: str, key: str, interval: int, enabled: bool):
        """更新单个技能配置"""
        if skill_name in self.skills:
            self.skills[skill_name]['key'] = key
            self.skills[skill_name]['interval'] = interval
            self.skills[skill_name]['enabled'] = enabled

    def update_from_config(self, config_section):
        """从配置解析器更新所有技能设置"""
        if config_section:
            for skill_name in ['summon', 'heal', 'buff']:
                key = config_section.get(f'{skill_name}_key', fallback=self.skills[skill_name]['key'])
                interval = config_section.getint(f'{skill_name}_interval', fallback=self.skills[skill_name]['interval'])
                enabled = config_section.getboolean(f'{skill_name}_enabled', fallback=self.skills[skill_name]['enabled'])
                self.update_config(skill_name, key, interval, enabled)

    def send_key(self, key_char: str):
        """使用PostMessage向游戏窗口发送按键"""
        if not self.hwnd:
            return

        try:
            vk_code = win32api.VkKeyScan(key_char)
            vk_code = vk_code & 0xFF

            win32gui.PostMessage(self.hwnd, win32con.WM_KEYDOWN, vk_code, 0)
            time.sleep(0.05)
            win32gui.PostMessage(self.hwnd, win32con.WM_KEYUP, vk_code, 0)
        except Exception as e:
            logger.error(f"道士技能按键失败 [{key_char}]: {e}")

    def use_skill(self, skill_name: str, now: float) -> bool:
        """执行单个技能

        Args:
            skill_name: 技能名称 summon/heal/buff
            now: 当前时间戳

        Returns:
            True=使用了技能
        """
        if not self.enabled or not self.hwnd:
            return False

        skill = self.skills.get(skill_name)
        if not skill or not skill['enabled']:
            return False

        if now - skill['last_use'] < skill['interval']:
            return False

        # 执行按键
        self.send_key(skill['key'])
        skill['last_use'] = now
        logger.info(f"道士技能: [{skill['name']}] 按键={skill['key']}, 冷却={skill['interval']}秒")
        return True

    def tick(self) -> int:
        """主循环调用 - 执行一次技能检查

        Returns:
            当前使用了多少个技能
        """
        if not self.enabled or not self.hwnd:
            return 0

        now = time.time()
        used_count = 0

        # 按优先级：治愈(最频繁) > 状态 > 召唤
        if self.use_skill('heal', now):
            used_count += 1

        if self.use_skill('buff', now):
            used_count += 1
            # 状态技能后稍微等待
            time.sleep(0.1)

        if self.use_skill('summon', now):
            used_count += 1

        return used_count

    def reset_timers(self):
        """重置所有技能计时器"""
        now = time.time()
        for skill in self.skills.values():
            skill['last_use'] = now