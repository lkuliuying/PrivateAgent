"""保留服务端导入路径，复用共享模型模块。"""
import sys

from private_agent_core.llm import url_policy

sys.modules[__name__] = url_policy
