from dataclasses import dataclass, field


@dataclass
class Plan:
    """prepare/confirm 共用的“操作计划”：规范化参数 + 预览 + 风控结果 + 执行所需的行对象。"""
    type: str
    params: dict
    summary: dict
    risk: dict
    data: dict = field(default_factory=dict)
