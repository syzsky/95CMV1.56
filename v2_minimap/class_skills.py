# -*- coding: utf-8 -*-
"""
全职业自动技能模块 - 支持战士/法师/道士
功能：自动循环使用职业技能、自动喝药
"""

import time
import logging
import key_sender
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# 各职业默认技能配置
CLASS_CONFIGS = {
    'warrior': {
        'name': '战士',
        'skills': {
            'blood':     {'key': 'F1', 'interval': 600, 'name': '破血狂杀'},
            'half_moon': {'key': 'F2', 'interval': 5,   'name': '半月弯刀'},
            'fire':      {'key': 'F3', 'interval': 30,  'name': '烈火剑法'},
            'charge':    {'key': 'F4', 'interval': 60,  'name': '野蛮冲撞'},
        },
        'potions': {
            'hp': {'key': '1', 'interval': 3, 'name': '生命药水'},
        }
    },
    'wizard': {
        'name': '法师',
        'skills': {
            'shield':    {'key': 'F1', 'interval': 120, 'name': '魔法盾'},
            'blizzard':  {'key': 'F2', 'interval': 3,   'name': '冰咆哮'},
            'lightning': {'key': 'F3', 'interval': 2,   'name': '雷电术'},
            'teleport':  {'key': 'F4', 'interval': 300, 'name': '瞬息移动'},
        },
        'potions': {
            'hp': {'key': '1', 'interval': 3, 'name': '生命药水'},
            'mp': {'key': '2', 'interval': 3, 'name': '魔法药水'},
        }
    },
    'taoist': {
        'name': '道士',
        'skills': {
            'summon': {'key': '3', 'interval': 300, 'name': '召唤神兽'},
            'heal':   {'key': '4', 'interval': 15,  'name': '治愈术'},
            'buff':   {'key': '5', 'interval': 120, 'name': '幽灵盾'},
        },
        'potions': {
            'hp': {'key': '1', 'interval': 3, 'name': '生命药水'},
        }
    }
}


class ClassSkillManager:
    """全职业自动技能管理器"""

    def __init__(self):
        self.enabled = False
        self.hwnd: Optional[int] = None
        self.current_class = 'taoist'
        self._skills: Dict[str, Any] = {}
        self._potions: Dict[str, Any] = {}
        self._load_class_config('taoist')
        self._last_use: Dict[str, float] = {}

    def _load_class_config(self, class_name: str):
        config = CLASS_CONFIGS.get(class_name, CLASS_CONFIGS['taoist'])
        self._skills = {k: dict(v) for k, v in config['skills'].items()}
        self._potions = {k: dict(v) for k, v in config['potions'].items()}
        for s in list(self._skills.values()) + list(self._potions.values()):
            s['enabled'] = True

    def get_class_names(self) -> list:
        return list(CLASS_CONFIGS.keys())

    def switch_class(self, class_name: str):
        if class_name in CLASS_CONFIGS:
            self.current_class = class_name
            self._load_class_config(class_name)
            self._last_use.clear()
            logger.info(f"切换职业为: {CLASS_CONFIGS[class_name]['name']}")

    def set_hwnd(self, hwnd: int):
        self.hwnd = hwnd

    def update_skill_config(self, skill_dict: dict, name: str, key: str, interval: int, enabled: bool):
        if name in skill_dict:
            skill_dict[name]['key'] = key
            skill_dict[name]['interval'] = max(1, interval)
            skill_dict[name]['enabled'] = enabled

    def update_from_config(self, section, class_name: str = None):
        if class_name:
            self.switch_class(class_name)
        for name in list(self._skills.keys()):
            key = section.get(f'{name}_key', fallback=self._skills[name]['key'])
            interval = section.getint(f'{name}_interval', fallback=self._skills[name]['interval'])
            enabled = section.getboolean(f'{name}_enabled', fallback=True)
            self.update_skill_config(self._skills, name, key, interval, enabled)
        for name in list(self._potions.keys()):
            pk = f'{name}_potion_key'
            pi = f'{name}_potion_interval'
            pe = f'{name}_potion_enabled'
            key = section.get(pk, fallback=self._potions[name]['key'])
            interval = section.getint(pi, fallback=self._potions[name]['interval'])
            enabled = section.getboolean(pe, fallback=True)
            self.update_skill_config(self._potions, name, key, interval, enabled)

    def send_key(self, key_char: str):
        """前台按键（keybd_event 模拟真实按键）"""
        key_sender.send_key(key_char, 0.05)

    def use_item(self, item_dict: dict, now: float) -> bool:
        if not self.enabled or not self.hwnd:
            return False
        if not item_dict.get('enabled', True):
            return False
        key = item_dict.get('key', '')
        interval = item_dict.get('interval', 999)
        item_id = f"{self.current_class}_{item_dict.get('name', '?')}"
        if now - self._last_use.get(item_id, 0) < interval:
            return False
        self.send_key(key)
        self._last_use[item_id] = now
        logger.info(f"[{CLASS_CONFIGS[self.current_class]['name']}] {item_dict['name']} (键{key}/{interval}s)")
        return True

    def tick(self) -> int:
        if not self.enabled or not self.hwnd:
            return 0
        now = time.time()
        used = 0
        # 先喝药
# 先喝药
        for name in ['hp', 'mp']:
            if name in self._potions:
                if self.use_item(self._potions[name], now=now):
                    used += 1
                    time.sleep(0.1)
        # 技能循环
        for skill in self._skills.values():
            if self.use_item(skill, now=now):
                used += 1
                time.sleep(0.1)
        return used

    def reset_timers(self):
        self._last_use.clear()