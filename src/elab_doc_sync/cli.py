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
from .config import load_config, BODY_FORMAT_INIT, _read_yaml_text
from .sync import DocsSyncer, EachDocsSyncer, ConflictError, _download_images, _normalize_remote_image_urls, _download_attachments, _count_local_attachments
from . import sync_log

DEFAULT_CONFIG = ".elab-sync.yaml"

# html_to_md 共通オプション: エスケープを抑制してラウンドトリップを安定させる
# 適用先: pull, diff, clone, new（HTML→Markdown 変換の全経路）
# 方針: 本ツール経由の push→pull ラウンドトリップの安定性を優先する。
# Web UI 等で直接作成された HTML 内のリテラルな * や _ は、pull 後に
# Markdown の強調記法として解釈される可能性がある（許容する仕様）。
_MD_OPTS = {"heading_style": "ATX", "escape_asterisks": False, "escape_underscores": False}

# eLabFTW の Web UI では items を「リソース」と表示するため、CLI でも resources を受け付ける
_ENTITY_ALIASES = {"resources": "items", "resource": "items"}


def _normalize_entity(value: str) -> str:
    """CLI 入力の entity 値を API 用に正規化する。"""
    return _ENTITY_ALIASES.get(value, value)


def _entity_label(entity_type: str) -> str:
    """API の entity 種別をユーザー向け表示名に変換する。"""
    return "実験ノート" if entity_type == "experiments" else "リソース"


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
            entity_label = "実験ノート" if target.entity == "experiments" else "リソース"
            att_dir = (project_root / target.attachments_dir) if target.attachments_dir else None
            att_count = _count_local_attachments(att_dir)
            att_str = f"  添付: {att_count}件" if att_count else ""
            if isinstance(syncer, EachDocsSyncer):
                results = syncer.dry_run()
                if not results:
                    print(f"  [each: {target.docs_dir}] ドキュメントなし")
                    continue
                for r in results:
                    status = "変更あり" if r["changed"] else "変更なし（スキップ）"
                    dest = f"{entity_label} #{r['entity_id']}" if r["entity_id"] else f"新しい{entity_label}"
                    print(f"  [{r['title']}] {status}")
                    print(f"    画像: {r['images']}件{att_str}  → {dest}")
            else:
                info = syncer.dry_run()
                if not info["files"]:
                    print(f"  [{target.title}] ドキュメントなし")
                    continue
                status = "変更あり" if info["changed"] else "変更なし（スキップ）"
                dest = f"{entity_label} #{info['item_id']}" if info["item_id"] else f"新しい{entity_label}"
                print(f"  [{target.title}] {status}")
                print(f"    ファイル: {info['files']}件  画像: {info['images']}件{att_str}  → {dest}")
            continue

        try:
            if isinstance(syncer, EachDocsSyncer):
                updated += syncer.sync(force=args.force)
            else:
                if syncer.sync(force=args.force):
                    updated += 1
        except ConflictError as e:
            print(f"  ⚠ 競合検出: {e}", file=sys.stderr)
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
        entity_label = "実験ノート" if target.entity == "experiments" else "リソース"

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


def _ensure_target_in_config(config_path: Path, entity: str, config: "Config"):
    """--id pull 時に該当 entity のターゲットが yaml に無ければ自動追加する。"""
    entity = _normalize_entity(entity)
    if any(t.entity == entity for t in config.targets):
        return config

    docs_dir = f"{entity}/"
    id_file = f".elab-sync-ids/{entity}.id"
    new_target = {"docs_dir": docs_dir, "pattern": "*.md", "mode": "each",
                  "entity": entity, "title": "", "id_file": id_file}

    # yaml ファイルに追記
    raw = yaml.safe_load(_read_yaml_text(config_path)) or {}
    raw.setdefault("targets", []).append(new_target)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(raw, f, default_flow_style=False, allow_unicode=True)

    label = _entity_label(entity)
    print(f"  ℹ {label}用ターゲットを .elab-sync.yaml に追加しました（docs_dir: {docs_dir}）")

    # config を再読み込み
    return load_config(config_path)


def cmd_pull(args):
    """eLabFTW からエンティティを取得してローカルに Markdown として保存する。"""
    if args.id and not getattr(args, "entity", None):
        print("エラー: --id 指定時は --entity も指定してください（items / experiments）", file=sys.stderr)
        sys.exit(1)

    config_path = Path(args.config)
    project_root = config_path.parent or Path(".")
    config = load_config(config_path)

    # --id 指定時に該当 entity のターゲットが無ければ yaml に自動追加
    if args.id and args.entity:
        config = _ensure_target_in_config(config_path, args.entity, config)

    client = ELabFTWClient(config.url, config.api_key, config.verify_ssl)

    pulled = 0
    targets = config.targets
    # --id + --entity 指定時: mapping から ID が紐付いているターゲットを自動解決
    # 見つからなければ該当 entity の最初のターゲットにフォールバック
    if args.id and args.entity:
        entity_norm = _normalize_entity(args.entity)
        matched = [t for t in targets if t.entity == entity_norm]
        if args.target:
            matched = [t for t in matched if t.title == args.target]
        elif len(matched) > 1:
            # mapping から ID が既に紐付いているターゲットを探す
            id_set = set(args.id)
            resolved = []
            for t in matched:
                if t.mode == "each":
                    syncer = EachDocsSyncer(client, t, project_root)
                    mapping = syncer._load_mapping()
                    if id_set & set(mapping.values()):
                        resolved.append(t)
            matched = resolved if resolved else matched[:1]
        targets = matched

    for target in targets:
        if args.target and target.title != args.target:
            continue

        docs_dir = project_root / target.docs_dir
        docs_dir.mkdir(parents=True, exist_ok=True)
        entity_label = "実験ノート" if target.entity == "experiments" else "リソース"
        # --entity が指定されていれば上書き
        entity_type = _normalize_entity(getattr(args, "entity", None) or target.entity)
        get_fn = client.get_experiment if entity_type == "experiments" else client.get_item
        list_fn = client.list_experiments if entity_type == "experiments" else client.list_items
        entity_label = "実験ノート" if entity_type == "experiments" else "リソース"

        if target.mode == "each":
            syncer = EachDocsSyncer(client, target, project_root)
            mapping = syncer._load_mapping()

            if args.id:
                # 指定 ID を pull
                entities = set(args.id)
            elif mapping:
                # 既存 mapping の ID を pull（再同期）
                entities = set(mapping.values())
            else:
                print(f"  [{target.docs_dir}] --id を指定してください（初回 pull には ID が必要です）")
                continue

            for eid in entities:
                try:
                    data = get_fn(eid)
                except Exception as e:
                    print(f"  {entity_label} #{eid} の取得に失敗: {e}", file=sys.stderr)
                    continue

                title = data.get("title", f"untitled_{eid}")
                body_html = data.get("body", "") or ""
                body_md = html_to_md(body_html, **_MD_OPTS).strip()
                body_md = _download_images(body_md, entity_type, eid, client, docs_dir)

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
                # リモート body のハッシュを保存（競合検出用）
                syncer._save_remote_hash(filename, body_html)

                print(f"  [{title}] {entity_label} #{eid} → {filepath}")
                pulled += 1

                if target.attachments_dir:
                    _download_attachments(entity_type, eid, client, project_root / target.attachments_dir)

                log_path = project_root / sync_log.DEFAULT_LOG_PATH
                sync_log.record(log_path, action="pull", target=title,
                                entity=entity_type, entity_id=eid, files=[filename])

        else:
            # merge モード: 1 エンティティ → 1 ファイル
            syncer = DocsSyncer(client, target, project_root)
            eid = syncer.read_item_id()

            if args.id:
                if len(args.id) > 1:
                    print(f"  [{target.title}] ⚠ merge モードでは最初の ID のみ使用します（{args.id[0]}）")
                eid = args.id[0]

            if eid is None:
                print(f"  [{target.title}] 同期先の ID が不明です（--id で指定してください）")
                continue

            try:
                data = get_fn(eid)
            except Exception as e:
                print(f"  [{target.title}] {entity_label} #{eid} の取得に失敗: {e}", file=sys.stderr)
                continue

            body_html = data.get("body", "") or ""
            body_md = html_to_md(body_html, **_MD_OPTS).strip()
            body_md = _download_images(body_md, entity_type, eid, client, docs_dir)

            filename = f"{target.title or 'pulled'}.md"
            filepath = docs_dir / filename

            if not args.force and filepath.exists():
                print(f"  [{target.title}] 既にローカルに存在（スキップ、--force で上書き）")
                continue

            filepath.write_text(body_md + "\n", encoding="utf-8")

            # ID とハッシュを保存
            syncer.save_item_id(eid)
            syncer.save_hash(body_md)
            # リモート body のハッシュを保存（競合検出用）
            syncer.save_remote_hash(body_html)

            print(f"  [{target.title}] {entity_label} #{eid} → {filepath}")
            pulled += 1

            if target.attachments_dir:
                _download_attachments(entity_type, eid, client, project_root / target.attachments_dir)

            log_path = project_root / sync_log.DEFAULT_LOG_PATH
            sync_log.record(log_path, action="pull", target=target.title,
                            entity=entity_type, entity_id=eid, files=[filename])

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
                remote_md = html_to_md(data.get("body", "") or "", **_MD_OPTS).strip()
                remote_md = _normalize_remote_image_urls(remote_md, target.entity, eid, client)

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

            remote_md = html_to_md(data.get("body", "") or "", **_MD_OPTS).strip()
            remote_md = _normalize_remote_image_urls(remote_md, target.entity, eid, client)

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
    entity_input = input("送信先 — items(resources): リソース / experiments: 実験ノート [items]: ").strip().lower() or "items"
    entity_input = _normalize_entity(entity_input)

    fmt_input = input(f"送信形式 — md: Markdown のまま / html: HTML に変換 [{BODY_FORMAT_INIT}]: ").strip().lower() or BODY_FORMAT_INIT

    target = {"docs_dir": docs_dir, "pattern": pattern, "mode": mode_input, "entity": entity_input, "body_format": fmt_input}

    if mode_input == "merge":
        title = ""
        while not title:
            title = input("eLabFTW リソースのタイトル: ").strip()
        target["title"] = title
    else:
        target["title"] = ""

    data = {
        "elabftw": {"url": url, "api_key": "", "verify_ssl": verify_ssl},
        "targets": [target],
    }

    with open(config_path, "w", encoding="utf-8") as f:
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


def cmd_clone(args):
    """リモートの eLabFTW エンティティからローカルプロジェクトを構築する。"""
    import os as _os

    url = args.url.rstrip("/")
    api_key = _os.environ.get("ELABFTW_API_KEY", "").strip()
    if not api_key:
        print("エラー: 環境変数 ELABFTW_API_KEY を設定してください", file=sys.stderr)
        sys.exit(1)

    entity = args.entity
    ids = args.id
    project_dir = Path(args.dir or f"elab-clone-{ids[0]}")
    docs_dir = "docs/"

    # 既存ディレクトリへの上書き防止
    dir_created = False
    if project_dir.exists() and any(project_dir.iterdir()):
        print(f"エラー: {project_dir} は既に存在し、空ではありません", file=sys.stderr)
        sys.exit(1)
    if not project_dir.exists():
        dir_created = True

    print(f"=== esync clone: {url} ===\n")

    client = ELabFTWClient(url, api_key, verify_ssl=not args.no_verify)
    get_fn = client.get_experiment if entity == "experiments" else client.get_item

    # プロジェクトディレクトリ作成
    project_dir.mkdir(parents=True, exist_ok=True)
    docs_path = project_dir / docs_dir
    docs_path.mkdir(parents=True, exist_ok=True)

    # .elab-sync.yaml 生成
    config_data = {
        "elabftw": {"url": url, "api_key": "", "verify_ssl": not args.no_verify},
        "targets": [{"docs_dir": docs_dir, "pattern": "*.md", "mode": "each", "entity": entity, "title": ""}],
    }
    config_path = project_dir / ".elab-sync.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)
    print(f"  {config_path} を作成しました")

    # エンティティ取得・保存
    target = __import__("elab_doc_sync.config", fromlist=["TargetConfig"]).TargetConfig(
        title="", docs_dir=docs_dir, id_file=".elab-sync-ids/default.id",
        pattern="*.md", mode="each", entity=entity,
    )
    syncer = EachDocsSyncer(client, target, project_dir)
    mapping = {}
    entity_label = "実験ノート" if entity == "experiments" else "リソース"
    cloned = 0

    for eid in ids:
        try:
            data = get_fn(eid)
        except Exception as e:
            print(f"  {entity_label} #{eid} の取得に失敗: {e}", file=sys.stderr)
            continue

        title = data.get("title", f"untitled_{eid}")
        body_html = data.get("body", "") or ""
        body_md = html_to_md(body_html, **_MD_OPTS).strip()
        body_md = _download_images(body_md, entity, eid, client, docs_path)

        filename = f"{title}.md"
        filepath = docs_path / filename
        filepath.write_text(body_md + "\n", encoding="utf-8")

        mapping[filename] = eid
        syncer._save_hash(filename, body_md)
        syncer._save_remote_hash(filename, body_html)
        cloned += 1

        print(f"  [{title}] {entity_label} #{eid} → {filepath}")

        # 非画像添付ファイルのダウンロード
        _download_attachments(entity, eid, client, project_dir / "attachments")

    if cloned == 0:
        # clone が作成したディレクトリのみ削除（既存ディレクトリは残す）
        if dir_created:
            shutil.rmtree(project_dir, ignore_errors=True)
        else:
            # clone が生成したファイルだけ削除
            for p in [config_path, project_dir / ".gitignore"]:
                p.unlink(missing_ok=True)
            shutil.rmtree(docs_path, ignore_errors=True)
            shutil.rmtree(project_dir / ".elab-sync-ids", ignore_errors=True)
        print("\nエラー: エンティティを1件も取得できませんでした", file=sys.stderr)
        sys.exit(1)

    syncer._save_mapping(mapping)

    # .gitignore（API キーを含む設定ファイルも除外）
    gitignore = project_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(".elab-sync-ids/\n.elab-sync.yaml\n")

    print(f"\n✅ プロジェクトを作成しました: {project_dir}/ ({cloned} 件)")
    print(f"   API キーを設定してください:")
    print(f"     環境変数: export ELABFTW_API_KEY=\"your_key\"")
    print(f"     または {config_path} の elabftw.api_key に記入")


REPO_URL = "git+https://github.com/Kosaku-Noba/elab-doc-sync.git"


def cmd_log(args):
    """同期ログを表示する。"""
    config_path = Path(args.config)
    project_root = config_path.parent or Path(".")
    log_path = project_root / sync_log.DEFAULT_LOG_PATH
    entries = sync_log.read_log(log_path, limit=args.limit)
    print(sync_log.format_log(entries))


def cmd_update(args):
    """ツール自体を最新版に更新する。"""
    import subprocess
    print("elab-doc-sync を最新版に更新しています...")
    try:
        subprocess.run(["uv", "pip", "install", "--upgrade", REPO_URL], check=True)
        print("\n✅ 更新が完了しました")
    except FileNotFoundError:
        print("エラー: uv が見つかりません。https://docs.astral.sh/uv/ からインストールしてください", file=sys.stderr)
        sys.exit(1)


HELP_EPILOG = """\
使用例:
  elab-doc-sync                  ローカル → eLabFTW に同期（push）
  elab-doc-sync pull             eLabFTW → ローカルに取得
  elab-doc-sync pull --id 42     指定 ID のエンティティを取得
  elab-doc-sync diff             ローカルと eLabFTW の差分を表示
  elab-doc-sync status           同期状態を確認
  elab-doc-sync tag list         リモートのタグ一覧を表示
  elab-doc-sync tag add "タグ"   タグを追加
  elab-doc-sync tag remove "タグ" タグを外す
  elab-doc-sync metadata get     メタデータを表示
  elab-doc-sync metadata set k=v メタデータを設定
  elab-doc-sync entity-status show ステータスを表示
  elab-doc-sync entity-status set 1 ステータスを変更
  elab-doc-sync category list    カテゴリ一覧を表示
  elab-doc-sync category show --id 42 --entity items 現在のカテゴリを表示
  elab-doc-sync category set "名前" --id 42 --entity items カテゴリを設定
  elab-doc-sync whoami           現在のユーザー情報を表示
  elab-doc-sync new --list       テンプレート一覧を表示
  elab-doc-sync new --template-id 1 テンプレートからファイル作成
  elab-doc-sync init             対話的に設定ファイルを作成
  elab-doc-sync update           ツールを最新版に更新
"""


def _get_entity_ids(client, syncer, target, args_id=None):
    """ターゲットに紐づくエンティティ ID のリストを返す。"""
    if args_id:
        return [(args_id, target.entity)]
    if target.mode == "each":
        mapping = syncer._load_mapping()
        return [(eid, target.entity) for eid in mapping.values()] if mapping else []
    eid = syncer.read_item_id()
    return [(eid, target.entity)] if eid else []


def cmd_tag(args):
    config_path = Path(args.config)
    project_root = config_path.parent or Path(".")
    config = load_config(config_path)
    client = ELabFTWClient(config.url, config.api_key, config.verify_ssl)

    # --id と --entity が指定されたら直接操作
    direct_id = getattr(args, "id", None)
    direct_entity = getattr(args, "entity", None)
    if direct_entity and not direct_id:
        print("エラー: --entity 指定時は --id も指定してください", file=sys.stderr)
        sys.exit(1)
    if direct_id and not direct_entity:
        print("エラー: --id 指定時は --entity も指定してください（items / experiments / resources）", file=sys.stderr)
        sys.exit(1)
    if direct_id and direct_entity:
        entity_type = _normalize_entity(direct_entity)
        _tag_action(client, args, entity_type, direct_id)
        return

    for target in config.targets:
        if args.target and target.title != args.target:
            continue
        syncer = _make_syncer(client, target, project_root)
        ids = _get_entity_ids(client, syncer, target, direct_id)
        if not ids:
            print(f"  [{target.title or target.docs_dir}] 同期済みエンティティなし")
            continue

        for eid, etype in ids:
            _tag_action(client, args, etype, eid)


def _tag_action(client, args, entity_type, entity_id):
    label = f"{_entity_label(entity_type)} #{entity_id}"
    if args.tag_action == "list":
        tags = client.get_tags(entity_type, entity_id)
        tag_names = [t.get("tag", "?") for t in tags]
        print(f"  {label}: {', '.join(tag_names) if tag_names else '(タグなし)'}")
    elif args.tag_action == "add":
        client.add_tag(entity_type, entity_id, args.tag_name)
        print(f"  {label}: タグ「{args.tag_name}」を追加しました")
    elif args.tag_action == "remove":
        if client.untag_by_name(entity_type, entity_id, args.tag_name):
            print(f"  {label}: タグ「{args.tag_name}」を外しました")
        else:
            print(f"  {label}: タグ「{args.tag_name}」が見つかりません")


def cmd_metadata(args):
    config_path = Path(args.config)
    project_root = config_path.parent or Path(".")
    config = load_config(config_path)
    client = ELabFTWClient(config.url, config.api_key, config.verify_ssl)

    for target in config.targets:
        if args.target and target.title != args.target:
            continue
        syncer = _make_syncer(client, target, project_root)
        ids = _get_entity_ids(client, syncer, target, getattr(args, "id", None))
        if not ids:
            print(f"  [{target.title or target.docs_dir}] 同期済みエンティティなし")
            continue

        for eid, etype in ids:
            label = f"{_entity_label(etype)} #{eid}"
            if args.meta_action == "get":
                meta = client.get_metadata(etype, eid)
                print(f"  {label}:")
                print(f"    {json.dumps(meta, ensure_ascii=False, indent=2)}")
            elif args.meta_action == "set":
                pairs = {}
                for kv in args.keyvalues:
                    if "=" not in kv:
                        print(f"エラー: '{kv}' は key=value 形式ではありません", file=sys.stderr)
                        sys.exit(1)
                    k, v = kv.split("=", 1)
                    pairs[k] = v
                raw = client.get_metadata_raw(etype, eid)
                existing = client.get_metadata(etype, eid)
                if raw and not existing:
                    print(f"  {label}: ⚠ 既存メタデータの読み取りに失敗しました（上書きされます）", file=sys.stderr)
                existing.update(pairs)
                client.update_metadata(etype, eid, existing)
                print(f"  {label}: メタデータを更新しました")


def cmd_whoami(args):
    """現在の API キーに紐づくユーザー情報を表示する。"""
    config_path = Path(args.config)
    config = load_config(config_path)
    client = ELabFTWClient(config.url, config.api_key, config.verify_ssl)
    user = client._req("GET", "/api/v2/users/me").json()
    print(f"  ユーザー: {user.get('firstname', '')} {user.get('lastname', '')}")
    print(f"  メール: {user.get('email', '不明')}")
    print(f"  ユーザーID: {user.get('userid', '不明')}")
    teams = user.get("teams", [])
    if teams:
        team_names = [t.get("name", "?") for t in teams]
        print(f"  チーム: {', '.join(team_names)}")


def cmd_new(args):
    """テンプレートから新規 Markdown ファイルを生成する。"""
    config_path = Path(args.config)
    project_root = config_path.parent or Path(".")
    config = load_config(config_path)
    client = ELabFTWClient(config.url, config.api_key, config.verify_ssl)

    if args.list_templates:
        templates = client._req("GET", "/api/v2/experiments_templates").json()
        if not templates:
            print("  テンプレートがありません")
            return
        for t in templates:
            print(f"  #{t.get('id', '?')}: {t.get('title', '無題')}")
        return

    if not args.template_id:
        print("エラー: --template-id を指定してください（一覧は esync new --list で確認）", file=sys.stderr)
        sys.exit(1)

    template = client._req("GET", f"/api/v2/experiments_templates/{args.template_id}").json()
    title = args.title or template.get("title", "untitled")
    body_html = template.get("body", "") or ""
    body_md = html_to_md(body_html, **_MD_OPTS).strip() if body_html else ""

    filename = "".join(c if c.isalnum() or c in "-_ " else "_" for c in title).replace(" ", "_") + ".md"
    if args.output:
        outpath = Path(args.output)
    else:
        # --target で指定されたターゲット、なければ最初のターゲットの docs_dir
        target = None
        if args.target:
            target = next((t for t in config.targets if t.title == args.target), None)
        if not target and config.targets:
            target = config.targets[0]
        if target:
            outpath = project_root / target.docs_dir / filename
        else:
            outpath = project_root / filename

    if outpath.exists() and not args.force:
        print(f"エラー: {outpath} は既に存在します（--force で上書き）", file=sys.stderr)
        sys.exit(1)

    outpath.parent.mkdir(parents=True, exist_ok=True)
    outpath.write_text(f"# {title}\n\n{body_md}\n", encoding="utf-8")
    print(f"  ✅ {outpath} を作成しました（テンプレート #{args.template_id}: {template.get('title', '')}）")


def cmd_list(args):
    """リモートのリソース/実験ノート一覧を表示する。"""
    config_path = Path(args.config)
    config = load_config(config_path)
    client = ELabFTWClient(config.url, config.api_key, config.verify_ssl)
    entity_type = _normalize_entity(args.entity_type or "items")
    limit = args.limit or 20
    if entity_type == "items":
        entities = client._req("GET", "/api/v2/items", params={"limit": limit}).json()
    else:
        entities = client._req("GET", "/api/v2/experiments", params={"limit": limit}).json()
    label = "実験ノート" if entity_type == "experiments" else "リソース"
    if not entities:
        print(f"  {label}がありません")
        return
    for e in entities:
        title = e.get("title", "無題")
        eid = e.get("id", "?")
        status = e.get("status_title", "")
        suffix = f" [{status}]" if status else ""
        print(f"  #{eid}: {title}{suffix}")
    print(f"\n  {label} {len(entities)} 件表示（--limit で件数変更可）")


def cmd_link(args):
    """既存リモートエンティティとローカルファイルを手動で紐付ける。"""
    config_path = Path(args.config)
    project_root = config_path.parent or Path(".")
    config = load_config(config_path)
    client = ELabFTWClient(config.url, config.api_key, config.verify_ssl)

    target = None
    if args.target:
        target = next((t for t in config.targets if t.title == args.target), None)
        if not target:
            print(f"エラー: ターゲット '{args.target}' が見つかりません", file=sys.stderr)
            sys.exit(1)
    if not target:
        target = config.targets[0]

    syncer = _make_syncer(client, target, project_root)

    # リモートの body を取得して remote_hash を初期化（競合検出のベースライン）
    try:
        entity = client.get_entity(target.entity, args.entity_id)
        body_html = entity.get("body", "") or ""
    except Exception:
        body_html = ""

    if target.mode == "each":
        if not args.file:
            print("エラー: each モードでは --file を指定してください", file=sys.stderr)
            sys.exit(1)
        mapping = syncer._load_mapping() or {}
        mapping[args.file] = args.entity_id
        syncer._save_mapping(mapping)
        if body_html:
            syncer._save_remote_hash(args.file, body_html)
        print(f"  ✅ {args.file} → {_entity_label(target.entity)} #{args.entity_id} を紐付けました")
    else:
        syncer.save_item_id(args.entity_id)
        if body_html:
            syncer.save_remote_hash(body_html)
        print(f"  ✅ [{target.title}] → {_entity_label(target.entity)} #{args.entity_id} を紐付けました")


def cmd_verify(args):
    """ローカルとリモートの整合性をチェックする。"""
    config_path = Path(args.config)
    project_root = config_path.parent or Path(".")
    config = load_config(config_path)
    client = ELabFTWClient(config.url, config.api_key, config.verify_ssl)
    issues = 0

    for target in config.targets:
        if args.target and target.title != args.target:
            continue
        syncer = _make_syncer(client, target, project_root)

        if target.mode == "each":
            mapping = syncer._load_mapping() or {}
            if not mapping:
                print(f"  [{target.docs_dir}] マッピングなし（未同期）")
                continue
            for filename, eid in mapping.items():
                filepath = project_root / target.docs_dir / filename
                if not filepath.exists():
                    print(f"  ⚠ {filename}: ローカルファイルが見つかりません（リモート #{eid}）")
                    issues += 1
                else:
                    try:
                        client.get_entity(target.entity, eid)
                    except Exception:
                        print(f"  ⚠ {filename}: リモート #{eid} にアクセスできません")
                        issues += 1
                    else:
                        print(f"  ✓ {filename} ↔ #{eid}")
        else:
            eid = syncer.read_item_id()
            if not eid:
                print(f"  [{target.title}] 未同期")
                continue
            try:
                client.get_entity(target.entity, eid)
                print(f"  ✓ [{target.title}] ↔ #{eid}")
            except Exception:
                print(f"  ⚠ [{target.title}]: リモート #{eid} にアクセスできません")
                issues += 1

    if issues:
        print(f"\n  {issues} 件の問題が見つかりました")
    else:
        print(f"\n  ✅ 接続チェックに問題はありません（内容の一致は esync status で確認）")


def cmd_entity_status(args):
    """エンティティのステータスを表示または変更する。"""
    config_path = Path(args.config)
    project_root = config_path.parent or Path(".")
    config = load_config(config_path)
    client = ELabFTWClient(config.url, config.api_key, config.verify_ssl)

    all_ids = []
    for target in config.targets:
        if args.target and target.title != args.target:
            continue
        syncer = _make_syncer(client, target, project_root)
        target_id = getattr(args, "id", None)
        ids = _get_entity_ids(client, syncer, target, target_id)
        if not ids:
            print(f"  [{target.title or target.docs_dir}] 同期済みエンティティなし")
            continue
        all_ids.extend(ids)

    if not all_ids:
        return

    if args.status_action == "show":
        for eid, etype in all_ids:
            entity = client.get_entity(etype, eid)
            status_name = entity.get("status_title") or entity.get("status", {}).get("title", "不明")
            print(f"  {_entity_label(etype)} #{eid}: {status_name}")
    elif args.status_action == "set":
        if len(all_ids) > 1 and not getattr(args, "id", None):
            print(f"  対象: {len(all_ids)} 件のエンティティ")
            for eid, etype in all_ids:
                print(f"    - {_entity_label(etype)} #{eid}")
            answer = input("  全て変更しますか？ [y/N]: ").strip().lower()
            if answer != "y":
                print("  中断しました")
                return
        for eid, etype in all_ids:
            client.patch_entity(etype, eid, status=int(args.status_id))
            print(f"  {_entity_label(etype)} #{eid}: ステータスを変更しました")


def cmd_category(args):
    config_path = Path(args.config)
    config = load_config(config_path)
    client = ELabFTWClient(config.url, config.api_key, config.verify_ssl)
    project_root = config_path.parent or Path(".")

    direct_id = getattr(args, "id", None)
    direct_entity = getattr(args, "entity", None)

    action = args.cat_action

    if action == "list":
        entity_type = _normalize_entity(direct_entity) if direct_entity else "items"
        cats = client.list_categories(entity_type)
        for c in cats:
            print(f"  #{c['id']}  {c.get('title', '?')}")
        return

    entity_type = _normalize_entity(direct_entity)
    if action == "show":
        _category_show(client, entity_type, direct_id)
    elif action == "set":
        _category_set(client, entity_type, direct_id, args.category_value)


def _category_show(client, entity_type, entity_id):
    entity = client.get_entity(entity_type, entity_id)
    cat_id = entity.get("category")
    cat_title = entity.get("category_title")
    label = f"{_entity_label(entity_type)} #{entity_id}"
    if cat_title:
        print(f"  {label}: {cat_title} (#{cat_id})")
    elif cat_id:
        print(f"  {label}: #{cat_id}")
    else:
        print(f"  {label}: (カテゴリ未設定)")


def _category_set(client, entity_type, entity_id, category_value):
    label = f"{_entity_label(entity_type)} #{entity_id}"
    cat_id = client.resolve_category_id(entity_type, category_value)
    client.patch_entity(entity_type, entity_id, category=cat_id)
    print(f"  {label}: カテゴリを設定しました (#{cat_id})")


def main():
    # 共通オプション（全サブコマンドで使える）
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", "-c", default=DEFAULT_CONFIG, help="設定ファイルのパス（デフォルト: .elab-sync.yaml）")
    common.add_argument("--target", "-t", default=None, help="同期するターゲット名（指定しない場合は全ターゲット）")
    common.add_argument("--force", "-f", action="store_true", help="変更がなくても強制同期 / pull 時は既存ファイルを上書き")
    common.add_argument("--dry-run", "-n", action="store_true", help="実行せずに同期内容を確認")

    from importlib.metadata import version as _pkg_version
    try:
        _version = _pkg_version("elab-doc-sync")
    except Exception:
        _version = "unknown"

    parser = argparse.ArgumentParser(
        prog=Path(sys.argv[0]).stem if Path(sys.argv[0]).stem in ("esync", "elab-doc-sync") else "elab-doc-sync",
        description="Markdown ドキュメントを eLabFTW に同期する CLI ツール",
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[common],
    )
    parser.add_argument("--version", "-V", action="version", version=f"%(prog)s {_version}")

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("status", help="同期状態を確認", parents=[common])
    sub.add_parser("push", help="ローカル → eLabFTW に同期（esync と同じ）", parents=[common])
    sub.add_parser("init", help="対話的に設定ファイルを作成", parents=[common])
    sub.add_parser("diff", help="ローカルと eLabFTW の差分を表示", parents=[common])
    sub.add_parser("update", help="ツールを最新版に更新")

    pull_parser = sub.add_parser("pull", help="eLabFTW からエンティティを取得してローカルに保存", parents=[common])
    pull_parser.add_argument("--id", type=int, action="append", default=None, help="取得するエンティティ ID（複数指定可）")
    pull_parser.add_argument("--entity", default=None, choices=["items", "experiments", "resources"],
                             help="エンティティ種別（resources は items のエイリアス）")

    log_parser = sub.add_parser("log", help="同期ログを表示", parents=[common])
    log_parser.add_argument("--limit", "-l", type=int, default=20, help="表示件数（デフォルト: 20）")

    clone_parser = sub.add_parser("clone", help="eLabFTW からプロジェクトを構築", parents=[common])
    clone_parser.add_argument("--url", required=True, help="eLabFTW の URL")
    clone_parser.add_argument("--id", type=int, action="append", required=True, help="取得するエンティティ ID（複数指定可）")
    clone_parser.add_argument("--dir", default=None, help="プロジェクトディレクトリ名")
    clone_parser.add_argument("--entity", default="items", choices=["items", "experiments", "resources"], help="エンティティ種別")
    clone_parser.add_argument("--no-verify", action="store_true", help="SSL 検証を無効化")

    tag_parser = sub.add_parser("tag", help="タグを管理", parents=[common])
    tag_sub = tag_parser.add_subparsers(dest="tag_action")
    tag_list_p = tag_sub.add_parser("list", help="タグ一覧を表示")
    tag_list_p.add_argument("--id", type=int, default=None, help="エンティティ ID")
    tag_list_p.add_argument("--entity", default=None, choices=["items", "experiments", "resources"], help="items / experiments / resources")
    tag_add_p = tag_sub.add_parser("add", help="タグを追加")
    tag_add_p.add_argument("tag_name", help="追加するタグ名")
    tag_add_p.add_argument("--id", type=int, default=None, help="エンティティ ID")
    tag_add_p.add_argument("--entity", default=None, choices=["items", "experiments", "resources"], help="items / experiments / resources")
    tag_rm_p = tag_sub.add_parser("remove", help="タグを外す")
    tag_rm_p.add_argument("tag_name", help="外すタグ名")
    tag_rm_p.add_argument("--id", type=int, default=None, help="エンティティ ID")
    tag_rm_p.add_argument("--entity", default=None, choices=["items", "experiments", "resources"], help="items / experiments / resources")

    meta_parser = sub.add_parser("metadata", help="メタデータを管理", parents=[common])
    meta_sub = meta_parser.add_subparsers(dest="meta_action")
    meta_sub.add_parser("get", help="メタデータを表示")
    meta_set_p = meta_sub.add_parser("set", help="メタデータを設定")
    meta_set_p.add_argument("keyvalues", nargs="+", help="key=value ペア")
    meta_set_p.add_argument("--id", type=int, default=None, help="エンティティ ID")

    estatus_parser = sub.add_parser("entity-status", help="エンティティのステータスを管理", parents=[common])
    sub.add_parser("whoami", help="現在のユーザー情報を表示")

    cat_parser = sub.add_parser("category", help="カテゴリを管理", parents=[common])
    cat_sub = cat_parser.add_subparsers(dest="cat_action")
    cat_list_p = cat_sub.add_parser("list", help="カテゴリ一覧を表示")
    cat_list_p.add_argument("--entity", default=None, choices=["items", "experiments", "resources"], help="items / experiments / resources")
    cat_show_p = cat_sub.add_parser("show", help="現在のカテゴリを表示")
    cat_show_p.add_argument("--id", type=int, required=True, help="エンティティ ID")
    cat_show_p.add_argument("--entity", required=True, choices=["items", "experiments", "resources"], help="items / experiments / resources")
    cat_set_p = cat_sub.add_parser("set", help="カテゴリを設定")
    cat_set_p.add_argument("category_value", help="カテゴリ ID または名前")
    cat_set_p.add_argument("--id", type=int, required=True, help="エンティティ ID")
    cat_set_p.add_argument("--entity", required=True, choices=["items", "experiments", "resources"], help="items / experiments / resources")

    new_parser = sub.add_parser("new", help="テンプレートから新規ドキュメントを作成", parents=[common])
    new_parser.add_argument("--list", dest="list_templates", action="store_true", help="テンプレート一覧を表示")
    new_parser.add_argument("--template-id", type=int, default=None, help="テンプレート ID")
    new_parser.add_argument("--title", default=None, help="ファイルのタイトル（省略時はテンプレート名）")
    new_parser.add_argument("--output", "-o", default=None, help="出力ファイルパス")

    list_parser = sub.add_parser("list", help="リモートのリソース/実験ノート一覧を表示", parents=[common])
    list_parser.add_argument("--entity", dest="entity_type", default="items", choices=["items", "experiments", "resources"], help="エンティティ種別")
    list_parser.add_argument("--limit", type=int, default=20, help="表示件数（デフォルト: 20）")

    link_parser = sub.add_parser("link", help="既存リモートエンティティとローカルを紐付け", parents=[common])
    link_parser.add_argument("entity_id", type=int, help="リモートエンティティ ID")
    link_parser.add_argument("--file", default=None, help="紐付けるローカルファイル名（each モード時）")

    sub.add_parser("verify", help="ローカルとリモートの整合性チェック", parents=[common])

    estatus_sub = estatus_parser.add_subparsers(dest="status_action")
    estatus_sub.add_parser("show", help="現在のステータスを表示")
    estatus_set_p = estatus_sub.add_parser("set", help="ステータスを変更")
    estatus_set_p.add_argument("status_id", help="ステータス ID")
    estatus_set_p.add_argument("--id", type=int, default=None, help="対象エンティティ ID（省略時は全同期済みエンティティ）")

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
    elif args.command == "log":
        cmd_log(args)
    elif args.command == "clone":
        cmd_clone(args)
    elif args.command == "tag":
        cmd_tag(args)
    elif args.command == "metadata":
        cmd_metadata(args)
    elif args.command == "entity-status":
        cmd_entity_status(args)
    elif args.command == "category":
        cmd_category(args)
    elif args.command == "whoami":
        cmd_whoami(args)
    elif args.command == "new":
        cmd_new(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "link":
        cmd_link(args)
    elif args.command == "verify":
        cmd_verify(args)
    elif args.command in (None, "push"):
        cmd_sync(args)
    else:
        # argparse が未知コマンドを先に拒否するため通常は到達しない（防御的コード）
        parser.print_help()
        sys.exit(1)
