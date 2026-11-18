"""コマンドの実行結果。

`run_*` 関数は CommandResult を返す。CLI（`cmd_*`）は echo=cli_echo を渡して従来どおり 1 行ずつ
表示し、exit_code を終了コードにする。MCP サーバーは echo を渡さず、data を JSON で返す。
"""

import sys
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import Callable

# returns_partial_result の実行中に作られた CommandResult
_created: ContextVar[list | None] = ContextVar("elab_doc_sync_created_results", default=None)


def cli_echo(message: str, stderr: bool = False) -> None:
    """CLI 用の表示先。警告・エラーは標準エラー出力に出す。"""
    print(message, file=sys.stderr if stderr else sys.stdout)


@dataclass
class CommandResult:
    exit_code: int = 0
    data: dict = field(default_factory=dict)
    messages: list[str] = field(default_factory=list)
    # 警告・エラー（CLI では標準エラー出力）。messages には含めない
    warnings: list[str] = field(default_factory=list)
    # 表示先 echo(message, stderr=False)。CLI は cli_echo を渡し、途中で例外になってもそこまでの表示を残す
    echo: Callable[..., None] | None = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        created = _created.get()
        if created is not None:
            created.append(self)

    def say(self, message: str = "") -> None:
        """人向けの表示を 1 行（改行を含んでもよい）追加する。"""
        self.messages.append(message)
        if self.echo is not None:
            self.echo(message)

    def warn(self, message: str) -> None:
        """警告・エラーを 1 行追加する。"""
        self.warnings.append(message)
        if self.echo is not None:
            self.echo(message, stderr=True)

    def fail(self, message: str, exit_code: int = 1) -> "CommandResult":
        """エラーを追加して終了コードを設定し、自身を返す（`return res.fail(...)` で使う）。"""
        self.warn(message)
        self.exit_code = exit_code
        return self

    def to_dict(self) -> dict:
        return {"exit_code": self.exit_code, "data": self.data, "messages": self.messages,
                "warnings": self.warnings}


def returns_partial_result(fn):
    """run_* 用。途中で例外になったら、それまでの CommandResult を例外の partial_result に付ける。

    書き換え系では一部の変更が済んだ後に失敗することがあるため、呼び出し元（MCP など）が
    済んだ変更を確認できるようにする。
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _created.set([])
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            created = _created.get()
            if created and getattr(exc, "partial_result", None) is None:
                exc.partial_result = created[0]
            raise
        finally:
            _created.reset(token)
    return wrapper


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
