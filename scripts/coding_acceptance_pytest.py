"""公开测试的收集边界适配；不改变测试、fixture 或断言的执行结果。"""


def pytest_configure(config):
    manager = config.pluginmanager
    original = manager._get_directory
    parent = config.rootpath.parent

    def directory(path):
        # pytest 为根目录选择 hook 时查询父目录类型；父级必为目录，无需越界 stat。
        return parent if path == parent else original(path)

    manager._get_directory = directory
