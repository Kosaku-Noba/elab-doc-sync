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


def redact(text: str, *secrets: str | None) -> str:
    """text に含まれる秘密値（API キーなど）を *** に置き換える。

    例外メッセージは値を repr やバイト列の表記で含むことがあるため、それらの表記と、
    改行で区切られた各部分（4 文字以上）も置き換える。
    """
    for secret in secrets:
        if not secret:
            continue
        variants = {secret, repr(secret)[1:-1], repr(secret.encode("utf-8"))[2:-1]}
        variants.update(part for part in secret.splitlines() if len(part.strip()) >= 4)
        for variant in sorted(variants, key=len, reverse=True):
            if variant:
                text = text.replace(variant, "***")
    return text
