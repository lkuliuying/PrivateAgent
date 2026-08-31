"""兼容服务端原有导入路径；所有模型契约来自同一共享核心。"""
import sys

from private_agent_core import contracts

sys.modules[__name__] = contracts
