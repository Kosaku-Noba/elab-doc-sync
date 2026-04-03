"""elab-doc-sync ブートストラップスクリプト。

使い方:
  python sync.py              # 同期実行
  python sync.py init         # 初回セットアップ
  python sync.py status       # 状態確認
  python sync.py --dry-run    # 実行せずに確認
  python sync.py --force      # 強制同期
"""

import shutil
import subprocess
import sys
from pathlib import Path

# ── 設定 ─────────────────────────────────────────────────
TOOL_REPO = "https://github.com/your-org/elab-doc-sync.git"  # ← 社内リポジトリの URL に変更してください
TOOL_DIR = Path(".tool/elab-doc-sync")


def run(cmd, **kwargs):
    """コマンドを実行し、失敗時はメッセージを表示して終了。"""
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        print(f"エラー: コマンドが失敗しました: {' '.join(str(c) for c in cmd)}", file=sys.stderr)
        sys.exit(result.returncode)
    return result


def ensure_tool():
    """ツールが未取得ならclone し、コマンドが使えなければインストールする。"""
    # 1. clone
    if not TOOL_DIR.exists():
        if not shutil.which("git"):
            print("エラー: git が見つかりません。Git をインストールしてください。", file=sys.stderr)
            sys.exit(1)
        print(f"ツールを取得中: {TOOL_REPO}")
        TOOL_DIR.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", TOOL_REPO, str(TOOL_DIR)])

    # 2. install (elab-doc-sync コマンドが PATH にあればスキップ)
    if shutil.which("elab-doc-sync"):
        return

    print("ツールをインストール中...")
    if shutil.which("uv"):
        run(["uv", "sync"], cwd=str(TOOL_DIR))
    else:
        run([sys.executable, "-m", "pip", "install", "-e", str(TOOL_DIR)])


def main():
    ensure_tool()
    cmd = ["elab-doc-sync"] + sys.argv[1:]
    sys.exit(subprocess.run(cmd).returncode)


if __name__ == "__main__":
    main()
