"""兼容原执行宿主导入路径，使用共享协议实现。"""
import sys

from private_agent_core.execution import exec_host_client

sys.modules[__name__] = exec_host_client
