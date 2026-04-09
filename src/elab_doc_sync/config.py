"""Load and validate .elab-sync.yaml configuration."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
import yaml


# body_format の既定値:
# - 既存設定で省略された場合は互換性のため html（HTML 変換して送信）
# - esync init で新規作成する場合は md を提案（cli.py 側で制御）
BODY_FORMAT_DEFAULT = "html"
BODY_FORMAT_INIT = "md"


@dataclass
class TargetConfig:
    title: str
    docs_dir: str
    id_file: str
    pattern: str = "*.md"
    mode: str = "merge"       # "merge" (全結合→1エンティティ) or "each" (1ファイル=1エンティティ)
    entity: str = "items"     # "items" or "experiments"
    tags: list[str] = None    # push 時に自動設定するタグ
    body_format: str = BODY_FORMAT_DEFAULT
    attachments_dir: str | None = None  # 添付ファイルディレクトリ（画像以外）

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


@dataclass
class Config:
    url: str
    api_key: str
    verify_ssl: bool
    targets: list[TargetConfig]


def _abort(msg: str) -> None:
    print(f"エラー: {msg}", file=sys.stderr)
    sys.exit(1)


def load_config(config_path: Path) -> Config:
    if not config_path.exists():
        _abort(
            f"設定ファイルが見つかりません: {config_path}\n"
            "→ 'elab-doc-sync init' で作成できます"
        )

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    elab = raw.get("elabftw", {})
    url = elab.get("url", "")
    if not url:
        _abort(
            "eLabFTW の URL が設定されていません\n"
            "→ .elab-sync.yaml の elabftw.url を確認してください"
        )

    api_key = os.environ.get("ELABFTW_API_KEY", "").strip() or elab.get("api_key", "").strip()
    if not api_key:
        _abort(
            "API キーが設定されていません\n"
            "→ .elab-sync.yaml の elabftw.api_key に設定するか、\n"
            '  環境変数を設定してください: export ELABFTW_API_KEY="your_key"'
        )

    verify_ssl = elab.get("verify_ssl", True)

    targets = []
    for t in raw.get("targets", []):
        mode = t.get("mode", "merge")
        entity = t.get("entity", "items")
        # resources は items のエイリアス（eLabFTW Web UI の表示名）
        if entity in ("resources", "resource"):
            entity = "items"
        title = t.get("title", "") if mode == "merge" else t.get("title", "")
        body_format = t.get("body_format", BODY_FORMAT_DEFAULT)
        if body_format not in ("md", "html"):
            _abort(f"body_format は 'md' または 'html' を指定してください（現在: {body_format!r}）")
        targets.append(TargetConfig(
            title=title,
            docs_dir=t["docs_dir"],
            id_file=t.get("id_file", ".elab-sync-ids/default.id"),
            pattern=t.get("pattern", "*.md"),
            mode=mode,
            entity=entity,
            tags=t.get("tags", []),
            body_format=body_format,
            attachments_dir=t.get("attachments_dir"),
        ))

    if not targets:
        _abort(
            "同期ターゲットが定義されていません\n"
            "→ .elab-sync.yaml の targets を確認してください"
        )

    return Config(url=url, api_key=api_key, verify_ssl=verify_ssl, targets=targets)
