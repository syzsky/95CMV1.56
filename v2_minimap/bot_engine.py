# -*- coding: utf-8 -*-
"""
智能挂机状态机引擎
自动判断当前状态并执行对应操作
"""

import time
import logging
import random
from enum import Enum, auto

logger = logging.getLogger(__name__)


class BotState(Enum):
    """挂机状态"""
    IDLE = auto()
    TELEPORT = auto()       # 找NPC飞图
    HUNT = auto()           # 找红点打怪
    ATTACK = auto()         # 攻击怪物
    FLEE = auto()           # 检测到玩家，逃跑
    PATROL = auto()         # 没怪了，走一走找怪
    FLEE_BACK = auto()      # 逃跑后等几秒返回
    COMPLETED = auto()      # 完成


class SmartEngine:
    """
    智能挂机引擎 - 状态机驱动
    自动切换：传送 → 打怪 → 找怪 → 逃跑 → 继续打
    """

    def __init__(self, bot):
        """
        bot: Mir2AutoBotV2 实例（包含 minimap_detector, npc_teleporter, monster_hunter 等）
        """
        self.bot = bot
        self.state = BotState.IDLE
        self.last_change_time = 0
        self._patrol_start = 0

        # 各状态启动时间
        self._state_times = {}
        self._last_check_time = 0

        # 状态切换冷却（防止太快切换）
        self.min_state_time = 2.0

    def change_state(self, new_state: BotState):
        """切换状态"""
        if new_state == self.state:
            return
        old = self.state
        self.state = new_state
        self.last_change_time = time.time()
        self._state_times[new_state] = time.time()
        logger.info(f"[引擎] {old.name} → {new_state.name}")

    def update(self):
        """
        主更新循环，每秒调用一次
        根据状态执行对应操作
        """
        if not self.bot.running:
            return

        now = time.time()

        # 截图小地图（所有状态都需要）
        minimap = self.bot.capture_minimap()
        if minimap is None:
            time.sleep(0.3)
            return

        self.bot.stats['detection_runs'] += 1

        # 检测红点（怪物）和黄点（玩家）
        red_dots = self.bot.minimap_detector.detect_red_dots(minimap)
        yellow_dots = self.bot.minimap_detector.detect(minimap)

        has_monsters = len(red_dots) > 0
        has_players = len(yellow_dots) > 0

        mm_w = self.bot.minimap_region[2]
        mm_h = self.bot.minimap_region[3]
        center_x = mm_w // 2
        center_y = mm_h // 2

        # ====== 状态机调度 ======
        if self.state == BotState.IDLE:
            self._handle_idle()

        elif self.state == BotState.TELEPORT:
            self._handle_teleport()

        elif self.state == BotState.HUNT:
            self._handle_hunt(red_dots, yellow_dots, center_x, center_y, has_monsters, has_players)

        elif self.state == BotState.ATTACK:
            self._handle_attack(red_dots, yellow_dots, center_x, center_y, has_monsters, has_players)

        elif self.state == BotState.FLEE:
            self._handle_flee(has_players)

        elif self.state == BotState.PATROL:
            self._handle_patrol(red_dots, center_x, center_y, has_monsters)

        elif self.state == BotState.FLEE_BACK:
            self._handle_flee_back()

        # 统计更新
        self.bot.update_stats()

        # 检测间隔
        interval = self.bot.config.getfloat('Detection', 'detection_interval', fallback=0.3)
        time.sleep(interval)

    # ====== 各状态处理方法 ======

    def _handle_idle(self):
        """初始状态 - 决定要做什么"""
        npc_enabled = self.bot.npc_teleporter.enabled
        hunt_enabled = self.bot.monster_hunter.enabled

        if npc_enabled:
            logger.info("[引擎] 开始NPC传送流程")
            target = self.bot.config.get('NpcTeleport', 'target_dungeon', fallback='石墓阵')
            self.bot.npc_teleporter.start_teleport(target, callback=self._on_teleport_done)
            self.change_state(BotState.TELEPORT)
        elif hunt_enabled:
            logger.info("[引擎] 直接开始打怪")
            self.bot.monster_hunter.start_hunting()
            self.change_state(BotState.PATROL)
        else:
            self.change_state(BotState.COMPLETED)

    def _on_teleport_done(self):
        """传送完成回调"""
        logger.info("[引擎] 传送完成，开始打怪")
        if self.bot.monster_hunter.enabled:
            self.bot.monster_hunter.start_hunting()
            self.change_state(BotState.PATROL)
        else:
            self.change_state(BotState.COMPLETED)

    def _handle_teleport(self):
        """传送中 - 等待NPC传送器完成"""
        status = self.bot.npc_teleporter.update()
        if status == 'arrived':
            # 传送完成，上面callback处理
            pass
        elif status == 'failed':
            logger.warning("[引擎] 传送失败，重新尝试")
            target = self.bot.config.get('NpcTeleport', 'target_dungeon', fallback='石墓阵')
            self.bot.npc_teleporter.start_teleport(target, self._on_teleport_done)

    def _handle_hunt(self, red_dots, yellow_dots, cx, cy, has_monsters, has_players):
        """
        打怪状态 - 检测到红点，走过去打
        """
        # 有玩家→逃跑
        if has_players and self.bot.config.getboolean('Teleport', 'enabled', fallback=True):
            logger.info("[引擎] 检测到玩家！切换逃跑")
            self.change_state(BotState.FLEE)
            return

        # 有怪物→攻击
        if has_monsters:
            result = self.bot.monster_hunter.hunt(red_dots, cx, cy)
            if result == 'attacking':
                self.change_state(BotState.ATTACK)
            # 'walking' 保持 HUNT
        else:
            # 没怪了→巡逻找怪
            logger.info("[引擎] 没有怪物了，开始巡逻")
            self._patrol_start = time.time()
            self.change_state(BotState.PATROL)

    def _handle_attack(self, red_dots, yellow_dots, cx, cy, has_monsters, has_players):
        """
        攻击状态 - 持续攻击当前目标
        每轮技能打完后自动切回 HUNT 重新检测
        """
        # 有玩家→逃跑
        if has_players and self.bot.config.getboolean('Teleport', 'enabled', fallback=True):
            logger.info("[引擎] 攻击中检测到玩家！逃跑")
            self.change_state(BotState.FLEE)
            return

        # 继续打
        if has_monsters:
            self.bot.monster_hunter.hunt(red_dots, cx, cy)
        else:
            # 怪物死了→继续找
            self.change_state(BotState.HUNT)

    def _handle_flee(self, has_players):
        """逃跑状态 - 使用随机传送石"""
        self.bot.use_teleport()
        # 等一会儿再检查
        if time.time() - self.last_change_time > 5:
            self.change_state(BotState.FLEE_BACK)

    def _handle_flee_back(self):
        """逃跑后返回 - 等传送冷却"""
        if time.time() - self.last_change_time > 3:
            self.change_state(BotState.PATROL)

    def _handle_patrol(self, red_dots, cx, cy, has_monsters):
        """
        巡逻状态 - 附近没怪时四处走走
        """
        if has_monsters:
            # 发现怪物→切换打怪
            logger.info("[引擎] 巡逻时发现怪物！切换打怪")
            self.change_state(BotState.HUNT)
            return

        # 随机走一步
        elapsed = time.time() - self._patrol_start
        if elapsed > 30:
            # 巡逻了30秒还没怪→原地等
            logger.info("[引擎] 巡逻30秒无怪，原地等待")
            time.sleep(3)
            self._patrol_start = time.time()

        # 随机方向走
        direction = random.choice(['W', 'A', 'S', 'D'])
        self.bot.monster_hunter.send_key(direction, 0.3)
        time.sleep(0.8)