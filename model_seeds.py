"""内置模型种子数据。

保持纯净开源默认：初始不内置任何第三方中转站或未配置模型，
由用户按需在界面的「模型管理」中通过【⚡ 工作流快捷接入】一键填入，或自主添加。
"""

from __future__ import annotations

from typing import Any

DEFAULT_MODELS: list[dict[str, Any]] = []
