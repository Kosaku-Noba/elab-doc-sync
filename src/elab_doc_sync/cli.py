"""CLI entry point for elab-doc-sync."""

import argparse
import difflib
import json
import shutil
import sys
from pathlib import Path

import yaml
from markdownify import markdownify as html_to_md

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


def cmd_pull(args):
    """eLabFTW からエンティティを取得してローカルに Markdown として保存する。"""
    config_path = Path(args.config)
    project_root = config_path.parent or Path(".")
    config = load_config(config_path)
    client = ELabFTWClient(config.url, config.api_key, config.verify_ssl)

    pulled = 0
    for target in config.targets:
        if args.target and target.title != args.target:
            continue

        docs_dir = project_root / target.docs_dir
        docs_dir.mkdir(parents=True, exist_ok=True)
        entity_label = "実験ノート" if target.entity == "experiments" else "アイテム"
        get_fn = client.get_experiment if target.entity == "experiments" else client.get_item
        list_fn = client.list_experiments if target.entity == "experiments" else client.list_items

        if target.mode == "each":
            syncer = EachDocsSyncer(client, target, project_root)
            mapping = syncer._load_mapping()

            if args.id:
                # 指定 ID を pull
                entities = {args.id}
            elif mapping:
                # 既存 mapping の ID を pull
                entities = set(mapping.values())
            else:
                # mapping がない場合は全件取得
                all_entities = list_fn()
                entities = {e["id"] for e in all_entities}

            for eid in entities:
                try:
                    data = get_fn(eid)
                except Exception as e:
                    print(f"  {entity_label} #{eid} の取得に失敗: {e}", file=sys.stderr)
                    continue

                title = data.get("title", f"untitled_{eid}")
                body_html = data.get("body", "") or ""
                body_md = html_to_md(body_html, heading_style="ATX").strip()

                filename = f"{title}.md"
                filepath = docs_dir / filename

                if not args.force and filepath.exists():
                    print(f"  [{title}] 既にローカルに存在（スキップ、--force で上書き）")
                    continue

                filepath.write_text(body_md + "\n", encoding="utf-8")

                # mapping を更新
                mapping[filename] = eid
                syncer._save_mapping(mapping)
                # hash を保存して次回 push 時に差分なしと判定されるようにする
                syncer._save_hash(filename, body_md)

                print(f"  [{title}] {entity_label} #{eid} → {filepath}")
                pulled += 1

        else:
            # merge モード: 1 エンティティ → 1 ファイル
            syncer = DocsSyncer(client, target, project_root)
            eid = syncer.read_item_id()

            if args.id:
                eid = args.id

            if eid is None:
                print(f"  [{target.title}] 同期先の ID が不明です（--id で指定してください）")
                continue

            try:
                data = get_fn(eid)
            except Exception as e:
                print(f"  [{target.title}] {entity_label} #{eid} の取得に失敗: {e}", file=sys.stderr)
                continue

            body_html = data.get("body", "") or ""
            body_md = html_to_md(body_html, heading_style="ATX").strip()

            filename = f"{target.title or 'pulled'}.md"
            filepath = docs_dir / filename

            if not args.force and filepath.exists():
                print(f"  [{target.title}] 既にローカルに存在（スキップ、--force で上書き）")
                continue

            filepath.write_text(body_md + "\n", encoding="utf-8")

            # ID とハッシュを保存
            syncer.save_item_id(eid)
            syncer.save_hash(body_md)

            print(f"  [{target.title}] {entity_label} #{eid} → {filepath}")
            pulled += 1

    print(f"\n完了: {pulled} 件取得しました")


def _show_diff(title, local_text, remote_text):
    """unified diff を表示。差分がなければ False を返す。"""
    local_lines = local_text.splitlines(keepends=True)
    remote_lines = remote_text.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        remote_lines, local_lines,
        fromfile=f"eLabFTW: {title}",
        tofile=f"ローカル: {title}",
    ))
    if not diff:
        return False
    sys.stdout.writelines(diff)
    print()
    return True


def cmd_diff(args):
    """ローカルと eLabFTW 上の内容の差分を表示する。"""
    config_path = Path(args.config)
    project_root = config_path.parent or Path(".")
    config = load_config(config_path)
    client = ELabFTWClient(config.url, config.api_key, config.verify_ssl)

    has_diff = False
    for target in config.targets:
        if args.target and target.title != args.target:
            continue

        docs_dir = project_root / target.docs_dir
        get_fn = client.get_experiment if target.entity == "experiments" else client.get_item

        if target.mode == "each":
            syncer = EachDocsSyncer(client, target, project_root)
            mapping = syncer._load_mapping()

            for filename, eid in mapping.items():
                local_path = docs_dir / filename
                if not local_path.exists():
                    print(f"  [{filename}] ローカルにファイルなし（eLabFTW #{eid} のみ存在）\n")
                    has_diff = True
                    continue

                try:
                    data = get_fn(eid)
                except Exception as e:
                    print(f"  [{filename}] eLabFTW #{eid} の取得に失敗: {e}\n", file=sys.stderr)
                    continue

                local_md = local_path.read_text(encoding="utf-8").strip()
                remote_md = html_to_md(data.get("body", "") or "", heading_style="ATX").strip()

                if _show_diff(filename, local_md, remote_md):
                    has_diff = True
                else:
                    print(f"  [{filename}] 差分なし")

        else:
            syncer = DocsSyncer(client, target, project_root)
            eid = syncer.read_item_id()
            if eid is None:
                print(f"  [{target.title}] 同期先の ID が不明です")
                continue

            try:
                data = get_fn(eid)
            except Exception as e:
                print(f"  [{target.title}] eLabFTW #{eid} の取得に失敗: {e}\n", file=sys.stderr)
                continue

            try:
                local_md = syncer.collect_docs()
            except FileNotFoundError as e:
                print(f"  [{target.title}] {e}\n")
                has_diff = True
                continue

            remote_md = html_to_md(data.get("body", "") or "", heading_style="ATX").strip()

            if _show_diff(target.title, local_md, remote_md):
                has_diff = True
            else:
                print(f"  [{target.title}] 差分なし")

    if not has_diff:
        print("\nすべて最新です")


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

    docs_dir = input("Markdown ファイルを置くディレクトリ（空欄で docs/）: ").strip() or "docs/"
    pattern = input("同期する Markdown のファイルパターン（空欄で *.md）: ").strip() or "*.md"

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
        "elabftw": {"url": url, "api_key": "", "verify_ssl": verify_ssl},
        "targets": [target],
    }

    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    # テンプレートファイルのコピー
    print("\nテンプレートファイルを展開中...")
    _copy_template_files(docs_dir)

    print(f"\n✅ 設定ファイルを作成しました: {config_path}")
    print(
        "\n次に、eLabFTW の API キーを設定してください:\n"
        f"  {config_path} の elabftw.api_key にキーを記入するか、\n"
        "  環境変数 ELABFTW_API_KEY を設定してください（環境変数が優先されます）。\n"
        "\n準備ができたら以下で同期を開始できます:\n"
        "  uv run elab-doc-sync --dry-run  （確認）\n"
        "  uv run elab-doc-sync            （実行）"
    )


REPO_URL = "git+https://github.com/Kosaku-Noba/elab-doc-sync.git"


def cmd_update(args):
    """ツール自体を最新版に更新する。"""
    import subprocess
    print("elab-doc-sync を最新版に更新しています...")
    # uv が使えるか試す → だめなら pip
    for installer in (["uv", "pip", "install", "--upgrade"], ["pip", "install", "--upgrade"]):
        try:
            subprocess.run([*installer, REPO_URL], check=True)
            print("\n✅ 更新が完了しました")
            return
        except FileNotFoundError:
            continue
    print("エラー: uv も pip も見つかりません", file=sys.stderr)
    sys.exit(1)


HELP_EPILOG = """\
使用例:
  elab-doc-sync                  ローカル → eLabFTW に同期（push）
  elab-doc-sync pull             eLabFTW → ローカルに取得
  elab-doc-sync pull --id 42     指定 ID のエンティティを取得
  elab-doc-sync diff             ローカルと eLabFTW の差分を表示
  elab-doc-sync status           同期状態を確認
  elab-doc-sync init             対話的に設定ファイルを作成
  elab-doc-sync update           ツールを最新版に更新
  elab-doc-sync --dry-run        実行せずに同期内容を確認
  elab-doc-sync --force          変更がなくても強制同期
  elab-doc-sync -t "名前"        特定のターゲットだけ同期
"""


def main():
    parser = argparse.ArgumentParser(
        prog=Path(sys.argv[0]).stem if Path(sys.argv[0]).stem in ("esync", "elab-doc-sync") else "elab-doc-sync",
        description="Markdown ドキュメントを eLabFTW に同期する CLI ツール",
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", "-c", default=DEFAULT_CONFIG, help="設定ファイルのパス（デフォルト: .elab-sync.yaml）")
    parser.add_argument("--target", "-t", default=None, help="同期するターゲット名（指定しない場合は全ターゲット）")
    parser.add_argument("--force", "-f", action="store_true", help="変更がなくても強制同期 / pull 時は既存ファイルを上書き")
    parser.add_argument("--dry-run", "-n", action="store_true", help="実行せずに同期内容を確認")

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status", help="同期状態を確認")
    sub.add_parser("init", help="対話的に設定ファイルを作成")
    sub.add_parser("diff", help="ローカルと eLabFTW の差分を表示")
    sub.add_parser("update", help="ツールを最新版に更新")

    pull_parser = sub.add_parser("pull", help="eLabFTW からエンティティを取得してローカルに保存")
    pull_parser.add_argument("--id", type=int, default=None, help="取得するエンティティの ID")

    args = parser.parse_args()
    if args.command == "status":
        cmd_status(args)
    elif args.command == "init":
        cmd_init(args)
    elif args.command == "pull":
        cmd_pull(args)
    elif args.command == "diff":
        cmd_diff(args)
    elif args.command == "update":
        cmd_update(args)
    else:
        cmd_sync(args)
