"""notify-hub：本机通知网关。任何程序调用同一个接口，按级别、去重、限流、失败重发的规则推到手机上的 Lark。"""
from .hub import Hub, Result, notify
from .models import Level

__version__ = "0.2.1"
__all__ = ["Hub", "Level", "Result", "notify", "__version__"]
