"""MCP server exposing multi-agent dev workflow tools."""

import os
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("multi-agent-dev")


def _run_dev(subcommand: str, args: list[str] | None = None, cwd: str | None = None) -> str:
    """Run ./dev subcommand and return stdout."""
    work_dir = cwd or os.getcwd()
    dev_path = Path(work_dir) / "dev"
    if not dev_path.exists():
        return f"エラー: {work_dir} に dev スクリプトが見つかりません"
    # プロジェクトルート確認: AI_discussions.md の存在で判定
    if subcommand != "init" and not (Path(work_dir) / "AI_discussions.md").exists():
        return f"エラー: {work_dir} はマルチエージェント開発プロジェクトではありません"
    cmd = [str(dev_path), subcommand] + (args or [])
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=work_dir)
    output = result.stdout
    if result.returncode != 0 and result.stderr:
        output += f"\nstderr: {result.stderr}"
    return output.strip() or "(出力なし)"


@mcp.tool()
def propose(request: str, cwd: str | None = None) -> str:
    """Feature Proposal Agent で要求を仕様に整理する。結果は AI_discussions.md に記録される。

    Args:
        request: ユーザーの要求テキスト
        cwd: プロジェクトディレクトリのパス（省略時はカレントディレクトリ）
    """
    return _run_dev("propose", [request], cwd)


@mcp.tool()
def review(cwd: str | None = None) -> str:
    """直近コミットのコードレビュー＋ドキュメントレビューを実行する。結果は AI_discussions.md に記録される。

    Args:
        cwd: プロジェクトディレクトリのパス（省略時はカレントディレクトリ）
    """
    return _run_dev("review", cwd=cwd)


@mcp.tool()
def status(cwd: str | None = None) -> str:
    """AI_discussions.md の最新エントリを表示する。

    Args:
        cwd: プロジェクトディレクトリのパス（省略時はカレントディレクトリ）
    """
    return _run_dev("status", cwd=cwd)


@mcp.tool()
def init_project(name: str, cwd: str | None = None) -> str:
    """新規プロジェクトディレクトリを作成する。

    Args:
        name: プロジェクト名（英数字で始まり、英数字・ハイフン・アンダースコアのみ）
        cwd: 親ディレクトリのパス（省略時はカレントディレクトリ）
    """
    return _run_dev("init", [name], cwd)


if __name__ == "__main__":
    mcp.run()
