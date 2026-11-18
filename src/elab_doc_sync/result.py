"""コマンドの実行結果。

`run_*` 関数は CommandResult を返す。CLI（`cmd_*`）は echo=print を渡して従来どおり 1 行ずつ
表示し、exit_code を終了コードにする。MCP サーバーは echo を渡さず、data を JSON で返す。
"""

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class CommandResult:
    exit_code: int = 0
    data: dict = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)
    # 表示先。CLI は print を渡し、途中で例外になってもそこまでの表示を残す
    echo: Callable[[str], None] | None = field(default=None, repr=False, compare=False)

    def say(self, message: str = "") -> None:
        """人向けの表示を 1 行（改行を含んでもよい）追加する。"""
        self.messages.append(message)
        if self.echo is not None:
            self.echo(message)

    def to_dict(self) -> dict:
        return {"exit_code": self.exit_code, "data": self.data, "messages": self.messages}
