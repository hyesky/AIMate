"""钉钉通道（骨架）。

生产接线：使用 dingtalk-stream 的 StreamClient 建立长连接，接收消息回调，
转交统一调度器。
"""
from __future__ import annotations


class DingtalkChannel:
    def __init__(self, client_id: str, client_secret: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret

    def generate_client_id(self) -> str:
        """SSE 长连接客户端标识（生产返回 client_id）。"""
        return self.client_id
