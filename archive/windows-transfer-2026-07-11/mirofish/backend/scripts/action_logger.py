"""
动作日志记录器
用于记录OASIS模拟中每个Agent的动作，供后端监控使用

日志结构:
    sim_xxx/
    ├── twitter/
    │   └── actions.jsonl    # Twitter 平台动作日志
    ├── reddit/
    │   └── actions.jsonl    # Reddit 平台动作日志
    ├── simulation.log       # 主模拟进程日志
    └── run_state.json       # 运行状态（API 查询用）
"""

import json
import os
import logging
from datetime import datetime
from typing import Dict, Any, Optional


def _coerce_positive_int(value: Any) -> Optional[int]:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return None
    return coerced if coerced > 0 else None


def _configured_total_rounds(config: Dict[str, Any]) -> int:
    time_config = config.get("time_config", {}) if isinstance(config, dict) else {}
    total_hours = _coerce_positive_int(time_config.get("total_simulation_hours")) or 72
    minutes_per_round = _coerce_positive_int(time_config.get("minutes_per_round")) or 30
    return max((total_hours * 60) // minutes_per_round, 1)


def _read_json_file(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _resolve_rounds_metadata(config: Dict[str, Any], base_dir: str) -> Dict[str, Any]:
    configured_total_rounds = _configured_total_rounds(config)
    candidate_dirs = []
    if base_dir:
        normalized_dir = os.path.abspath(base_dir)
        candidate_dirs.append(normalized_dir)
        parent_dir = os.path.dirname(normalized_dir)
        if parent_dir and parent_dir != normalized_dir:
            candidate_dirs.append(parent_dir)

    max_rounds_applied = None
    for candidate_dir in candidate_dirs:
        run_state = _read_json_file(os.path.join(candidate_dir, "run_state.json"))
        if not run_state:
            continue

        total_rounds = _coerce_positive_int(run_state.get("total_rounds"))
        max_rounds_applied = _coerce_positive_int(run_state.get("max_rounds_applied"))
        if total_rounds is not None:
            return {
                "total_rounds": total_rounds,
                "configured_total_rounds": configured_total_rounds,
                "max_rounds_applied": max_rounds_applied,
                "rounds_source": "run_state.total_rounds",
            }
        if max_rounds_applied is not None:
            return {
                "total_rounds": max_rounds_applied,
                "configured_total_rounds": configured_total_rounds,
                "max_rounds_applied": max_rounds_applied,
                "rounds_source": "run_state.max_rounds_applied",
            }

    return {
        "total_rounds": configured_total_rounds,
        "configured_total_rounds": configured_total_rounds,
        "max_rounds_applied": max_rounds_applied,
        "rounds_source": "config.time_config",
    }


class PlatformActionLogger:
    """单平台动作日志记录器"""
    
    def __init__(self, platform: str, base_dir: str):
        """
        初始化日志记录器
        
        Args:
            platform: 平台名称 (twitter/reddit)
            base_dir: 模拟目录的基础路径
        """
        self.platform = platform
        self.base_dir = base_dir
        self.log_dir = os.path.join(base_dir, platform)
        self.log_path = os.path.join(self.log_dir, "actions.jsonl")
        self._ensure_dir()
    
    def _ensure_dir(self):
        """确保目录存在"""
        os.makedirs(self.log_dir, exist_ok=True)
    
    def log_action(
        self,
        round_num: int,
        agent_id: int,
        agent_name: str,
        action_type: str,
        action_args: Optional[Dict[str, Any]] = None,
        result: Optional[str] = None,
        success: bool = True,
        round_event: Optional[Dict[str, Any]] = None
    ):
        """记录一个动作"""
        entry = {
            "round": round_num,
            "timestamp": datetime.now().isoformat(),
            "agent_id": agent_id,
            "agent_name": agent_name,
            "action_type": action_type,
            "action_args": action_args or {},
            "result": result,
            "success": success,
        }
        if round_event:
            entry["event_beat_id"] = round_event.get("event_beat_id")
            entry["round_event"] = round_event
        
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    def log_round_start(
        self,
        round_num: int,
        simulated_hour: int,
        round_event: Optional[Dict[str, Any]] = None
    ):
        """记录轮次开始"""
        entry = {
            "round": round_num,
            "timestamp": datetime.now().isoformat(),
            "event_type": "round_start",
            "simulated_hour": simulated_hour,
        }
        if round_event:
            entry["event_beat_id"] = round_event.get("event_beat_id")
            entry["round_event"] = round_event
        
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    def log_round_end(
        self,
        round_num: int,
        actions_count: int,
        round_event: Optional[Dict[str, Any]] = None
    ):
        """记录轮次结束"""
        entry = {
            "round": round_num,
            "timestamp": datetime.now().isoformat(),
            "event_type": "round_end",
            "actions_count": actions_count,
        }
        if round_event:
            entry["event_beat_id"] = round_event.get("event_beat_id")
            entry["round_event"] = round_event
        
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    def log_simulation_start(
        self,
        config: Dict[str, Any],
        effective_total_rounds: Optional[int] = None
    ):
        """记录模拟开始"""
        rounds_metadata = _resolve_rounds_metadata(config, self.base_dir)
        explicit_total_rounds = _coerce_positive_int(effective_total_rounds)
        if explicit_total_rounds is not None:
            rounds_metadata = dict(rounds_metadata)
            rounds_metadata["total_rounds"] = explicit_total_rounds
            rounds_metadata["rounds_source"] = "runner.effective_total_rounds"
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "simulation_start",
            "platform": self.platform,
            "total_rounds": rounds_metadata["total_rounds"],
            "configured_total_rounds": rounds_metadata["configured_total_rounds"],
            "rounds_source": rounds_metadata["rounds_source"],
            "agents_count": len(config.get("agent_configs", [])),
        }
        if rounds_metadata["max_rounds_applied"] is not None:
            entry["max_rounds_applied"] = rounds_metadata["max_rounds_applied"]
        
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    def log_simulation_end(self, total_rounds: int, total_actions: int):
        """记录模拟结束"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "simulation_end",
            "platform": self.platform,
            "total_rounds": total_rounds,
            "total_actions": total_actions,
        }
        
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')


class SimulationLogManager:
    """
    模拟日志管理器
    统一管理所有日志文件，按平台分离
    """
    
    def __init__(self, simulation_dir: str):
        """
        初始化日志管理器
        
        Args:
            simulation_dir: 模拟目录路径
        """
        self.simulation_dir = simulation_dir
        self.twitter_logger: Optional[PlatformActionLogger] = None
        self.reddit_logger: Optional[PlatformActionLogger] = None
        self._main_logger: Optional[logging.Logger] = None
        
        # 设置主日志
        self._setup_main_logger()
    
    def _setup_main_logger(self):
        """设置主模拟日志"""
        log_path = os.path.join(self.simulation_dir, "simulation.log")
        
        # 创建 logger
        self._main_logger = logging.getLogger(f"simulation.{os.path.basename(self.simulation_dir)}")
        self._main_logger.setLevel(logging.INFO)
        self._main_logger.handlers.clear()
        
        # 文件处理器
        file_handler = logging.FileHandler(log_path, encoding='utf-8', mode='w')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        self._main_logger.addHandler(file_handler)
        
        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter(
            '[%(asctime)s] %(message)s',
            datefmt='%H:%M:%S'
        ))
        self._main_logger.addHandler(console_handler)
        
        self._main_logger.propagate = False
    
    def get_twitter_logger(self) -> PlatformActionLogger:
        """获取 Twitter 平台日志记录器"""
        if self.twitter_logger is None:
            self.twitter_logger = PlatformActionLogger("twitter", self.simulation_dir)
        return self.twitter_logger
    
    def get_reddit_logger(self) -> PlatformActionLogger:
        """获取 Reddit 平台日志记录器"""
        if self.reddit_logger is None:
            self.reddit_logger = PlatformActionLogger("reddit", self.simulation_dir)
        return self.reddit_logger
    
    def log(self, message: str, level: str = "info"):
        """记录主日志"""
        if self._main_logger:
            getattr(self._main_logger, level.lower(), self._main_logger.info)(message)
    
    def info(self, message: str):
        self.log(message, "info")
    
    def warning(self, message: str):
        self.log(message, "warning")
    
    def error(self, message: str):
        self.log(message, "error")
    
    def debug(self, message: str):
        self.log(message, "debug")


# ============ 兼容旧接口 ============

class ActionLogger:
    """
    动作日志记录器（兼容旧接口）
    建议使用 SimulationLogManager 代替
    """
    
    def __init__(self, log_path: str):
        self.log_path = log_path
        self._ensure_dir()
    
    def _ensure_dir(self):
        log_dir = os.path.dirname(self.log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
    
    def log_action(
        self,
        round_num: int,
        platform: str,
        agent_id: int,
        agent_name: str,
        action_type: str,
        action_args: Optional[Dict[str, Any]] = None,
        result: Optional[str] = None,
        success: bool = True,
        round_event: Optional[Dict[str, Any]] = None
    ):
        entry = {
            "round": round_num,
            "timestamp": datetime.now().isoformat(),
            "platform": platform,
            "agent_id": agent_id,
            "agent_name": agent_name,
            "action_type": action_type,
            "action_args": action_args or {},
            "result": result,
            "success": success,
        }
        if round_event:
            entry["event_beat_id"] = round_event.get("event_beat_id")
            entry["round_event"] = round_event
        
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    def log_round_start(
        self,
        round_num: int,
        simulated_hour: int,
        platform: str,
        round_event: Optional[Dict[str, Any]] = None
    ):
        entry = {
            "round": round_num,
            "timestamp": datetime.now().isoformat(),
            "platform": platform,
            "event_type": "round_start",
            "simulated_hour": simulated_hour,
        }
        if round_event:
            entry["event_beat_id"] = round_event.get("event_beat_id")
            entry["round_event"] = round_event
        
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    def log_round_end(
        self,
        round_num: int,
        actions_count: int,
        platform: str,
        round_event: Optional[Dict[str, Any]] = None
    ):
        entry = {
            "round": round_num,
            "timestamp": datetime.now().isoformat(),
            "platform": platform,
            "event_type": "round_end",
            "actions_count": actions_count,
        }
        if round_event:
            entry["event_beat_id"] = round_event.get("event_beat_id")
            entry["round_event"] = round_event
        
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    def log_simulation_start(
        self,
        platform: str,
        config: Dict[str, Any],
        effective_total_rounds: Optional[int] = None
    ):
        rounds_metadata = _resolve_rounds_metadata(config, os.path.dirname(self.log_path))
        explicit_total_rounds = _coerce_positive_int(effective_total_rounds)
        if explicit_total_rounds is not None:
            rounds_metadata = dict(rounds_metadata)
            rounds_metadata["total_rounds"] = explicit_total_rounds
            rounds_metadata["rounds_source"] = "runner.effective_total_rounds"
        entry = {
            "timestamp": datetime.now().isoformat(),
            "platform": platform,
            "event_type": "simulation_start",
            "total_rounds": rounds_metadata["total_rounds"],
            "configured_total_rounds": rounds_metadata["configured_total_rounds"],
            "rounds_source": rounds_metadata["rounds_source"],
            "agents_count": len(config.get("agent_configs", [])),
        }
        if rounds_metadata["max_rounds_applied"] is not None:
            entry["max_rounds_applied"] = rounds_metadata["max_rounds_applied"]
        
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    def log_simulation_end(self, platform: str, total_rounds: int, total_actions: int):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "platform": platform,
            "event_type": "simulation_end",
            "total_rounds": total_rounds,
            "total_actions": total_actions,
        }
        
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')


# 全局日志实例（兼容旧接口）
_global_logger: Optional[ActionLogger] = None


def get_logger(log_path: Optional[str] = None) -> ActionLogger:
    """获取全局日志实例（兼容旧接口）"""
    global _global_logger
    
    if log_path:
        _global_logger = ActionLogger(log_path)
    
    if _global_logger is None:
        _global_logger = ActionLogger("actions.jsonl")
    
    return _global_logger
