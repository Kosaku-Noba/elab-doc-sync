"""CLI entry point for elab-doc-sync."""

import argparse
import shutil
import sys
from pathlib import Path

import yaml

from .client import ELabFTWClient
from .config import load_config
from .sync import DocsSyncer, EachDocsSyncer

DEFAULT_CONFIG = ".elab-sync.yaml"


def _make_syncer(client, target, project_root):
    if target.mode == "each":
        return EachDocsSyncer(client, target, project_root)
    return DocsSyncer(client, target, project_root)


def cmd_sync(args):
    config_path = Path(args.config)
    project_root = config_path.parent or Path(".")
    config = load_config(config_path)
    client = ELabFTWClient(config.url, config.api_key, config.verify_ssl)

    updated = 0
    for target in config.targets:
        if args.target and target.title != args.target:
            continue
        syncer = _make_syncer(client, target, project_root)

        if args.dry_run:
            entity_label = "実験ノート" if target.entity == "experiments" else "アイテム"
            if isinstance(syncer, EachDocsSyncer):
                results = syncer.dry_run()
                if not results:
                    print(f"  [each: {target.docs_dir}] ドキュメントなし")
                    continue
                for r in results:
                    status = "変更あり" if r["changed"] else "変更なし（スキップ）"
                    dest = f"{entity_label} #{r['entity_id']}" if r["entity_id"] else f"新しい{entity_label}"
                    print(f"  [{r['title']}] {status}")
                    print(f"    画像: {r['images']}件  → {dest}")
            else:
                info = syncer.dry_run()
                if not info["files"]:
                    print(f"  [{target.title}] ドキュメントなし")
                    continue
                status = "変更あり" if info["changed"] else "変更なし（スキップ）"
                dest = f"{entity_label} #{info['item_id']}" if info["item_id"] else f"新しい{entity_label}"
                print(f"  [{target.title}] {status}")
                print(f"    ファイル: {info['files']}件  画像: {info['images']}件  → {dest}")
            continue

        try:
            if isinstance(syncer, EachDocsSyncer):
                updated += syncer.sync(force=args.force)
            else:
                if syncer.sync(force=args.force):
                    updated += 1
        except Exception as e:
            label = target.title or f"each: {target.docs_dir}"
            print(f"  [{label}] エラー: {e}", file=sys.stderr)

    if not args.dry_run:
        print(f"\n完了: {updated} 件更新しました")


def cmd_status(args):
    config_path = Path(args.config)
    project_root = config_path.parent or Path(".")
    config = load_config(config_path)

    for target in config.targets:
        client = ELabFTWClient(config.url, config.api_key, config.verify_ssl)
        syncer = _make_syncer(client, target, project_root)
        entity_label = "実験ノート" if target.entity == "experiments" else "アイテム"

        if isinstance(syncer, EachDocsSyncer):
            results = syncer.dry_run()
            if not results:
                print(f"  [each: {target.docs_dir}] ドキュメントなし")
                continue
            for r in results:
                status = "変更あり" if r["changed"] else "最新"
                id_str = f"{entity_label} #{r['entity_id']}" if r["entity_id"] else "未作成"
                print(f"  [{r['title']}] {status}（{id_str}）")
        else:
            try:
                body = syncer.collect_docs()
                changed = syncer.has_changed(body)
            except FileNotFoundError as e:
                print(f"  [{target.title}] エラー: {e}")
                continue
            status = "変更あり" if changed else "最新"
            item_id = syncer.read_item_id()
            id_str = f"{entity_label} #{item_id}" if item_id else "未作成"
            print(f"  [{target.title}] {status}（{id_str}）")


def _template_dir():
    """パッケージ同梱の template ディレクトリを返す。"""
    return Path(__file__).resolve().parent / "template"


def _copy_template_files(docs_dir):
    """テンプレートファイル (.gitignore, README.md, docs/) をコピーする。"""
    tmpl = _template_dir()
    if not tmpl.is_dir():
        return

    for name in [".gitignore", "README.md"]:
        src = tmpl / name
        if not src.exists():
            continue
        dst = Path(name)
        if dst.exists():
            print(f"  {name} は既に存在するためスキップ")
        else:
            shutil.copy2(src, dst)
            print(f"  {name} を作成しました")

    docs_path = Path(docs_dir)
    if not docs_path.exists():
        docs_path.mkdir(parents=True)
        (docs_path / ".gitkeep").touch()
        print(f"  {docs_dir} ディレクトリを作成しました")


def cmd_init(args):
    config_path = Path(args.config)

    if config_path.exists():
        ans = input(f"{config_path} は既に存在します。上書きしますか？ [y/N]: ").strip().lower()
        if ans != "y":
            print("中止しました")
            return

    print("=== elab-doc-sync セットアップ ===\n")

    url = ""
    while not url:
        url = input("eLabFTW の URL: ").strip().rstrip("/")

    ssl_input = input("SSL 証明書を検証しますか？ [Y/n]: ").strip().lower()
    verify_ssl = ssl_input != "n"

    docs_dir = input("ドキュメントディレクトリ [docs/]: ").strip() or "docs/"
    pattern = input("ファイルパターン [*.md]: ").strip() or "*.md"

    mode_input = input("同期モード — merge: 全ファイルを1つに結合 / each: 1ファイル=1ノート [merge]: ").strip().lower() or "merge"
    entity_input = input("送信先 — items: アイテム / experiments: 実験ノート [items]: ").strip().lower() or "items"

    target = {"docs_dir": docs_dir, "pattern": pattern, "mode": mode_input, "entity": entity_input}

    if mode_input == "merge":
        title = ""
        while not title:
            title = input("eLabFTW アイテムのタイトル: ").strip()
        target["title"] = title
    else:
        target["title"] = ""

    data = {
        "elabftw": {"url": url, "verify_ssl": verify_ssl},
        "targets": [target],
    }

    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    # テンプレートファイルのコピー
    print("\nテンプレートファイルを展開中...")
    _copy_template_files(docs_dir)

    print(f"\n✅ 設定ファイルを作成しました: {config_path}")
    print(
        "\n次に、eLabFTW の API キーを環境変数に設定してください:\n"
        '  export ELABFTW_API_KEY="your_api_key"\n'
        "\n永続化するには ~/.bashrc (Linux) に追記してください:\n"
        '  echo \'export ELABFTW_API_KEY="your_api_key"\' >> ~/.bashrc\n'
        "\nWindows (PowerShell) の場合:\n"
        '  [System.Environment]::SetEnvironmentVariable("ELABFTW_API_KEY","your_api_key","User")\n'
        "\n準備ができたら以下で同期を開始できます:\n"
        "  elab-doc-sync --dry-run  （確認）\n"
        "  elab-doc-sync            （実行）"
    )


def main():
    parser = argparse.ArgumentParser(prog="elab-doc-sync", description="Markdown ドキュメントを eLabFTW に同期")
    parser.add_argument("--config", "-c", default=DEFAULT_CONFIG, help="設定ファイルのパス")
    parser.add_argument("--target", "-t", default=None, help="同期するターゲット名")
    parser.add_argument("--force", "-f", action="store_true", help="変更がなくても強制同期")
    parser.add_argument("--dry-run", "-n", action="store_true", help="実行せずに同期内容を確認")

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status", help="同期状態を確認")
    sub.add_parser("init", help="対話的に設定ファイルを作成")

    args = parser.parse_args()
    if args.command == "status":
        cmd_status(args)
    elif args.command == "init":
        cmd_init(args)
    else:
        cmd_sync(args)
