"""
麦当劳 MCP（Streamable HTTP）客户端。

用法
----
    from mcp_client import McdMcpClient

    client = McdMcpClient(token=os.environ["MCD_MCP_TOKEN"])
    tools  = client.list_tools()
    text   = client.call_tool("now-time-info", {})
    data   = client.extract_json(text)   # 从 "## Original Response\\n{...}" 中提取 JSON

设计要点（基于 2026-10-12 实测）
----------------------------------
* 协议：Streamable HTTP —— POST JSON-RPC 到 https://mcp.mcd.cn
* 认证：Authorization: Bearer <token>
* 服务端无状态：不返回 Mcp-Session-Id，单次 tools/call 即可直接调用
* 响应可能是 application/json 或 text/event-stream（SSE），两种都解析
* 限流 600 次/分钟，超了返回 429；本客户端在 429 时退避重试

本文件不依赖任何第三方库（仅标准库），Python >= 3.9 可用。
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

DEFAULT_URL = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2024-11-05"


class McdMcpError(RuntimeError):
    """MCP 调用层异常。"""


class McdMcpClient:
    """极简麦当劳 MCP 客户端。"""

    def __init__(
        self,
        token: str,
        url: str = DEFAULT_URL,
        max_retries: int = 4,
        timeout: int = 45,
    ) -> None:
        if not token:
            raise McdMcpError("token 不能为空，请从环境变量 MCD_MCP_TOKEN 读取")
        self.token = token
        self.url = url
        self.max_retries = max_retries
        self.timeout = timeout

    # -- 传输 ---------------------------------------------------------------
    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        last_err = "未知错误"
        for attempt in range(self.max_retries):
            req = urllib.request.Request(
                self.url,
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8")
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    wait = 4 * (attempt + 1)
                    print(f"  [mcp] 429 限流，退避 {wait}s 后重试 ({attempt + 1}/{self.max_retries})")
                    time.sleep(wait)
                    continue
                last_err = f"HTTP {e.code}"
                break
            except Exception as e:  # noqa: BLE001
                last_err = str(e)
                time.sleep(2 * (attempt + 1))
                continue
            return self._parse_jsonrpc(raw)
        raise McdMcpError(f"请求失败（{last_err}），已重试 {self.max_retries} 次")

    @staticmethod
    def _parse_jsonrpc(raw: str) -> Dict[str, Any]:
        s = raw.strip()
        if s.startswith("event:") or s.startswith("data:"):
            lines = [ln[5:].strip() for ln in s.splitlines() if ln.startswith("data:")]
            s = lines[-1] if lines else s
        try:
            return json.loads(s)
        except json.JSONDecodeError as e:
            raise McdMcpError(f"响应不是合法 JSON: {s[:200]}") from e

    # -- RPC ----------------------------------------------------------------
    def _rpc(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            payload["params"] = params
        resp = self._post(payload)
        if "error" in resp:
            raise McdMcpError(f"RPC 错误: {json.dumps(resp['error'], ensure_ascii=False)}")
        return resp.get("result", {})

    def list_tools(self) -> List[Dict[str, Any]]:
        """列出全部工具（tools/list 直接返回 {result:{tools:[...]}}）。"""
        result = self._rpc("tools/list", {})
        if isinstance(result, dict) and "tools" in result:
            return result["tools"]
        # 个别服务端可能把结果包在 content 里
        for item in result.get("content", []):
            if item.get("type") == "text":
                data = self.extract_json(item["text"])
                return data.get("tools", []) if isinstance(data, dict) else []
        return []

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        """调用工具，返回合并后的文本结果（所有 text 类型 content 拼接）。"""
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        parts: List[str] = []
        for item in result.get("content", []):
            if item.get("type") == "text":
                parts.append(item["text"])
        return "\n".join(parts)

    # -- 工具方法 -----------------------------------------------------------
    @staticmethod
    def extract_json(text: str) -> Any:
        """从工具返回文本中提取 JSON 对象。

        实测 tools/call 的文本形如：

            ## Original Response
            {...json...}

        本方法优先截取 `## Original Response` 之后的第一个平衡 JSON 对象；
        找不到标记则尝试整体解析。
        """
        if not text:
            return None
        m = re.search(r"## Original Response\s*\n(.+)$", text, re.S)
        seg = m.group(1).strip() if m else text.strip()
        start = seg.find("{")
        if start < 0:
            return None
        depth = 0
        for i in range(start, len(seg)):
            ch = seg[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(seg[start : i + 1])
                    except json.JSONDecodeError:
                        return None
        # 没闭合：退而求其次整体解析
        try:
            return json.loads(seg)
        except json.JSONDecodeError:
            return None
