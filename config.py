from typing import Any

from zhenxun.configs.config import Config

MODULE_NAME = "nonebot_plugin_web_bottle"
"""配置模块名，必须与插件名一致才能在 WebUI 中显示"""

_base = Config.get(MODULE_NAME)
"""配置组引用，配置项由真寻启动时的 init_config 填充"""


def conf(key: str, default: Any = None) -> Any:
    """读取插件配置项

    实时读取，WebUI 中修改后无需重启即可生效。

    参数:
        key: 配置项键
        default: 配置项不存在时的默认值

    返回:
        Any: 配置项值
    """
    return _base.get(key, default)
