"""兼容服务端原有导入路径，并保持测试替换与类型标识一致。"""
import sys

from private_agent_core import runtime

sys.modules[__name__] = runtime
