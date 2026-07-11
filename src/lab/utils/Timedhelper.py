from __future__ import annotations

import functools
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeVar, cast

from lab.utils.console.logger import Logger

# 定义 TypeVar 以处理泛型 Callable
T = TypeVar("T", bound=Callable[..., Any])  # 指定 bound 为 Callable，并使用 ... 表示任意参数


def timed_function(func: T) -> T:
    """
    装饰器函数：接受一个函数作为输入，统计并打印该函数的总执行时间。

    参数:
    func (T): 需要计时的函数或可调用对象。

    返回:
    T: 一个包装后的函数，与原始函数具有相同的签名。
    """

    func_name: str = getattr(func, "__name__", repr(func))

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:  # 显式使用 Any 处理参数和返回类型
        start_time: float = time.perf_counter()  # 添加类型注解 float
        result: Any = func(*args, **kwargs)  # 显式类型注解
        end_time: float = time.perf_counter()  # 添加类型注解 float
        total_time: float = end_time - start_time  # 计算总用时
        Logger.info(f"函数 {func_name} 总用时: {total_time:.4f} 秒")  # 打印用时
        return result  # 返回结果

    return cast("T", wrapper)  # 使用 cast 确保类型兼容


def get_time_tag_with_millis():
    now = datetime.now()
    # 格式: HH-MM-SS-mmm
    return now.strftime("%H-%M-%S-") + f"{int(now.microsecond / 1000):03d}"  # 因为并发可能在同一秒,所以必须加上毫秒
