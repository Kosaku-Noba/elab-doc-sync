"""CLI entry point for elab-doc-sync."""

import argparse
import difflib
import glob
import re
import json
import shutil
import sys
from pathlib import Path

import yaml
from markdownify import markdownify as html_to_md

from .safety import atomic_write, write_json, safe_path, snapshot, local_transaction, project_command, restore, BACKUPS, RECOVERY
from .config import TargetConfig
from .client import ELabFTWClient
from .config import load_config, BODY_FORMAT_INIT, _read_yaml_text, update_target_in_yaml, get_client_for_target, append_target_to_yaml
from .sync import EachDocsSyncer, ConflictError, _download_images, _normalize_remote_image_urls, _download_attachments, _count_local_attachments, _rewrite_elab_links_to_local
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


def _matches_target(target, selector):
    return not selector or target.title == selector or target.docs_dir.rstrip("/\\") == selector.rstrip("/\\")


def _make_client_for_target(config, target):
    """ターゲットのプロファイルに基づいて ELabFTWClient を生成する。"""
    url, api_key, verify_ssl = get_client_for_target(config, target)
    return ELabFTWClient(url, api_key, verify_ssl)


def _make_syncer(client, target, project_root):
    return EachDocsSyncer(client, target, project_root)


def _score_target_match(target, remote_tags: list[str], remote_category: str | None, remote_title: str) -> float:
    """リモートエンティティとターゲットのマッチスコアを計算する。

    スコアリングルール:
    - title_pattern (glob) がマッチ: +10
    - category が一致: +10
    - タグの包含率: (一致タグ数 / ターゲットのタグ数) × 5
      ※ターゲットにタグ設定がない場合は加算なし
    """
    from fnmatch import fnmatch
    score = 0.0

    # title_pattern マッチ
    if target.title_pattern and remote_title:
        if fnmatch(remote_title, target.title_pattern):
            score += 10.0

    # カテゴリ一致
    if target.category and remote_category:
        cat_str = str(target.category)
        if cat_str == str(remote_category):
            score += 10.0

    # タグ包含率: ターゲットのタグがリモートにどれだけ含まれるか
    # タグ数が多いターゲットほどスコアが高くなる（特異性ボーナス）
    if target.tags and remote_tags:
        target_tags_set = set(target.tags)
        remote_tags_set = set(remote_tags)
        matched = target_tags_set & remote_tags_set
        if target_tags_set:
            inclusion_rate = len(matched) / len(target_tags_set)
            score += inclusion_rate * 5.0
            # 特異性ボーナス: マッチしたタグが多いほど加算（より特定的なルールを優先）
            score += len(matched) * 0.5

    return score


def _find_best_target(config, entity_type: str, remote_tags: list[str],
                      remote_category: str | None, remote_title: str,
                      exclude_entity_ids: set[int] | None = None):
    """リモートエンティティに最もマッチするターゲットを返す。

    Returns:
        (target, score) or (None, 0.0)
    """
    candidates = []
    for target in config.targets:
        if target.entity != entity_type:
            continue
        score = _score_target_match(target, remote_tags, remote_category, remote_title)
        candidates.append((target, score))

    if not candidates:
        return None, 0.0

    # スコア降順
    candidates.sort(key=lambda x: x[1], reverse=True)
    best_target, best_score = candidates[0]

    # 曖昧さチェック: 最高スコアが0の場合はマッチなし
    if best_score == 0.0:
        return None, 0.0

    # 差がない（同点）場合は曖昧
    if len(candidates) > 1 and candidates[1][1] > 0 and (best_score - candidates[1][1]) < 0.01:
        return None, -1.0  # -1 = 曖昧

    return best_target, best_score


def _resolve_pull_target_interactive(config, entity_type: str, remote_title: str) -> "TargetConfig | None":
    """対話的にターゲットを選択させる。非対話環境では None を返す。"""
    matched = [t for t in config.targets if t.entity == entity_type]
    if not matched:
        return None

    print(f"  [{remote_title}] ⚠ 振り分け先が不明:")
    for i, t in enumerate(matched, 1):
        print(f"    {i}. {t.docs_dir}")
    print(f"    {len(matched) + 1}. 新規ディレクトリを作成")

    try:
        choice = input("  選択: ").strip()
        idx = int(choice) - 1
        if 0 <= idx < len(matched):
            return matched[idx]
        elif idx == len(matched):
            return None  # 新規作成シグナル
        else:
            print("  無効な番号です。スキップします。")
            return "SKIP"
    except (ValueError, EOFError):
        return "SKIP"


def _is_entity_already_tracked(config, project_root: Path, entity_type: str, entity_id: int) -> str | None:
    """指定 entity_id が既にどこかの mapping に存在するか確認する。

    Returns:
        存在する場合は docs_dir を返す。なければ None。
    """
    for target in config.targets:
        if target.entity != entity_type:
            continue
        if target.mode != "each":
            continue
        mapping_file = (project_root / target.id_file).parent / "mapping.json"
        if mapping_file.exists():
            import json
            mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
            if entity_id in mapping.values():
                return target.docs_dir
    return None


def _find_target_by_mapping(config, project_root: Path, entity_type: str, entity_id: int):
    """mapping から entity_id が紐付いているターゲットを返す。なければ None。"""
    for target in config.targets:
        if target.entity != entity_type:
            continue
        mapping_file = (project_root / target.id_file).parent / "mapping.json"
        if mapping_file.exists():
            mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
            if entity_id in mapping.values():
                return target
    return None


@project_command
def cmd_sync(args):
    config_path = Path(args.config)
    project_root = config_path.parent or Path(".")
    config = load_config(config_path)

    updated = failed = skipped = 0
    for target in config.targets:
        if not _matches_target(target, args.target):
            continue
        client = _make_client_for_target(config, target)
        syncer = _make_syncer(client, target, project_root)

        if args.dry_run:
            entity_label = "実験ノート" if target.entity == "experiments" else "リソース"
            att_dir = (project_root / target.attachments_dir) if target.attachments_dir else None
            att_count = _count_local_attachments(att_dir)
            att_str = f"  添付: {att_count}件" if att_count else ""
            results = syncer.dry_run()
            if not results:
                print(f"  [each: {target.docs_dir}] ドキュメントなし")
                continue
            for r in results:
                status = "変更あり" if r["changed"] else "変更なし（スキップ）"
                dest = f"{entity_label} #{r['entity_id']}" if r["entity_id"] else f"新しい{entity_label}"
                video_str = f"  動画: {r['videos']}件" if r.get("videos") else ""
                flink_str = f"  リンクファイル: {r['file_links']}件" if r.get("file_links") else ""
                print(f"  [{r['title']}] {status}")
                print(f"    画像: {r['images']}件{video_str}{flink_str}{att_str}  → {dest}")
            continue

        try:
            updated += syncer.sync(force=args.force, prune_attachments=args.prune_attachments)
            failed += syncer.failures
            skipped += syncer.skipped
        except ConflictError as e:
            failed += 1
            print(f"  ⚠ 競合検出: {e}", file=sys.stderr)
        except Exception as e:
            failed += 1
            label = target.title or f"each: {target.docs_dir}"
            print(f"  [{label}] エラー: {e}", file=sys.stderr)
        if (project_root / RECOVERY).exists():
            break

    if not args.dry_run:
        print(f"\n完了: {updated} 件更新、{skipped} 件スキップ、{failed} 件失敗")
    return 1 if failed else 0


def cmd_status(args):
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    failed = False
    for target in config.targets:
        if not _matches_target(target, args.target):
            continue
        syncer = _make_syncer(_make_client_for_target(config, target), target, config_path.parent)
        mapping = syncer._load_mapping(migrate=False)
        names = (set(mapping) | set(syncer._pending()) | {f.name for f in syncer.collect_files()}) - syncer._load_excluded()
        for name in sorted(names):
            result = syncer.inspect(name, mapping.get(name))
            pending = syncer._pending().get(name)
            state = ("作成結果不明" if not pending.get("eid") else "同期未完了") if pending else result["state"]
            print(f"  [{name}] {state}（#{mapping.get(name, '未作成')}）")
            if result.get("error"):
                print(f"    {result['error']}")
            failed |= state in ("競合", "確認失敗", "リモート削除", "作成結果不明", "同期未完了")
    if (config_path.parent / RECOVERY).exists():
        print("  未完了のローカル変更があります。backup list と restore で復旧してください")
        failed = True
    return int(failed)


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
    atomic_write(config_path, yaml.dump(raw, default_flow_style=False, allow_unicode=True))

    label = _entity_label(entity)
    print(f"  ℹ {label}用ターゲットを .elab-sync.yaml に追加しました（docs_dir: {docs_dir}）")

    # config を再読み込み
    return load_config(config_path)


def _sync_remote_metadata_to_yaml(client, config, config_path, target, entity_type, mapping):
    """pull 後にリモートのタグ・カテゴリを YAML に書き戻す。best-effort。"""
    if not mapping:
        return
    try:
        target_index = config.targets.index(target)
    except ValueError:
        return

    # 全エンティティのタグを集約（重複排除）
    all_tags = set()
    category_name = None
    for eid in mapping.values():
        try:
            remote_tags = client.get_tags(entity_type, eid)
            all_tags.update(
                (t.get("tag") if isinstance(t, dict) else str(t))
                for t in remote_tags
                if (t.get("tag") if isinstance(t, dict) else t)
            )
        except Exception:
            pass
        try:
            entity_data = client.get_entity(entity_type, eid)
            cat_id = entity_data.get("category")
            if cat_id and category_name is None:
                category_name = client.resolve_category_name(entity_type, cat_id)
        except Exception:
            pass

    updates = {}
    new_tags = sorted(all_tags)
    if new_tags != sorted(target.tags or []):
        updates["tags"] = new_tags
    if category_name is not None and category_name != target.category:
        updates["category"] = category_name
    elif category_name is None and target.category is not None:
        updates["category"] = None

    if updates:
        try:
            update_target_in_yaml(config_path, target_index, **updates)
        except Exception:
            return
        for k, v in updates.items():
            if k == "tags":
                print(f"    YAML 更新: tags → {v}")
            elif k == "category":
                print(f"    YAML 更新: category → {v or '(なし)'}")


@project_command
def cmd_pull(args):
    """Fetch remote changes without replacing unsynchronized local edits."""
    if args.id and not getattr(args, "entity", None):
        print("エラー: --id 指定時は --entity も指定してください", file=sys.stderr)
        raise SystemExit(2)
    config_path = Path(args.config).resolve()
    root = config_path.parent
    config = load_config(config_path)
    dry_run = getattr(args, "dry_run", False)
    targets = [t for t in config.targets if _matches_target(t, args.target)]
    if not targets:
        raise ValueError(f"ターゲットが見つかりません: {args.target}")
    export = Path(args.dir) if getattr(args, "dir", None) else None
    pulled = skipped = failed = 0
    jobs = []
    if args.id:
        entity = _normalize_entity(args.entity)
        candidates = [t for t in targets if t.entity == entity]
        for eid in args.id:
            tracked = [t for t in candidates if eid in EachDocsSyncer(None, t, root)._load_mapping(migrate=False).values()]
            if len(tracked) > 1:
                raise ValueError(f"#{eid} が複数接続先で追跡されています。--target を指定してください")
            target = tracked[0] if tracked else None
            source = target or (candidates[0] if len(candidates) == 1 else None)
            if source is None and len({get_client_for_target(config, t) for t in candidates}) > 1:
                raise ValueError("複数の接続先があります。--target を指定してください")
            client = _make_client_for_target(config, source) if source else ELabFTWClient(config.url, config.api_key, config.verify_ssl)
            try:
                data = client.get_experiment(eid) if entity == "experiments" else client.get_item(eid)
                if export:
                    target = _find_target_by_dir(config, entity, root, export) or target or source
                if target is None:
                    if len(candidates) == 1:
                        target = candidates[0]
                    elif candidates:
                        raw_tags = data.get("tags") or []
                        tags = raw_tags.split("|") if isinstance(raw_tags, str) else [t.get("tag", "") if isinstance(t, dict) else t for t in raw_tags]
                        target, score = _find_best_target(config, entity, tags, data.get("category_title") or data.get("category"), data.get("title", ""))
                        if target is None:
                            if getattr(args, "auto", False):
                                target = max(candidates, key=lambda t: _score_target_match(t, tags, data.get("category_title") or data.get("category"), data.get("title", "")))
                            elif dry_run:
                                print(f"  #{eid}: 保存先の選択が必要です（--target または --auto）")
                                skipped += 1
                                continue
                            else:
                                target = _resolve_pull_target_interactive(config, entity, data.get("title", ""))
                                if target == "SKIP":
                                    skipped += 1
                                    continue
                if target is None:
                    raw_tags = data.get("tags") or []
                    tags = raw_tags.split("|") if isinstance(raw_tags, str) else [t.get("tag", "") if isinstance(t, dict) else t for t in raw_tags]
                    category = data.get("category_title") or data.get("category")
                    folder = str(export) if export else (str(category or (tags[0] if tags else entity)).replace("/", "_").replace("\\", "_") + "/")
                    safe_path(root, folder)
                    target = TargetConfig(title="", docs_dir=folder, id_file=f".elab-sync-ids/{folder.rstrip('/')}/default.id", entity=entity, tags=tags, category=category)
                    if not dry_run:
                        from dataclasses import asdict
                        append_target_to_yaml(config_path, asdict(target))
                        config.targets.append(target)
                    print(f"  新規ターゲット{'予定' if dry_run else '追加'}: {folder}")
                # Never reuse data fetched with another target's credentials.
                if source is not None and get_client_for_target(config, source) != get_client_for_target(config, target):
                    client = _make_client_for_target(config, target)
                    data = client.get_experiment(eid) if entity == "experiments" else client.get_item(eid)
                jobs.append((client, target, eid, data))
            except Exception as exc:
                print(f"  #{eid} の取得に失敗: {exc}", file=sys.stderr)
                failed += 1
    else:
        for target in targets:
            client = _make_client_for_target(config, target)
            syncer = EachDocsSyncer(client, target, root)
            mapping = syncer._load_mapping(migrate=False)
            for name, eid in mapping.items():
                if name in syncer._load_excluded():
                    continue
                try:
                    jobs.append((client, target, eid, syncer._get_entity(eid)))
                except Exception as exc:
                    print(f"  #{eid} の取得に失敗: {exc}", file=sys.stderr)
                    failed += 1
    for client, target, eid, data in jobs:
        try:
            result = _pull_entity_to_target(client, config, config_path, target, root, eid, data, target.entity,
                                            args.force, export, dry_run=dry_run)
            pulled += result
            skipped += int(result == 0)
        except Exception as exc:
            print(f"  #{eid} の取得に失敗: {exc}", file=sys.stderr)
            failed += 1
            if (root / RECOVERY).exists():
                break
    print(f"\n{'確認' if dry_run else '完了'}: {pulled} 件取得{'予定' if dry_run else ''}、{skipped} 件スキップ、{failed} 件失敗")
    return 1 if failed else 0


def _find_target_by_dir(config, entity_type: str, project_root: Path, pull_dir: Path):
    """指定ディレクトリに一致するターゲットを探す。"""
    pull_dir_resolved = (project_root / pull_dir).resolve()
    for t in config.targets:
        if t.entity == entity_type and (project_root / t.docs_dir).resolve() == pull_dir_resolved:
            return t
    return None


def _find_or_create_target_for_pull(config, config_path, project_root, entity_type,
                                    docs_dir, remote_tags, remote_category, remote_title):
    """pull 先のターゲットを探し、なければ作成して YAML に追記する。"""
    # 既存ターゲットで docs_dir が一致するものがあれば使う
    for t in config.targets:
        if t.entity == entity_type and t.docs_dir == docs_dir:
            return t
    # 新規作成
    return _create_target_from_remote(
        config, config_path, project_root, entity_type,
        remote_tags, remote_category, remote_title, docs_dir_override=docs_dir)


def _create_target_from_remote(config, config_path, project_root, entity_type,
                               remote_tags, remote_category, remote_title,
                               docs_dir_override=None):
    """リモート情報から新しいターゲットを作成し YAML に追記する。"""
    if docs_dir_override:
        new_docs_dir = docs_dir_override
    else:
        # タイトルやカテゴリから適切なディレクトリ名を生成
        if remote_category:
            dir_name = str(remote_category).replace(" ", "_").replace("/", "_")
        elif remote_tags:
            dir_name = remote_tags[0].replace(" ", "_").replace("/", "_")
        else:
            dir_name = f"pulled_{entity_type}"
        new_docs_dir = f"{dir_name}/"

    # ディレクトリ作成
    (project_root / new_docs_dir).mkdir(parents=True, exist_ok=True)

    new_target = {
        "docs_dir": new_docs_dir,
        "pattern": "*.md",
        "mode": "each",
        "entity": entity_type,
        "title": "",
    }
    if remote_tags:
        new_target["tags"] = list(remote_tags)
    if remote_category:
        new_target["category"] = str(remote_category)

    append_target_to_yaml(config_path, new_target)
    print(f"  ℹ 新規ターゲットを追加: docs_dir={new_docs_dir}")

    # reload して新しいターゲットを返す
    new_config = load_config(config_path)
    for t in new_config.targets:
        if t.docs_dir == new_docs_dir and t.entity == entity_type:
            return t
    return new_config.targets[-1]


def _remote_markdown(data, target):
    body = data.get("body") or ""
    # API content_type: 1=HTML, 2=Markdown. Legacy responses use target configuration.
    content_type = data.get("content_type")
    is_md = str(content_type) == "2" or (content_type is None and target.body_format == "md")
    return body.strip() if is_md else html_to_md(body, **_MD_OPTS).strip()


def _pull_entity_to_target(client, config, config_path, target, project_root,
                           eid, data, entity_type, force, pull_dir_override, dry_run=False):
    docs_dir = project_root / (pull_dir_override or Path(target.docs_dir))
    is_temp_export = docs_dir.resolve() != (project_root / target.docs_dir).resolve()
    syncer = EachDocsSyncer(client, target, project_root)
    mapping = syncer._load_mapping(migrate=False)
    return _pull_each_entity(client, syncer, target, project_root, docs_dir, mapping,
                             {v: k for k, v in mapping.items()}, eid, data, entity_type,
                             force, is_temp_export, dry_run=dry_run)


def _pull_each_entity(client, syncer, target, project_root, docs_dir,
                      mapping, reverse_mapping, eid, data, entity_type,
                      force, is_temp_export, dry_run=False):
    title = data.get("title") or f"untitled_{eid}"
    if any(c in title for c in '/\\\x00<>:"|?*') or title in (".", ".."):
        raise ValueError(f"ファイル名にできないタイトルです: {title!r}")
    filename = f"{title}.md"
    old_name = reverse_mapping.get(eid) if not is_temp_export else None
    old_path = syncer.file_path(old_name) if old_name else None
    # Keep a tracked document's subdirectory when the remote title changes.
    parent = old_path.parent if old_path else docs_dir
    filepath = safe_path(parent, filename)
    if filename in mapping and mapping[filename] != eid and not is_temp_export:
        raise ConflictError(f"{filename} は別のIDに紐付いています")
    if old_path and old_path != filepath and filepath.exists():
        raise ConflictError(f"リネーム先 {filename} が既に存在するため変更をスキップします")
    uploads = client.list_uploads(entity_type, eid)
    if old_name and old_path.is_file():
        status = syncer.inspect(old_name, eid, data, uploads)
        state = status["state"]
        if state == "確認失敗":
            raise ConflictError(status.get("error", state))
        if not force:
            if state in ("競合", "基準情報なし"):
                raise ConflictError(f"{old_name}: {state}。esync diff で確認してください")
            if state == "送信待ち":
                print(f"  [{title}] ローカル編集を保持（送信待ち）")
                return 0
            if state == "最新" and old_path == filepath:
                print(f"  [{title}] 最新（スキップ）")
                return 0
    elif filepath.exists() and not force:
        raise ConflictError(f"{filename}: 既にローカルに存在、基準情報なし。--force の前に差分を確認してください")
    if dry_run:
        print(f"  [{title}] #{eid} → {filepath}（取得予定）")
        return 1
    paths = [docs_dir] if is_temp_export else syncer.backup_paths()
    if target.attachments_dir:
        paths.append(project_root / target.attachments_dir)
    with local_transaction(project_root, paths, f"pull:{entity_type}/{eid}"):
        docs_dir.mkdir(parents=True, exist_ok=True)
        body_md = _remote_markdown(data, target)
        body_md = _download_images(body_md, entity_type, eid, client, parent, strict=True)
        new_mapping = dict(mapping)
        if old_name:
            new_mapping.pop(old_name, None)
        new_mapping[filename] = eid
        body_md = _rewrite_elab_links_to_local(body_md, client.base_url, new_mapping, entity_type, target_docs_dir=target.docs_dir)
        if target.attachments_dir:
            _download_attachments(entity_type, eid, client, project_root / target.attachments_dir, strict=True)
        atomic_write(filepath, body_md + "\n")
        if old_path and old_path != filepath:
            old_path.unlink(missing_ok=True)
        if not is_temp_export:
            if old_name and old_name != filename:
                for suffix in syncer.SUFFIXES:
                    (syncer.hash_dir / f"{old_name}{suffix}").unlink(missing_ok=True)
            mapping.clear()
            mapping.update(new_mapping)
            reverse_mapping[eid] = filename
            syncer._save_mapping(mapping)
            syncer._save_baseline(filename, body_md, data, uploads)
            pending = syncer._pending()
            pending.pop(old_name or filename, None)
            syncer._save_pending(pending)
        sync_log.record(project_root / sync_log.DEFAULT_LOG_PATH, action="pull", target=title,
                        entity=entity_type, entity_id=eid, files=[filename])
    print(f"  [{title}] #{eid} → {filepath}")
    return 1


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

    has_diff = False
    failed = False
    for target in config.targets:
        if not _matches_target(target, args.target):
            continue

        client = _make_client_for_target(config, target)
        docs_dir = project_root / target.docs_dir
        get_fn = client.get_experiment if target.entity == "experiments" else client.get_item

        if target.mode == "each":
            syncer = EachDocsSyncer(client, target, project_root)
            mapping = syncer._load_mapping(migrate=False)

            for filename, eid in mapping.items():
                local_path = docs_dir / filename
                if not local_path.exists():
                    print(f"  [{filename}] ローカルにファイルなし（eLabFTW #{eid} のみ存在）\n")
                    has_diff = True
                    continue

                try:
                    data = get_fn(eid)
                except Exception as e:
                    failed = True
                    print(f"  [{filename}] eLabFTW #{eid} の取得に失敗: {e}\n", file=sys.stderr)
                    continue

                local_md = local_path.read_text(encoding="utf-8").strip()
                remote_md = _remote_markdown(data, target)
                remote_md = _normalize_remote_image_urls(remote_md, target.entity, eid, client)

                if _show_diff(filename, local_md, remote_md):
                    has_diff = True
                else:
                    print(f"  [{filename}] 差分なし")

    if not has_diff and not failed:
        print("\nすべて最新です")


    return int(failed)


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

    entity_input = input("送信先 — items(resources): リソース / experiments: 実験ノート [items]: ").strip().lower() or "items"
    entity_input = _normalize_entity(entity_input)

    fmt_input = input(f"送信形式 — md: Markdown のまま / html: HTML に変換 [{BODY_FORMAT_INIT}]: ").strip().lower() or BODY_FORMAT_INIT

    target = {"docs_dir": docs_dir, "pattern": pattern, "mode": "each", "entity": entity_input, "body_format": fmt_input, "title": ""}

    data = {
        "elabftw": {"url": url, "api_key": "", "verify_ssl": verify_ssl},
        "targets": [target],
    }

    atomic_write(config_path, yaml.dump(data, default_flow_style=False, allow_unicode=True))

    print("  Git管理対象外: .elab-sync.yaml, .elab-sync-ids/, .elab-sync-backups/, .elab-sync-operations/, .elab-sync-recovery.json")

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


@project_command
def cmd_clone(args):
    """リモートの eLabFTW エンティティからローカルプロジェクトを構築する。"""
    import os as _os

    url = args.url.rstrip("/")
    api_key = _os.environ.get("ELABFTW_API_KEY", "").strip()
    if not api_key:
        print("エラー: 環境変数 ELABFTW_API_KEY を設定してください", file=sys.stderr)
        sys.exit(1)

    entity = _normalize_entity(args.entity)
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

    if getattr(args, "dry_run", False):
        preview_target = TargetConfig(title="", docs_dir=docs_dir, id_file=".elab-sync-ids/default.id",
                                      entity=entity, attachments_dir="attachments")
        preview_syncer = EachDocsSyncer(client, preview_target, project_dir)
        failed = False
        for eid in ids:
            try:
                data = get_fn(eid)
                _pull_each_entity(client, preview_syncer, preview_target, project_dir.resolve(),
                                  (project_dir / docs_dir).resolve(), {}, {}, eid, data, entity,
                                  False, False, dry_run=True)
            except Exception as exc:
                failed = True
                print(f"  #{eid} の確認に失敗: {exc}", file=sys.stderr)
        return int(failed)

    # プロジェクトディレクトリ作成
    project_dir.mkdir(parents=True, exist_ok=True)
    docs_path = project_dir / docs_dir
    docs_path.mkdir(parents=True, exist_ok=True)

    # .elab-sync.yaml 生成
    config_data = {
        "elabftw": {"url": url, "api_key": "", "verify_ssl": not args.no_verify},
        "targets": [{"docs_dir": docs_dir, "pattern": "*.md", "mode": "each", "entity": entity, "title": "", "id_file": ".elab-sync-ids/default.id", "attachments_dir": "attachments"}],
    }
    config_path = project_dir / ".elab-sync.yaml"
    atomic_write(config_path, yaml.dump(config_data, default_flow_style=False, allow_unicode=True))
    print(f"  {config_path} を作成しました")

    # エンティティ取得・保存
    target = __import__("elab_doc_sync.config", fromlist=["TargetConfig"]).TargetConfig(
        title="", docs_dir=docs_dir, id_file=".elab-sync-ids/default.id",
        pattern="*.md", mode="each", entity=entity, attachments_dir="attachments",
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

        try:
            cloned += _pull_each_entity(client, syncer, target, project_dir.resolve(), docs_path.resolve(),
                                        mapping, {v: k for k, v in mapping.items()}, eid, data, entity,
                                        False, False)
        except Exception as exc:
            print(f"  #{eid} の取得に失敗: {exc}", file=sys.stderr)
            if (project_dir / RECOVERY).exists():
                raise

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
        gitignore.write_text(".elab-sync-ids/\n.elab-sync.yaml\n.elab-sync-backups/\n.elab-sync-operations/\n.elab-sync-recovery.json\n")

    print(f"\n✅ プロジェクトを作成しました: {project_dir}/ ({cloned} 件)")
    print(f"   API キーを設定してください:")
    print(f"     環境変数: export ELABFTW_API_KEY=\"your_key\"")
    print(f"     または {config_path} の elabftw.api_key に記入")
    return 0 if cloned == len(ids) else 1


REPO_URL = "git+https://github.com/Kosaku-Noba/elab-doc-sync.git"


def cmd_log(args):
    """同期ログを表示する。"""
    config_path = Path(args.config)
    project_root = config_path.parent or Path(".")
    log_path = project_root / sync_log.DEFAULT_LOG_PATH
    entries = sync_log.read_log(log_path, limit=args.limit)
    print(sync_log.format_log(entries))


def _check_path_priority():
    """update 後に PATH 上の esync が .venv 内のものでないか確認する。

    .venv/Scripts/esync や .venv/bin/esync が PATH 上で優先されていると、
    uv tool でインストールした最新版ではなく .venv の古い版が実行される。
    """
    import subprocess
    try:
        if sys.platform == "win32":
            result = subprocess.run(["where", "esync"], capture_output=True, text=True)
        else:
            result = subprocess.run(["which", "esync"], capture_output=True, text=True)
        paths = [p.strip() for p in result.stdout.strip().splitlines() if p.strip()]
        if not paths:
            return

        resolved = Path(paths[0])
        parts_lower = [p.lower() for p in resolved.parts]
        if ".venv" in parts_lower or "venv" in parts_lower:
            print(f"\n⚠ 警告: PATH 上で .venv 内の esync が優先されています")
            print(f"  実行パス: {resolved}")
            print(f"  → .venv 内の古いバージョンが使われている可能性があります")
            print(f"")
            print(f"  解決方法:")
            print(f"    1. プロジェクトディレクトリで `uv sync` を実行して .venv をクリーンアップ")
            print(f"    2. または .venv/{'Scripts' if sys.platform == 'win32' else 'bin'}/esync を手動削除")
            print(f"    3. 新しいターミナルを開いて `esync --version` で確認")
    except Exception:
        pass


def cmd_update(args):
    """ツール自体を最新版に更新する。"""
    import subprocess
    print("elab-doc-sync を最新版に更新しています...")
    try:
        subprocess.run(["uv", "tool", "install", "--force", REPO_URL], check=True)
        # 更新後のバージョンを表示
        try:
            result = subprocess.run(
                ["uv", "tool", "run", "esync", "--version"],
                capture_output=True, text=True)
            ver = result.stdout.strip()
            print(f"\n✅ 更新が完了しました（{ver}）")
        except Exception:
            print("\n✅ 更新が完了しました")
    except FileNotFoundError:
        print("エラー: uv が見つかりません。https://docs.astral.sh/uv/ からインストールしてください", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError:
        print("⚠ 自動更新に失敗しました。手動で実行してください:", file=sys.stderr)
        print(f"  uv tool install --force {REPO_URL}", file=sys.stderr)
        sys.exit(1)

    # PATH 優先度チェック: .venv 内に esync が残っていると古いバージョンが優先される
    _check_path_priority()


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
        if not _matches_target(target, args.target):
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
        tag_names = [(t.get("tag", "?") if isinstance(t, dict) else str(t)) for t in tags]
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
        if not _matches_target(target, args.target):
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

    # プロファイルごとに表示
    profiles_to_show = list(config.profiles.values()) if config.profiles else []
    if not profiles_to_show:
        # プロファイル未定義の場合はデフォルト接続情報で表示
        profiles_to_show = [None]

    for profile in profiles_to_show:
        if profile:
            url, api_key, verify_ssl = profile.url, profile.api_key, profile.verify_ssl
            print(f"[profile: {profile.name}]")
        else:
            url, api_key, verify_ssl = config.url, config.api_key, config.verify_ssl
            print("[default]")

        client = ELabFTWClient(url, api_key, verify_ssl)
        try:
            user = client._req("GET", "/api/v2/users/me").json()
        except Exception as e:
            print(f"  エラー: API接続失敗 ({e})")
            print()
            continue

        print(f"  ユーザー: {user.get('firstname', '')} {user.get('lastname', '')}")
        print(f"  メール: {user.get('email', '不明')}")
        print(f"  ユーザーID: {user.get('userid', '不明')}")

        # 現在のAPIキーが紐づくチーム（アクティブチーム）
        active_team_id = user.get("team")
        teams = user.get("teams", [])
        active_team_name = None
        if active_team_id and teams:
            for t in teams:
                if t.get("id") == active_team_id:
                    active_team_name = t.get("name")
                    break
        if active_team_name:
            print(f"  現在のチーム: {active_team_name} (id={active_team_id})")
        elif active_team_id:
            print(f"  現在のチーム: id={active_team_id}")

        # 所属チーム一覧
        if teams:
            other_teams = [t.get("name", "?") for t in teams if t.get("id") != active_team_id]
            if other_teams:
                print(f"  その他の所属チーム: {', '.join(other_teams)}")
        print()


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
    atomic_write(outpath, f"# {title}\n\n{body_md}\n")
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


def _select_target(config, name):
    targets = [t for t in config.targets if _matches_target(t, name)]
    if len(targets) != 1:
        raise ValueError("ターゲットを一意に選べません。--target を指定してください")
    return targets[0]


@project_command
def cmd_link(args):
    dry_run = getattr(args, "dry_run", False)
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    target = _select_target(config, args.target)
    if not args.file or (not getattr(args, "new", False) and (args.entity_id is None or args.entity_id <= 0)):
        raise ValueError("正のIDと --file を指定してください")
    syncer = _make_syncer(_make_client_for_target(config, target), target, config_path.parent)
    path = safe_path(syncer.docs_dir, args.file)
    filename = path.name
    if not path.is_file():
        raise ValueError(f"ローカル文書が見つかりません: {path}")
    mapping = syncer._load_mapping(migrate=False)
    if (filename in mapping and mapping[filename] != args.entity_id) or any(eid == args.entity_id and name != filename for name, eid in mapping.items()):
        raise ValueError("既存の紐付けと衝突しています。rmで解除してからlinkしてください")
    if getattr(args, "new", False):
        if args.entity_id is not None or filename in mapping:
            raise ValueError("--new はID未指定かつ未追跡の文書にのみ使用できます")
        print(f"  {filename}: リモートに対応記事がないことを確認済みとして、新規作成を再開します")
        if not dry_run:
            with local_transaction(config_path.parent, [syncer.hash_dir], "link --new:新規追跡"):
                write_json(syncer.hash_dir / "excluded.json", sorted(syncer._load_excluded() - {filename}))
                pending = syncer._pending()
                pending.pop(filename, None)
                syncer._save_pending(pending)
                syncer._receipt_path(filename).unlink(missing_ok=True)
        return 0
    data = syncer._get_entity(args.entity_id)
    uploads = syncer.client.list_uploads(target.entity, args.entity_id)
    print(f"  {path} → #{args.entity_id} {'紐付け予定' if dry_run else '追跡再開'}")
    if dry_run:
        return 0
    mapping[filename] = args.entity_id
    normalized = _normalize_remote_image_urls(_remote_markdown(data, target), target.entity, args.entity_id,
                                              syncer.client, uploads=uploads)
    normalized = _rewrite_elab_links_to_local(normalized, syncer.client.base_url, mapping, target.entity)
    with local_transaction(config_path.parent, [syncer.hash_dir], "link:追跡再開"):
        syncer._save_mapping(mapping)
        write_json(syncer.hash_dir / "excluded.json", sorted(syncer._load_excluded() - {filename}))
        # A link establishes the remote baseline, not a claim that local content was pushed.
        for suffix in syncer.SUFFIXES:
            (syncer.hash_dir / f"{filename}{suffix}").unlink(missing_ok=True)
        syncer._save_baseline(filename, normalized, data, uploads)
        # Keep unsent metadata visible on next push as well.
        pending = syncer._pending()
        pending.pop(filename, None)
        syncer._save_pending(pending)
    return 0


@project_command
def cmd_mv(args):
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    old_path, new_path = Path(args.old).absolute(), Path(args.new).absolute()
    matches = []
    for target in config.targets:
        if not _matches_target(target, args.target):
            continue
        syncer = _make_syncer(None, target, config_path.parent)
        try:
            old_rel = old_path.relative_to(syncer.docs_dir.absolute()).as_posix()
            new_rel = new_path.relative_to(syncer.docs_dir.absolute()).as_posix()
        except ValueError:
            continue
        safe_path(syncer.docs_dir, old_rel)
        safe_path(syncer.docs_dir, new_rel)
        mapping = syncer._load_mapping(migrate=False)
        if old_path.name in mapping:
            matches.append((syncer, mapping))
    if len(matches) != 1:
        raise ValueError("移動元を一意に選べません。同じターゲット内のパスを指定してください")
    syncer, mapping = matches[0]
    if new_path.suffix != ".md" or not new_path.match(syncer.target.pattern):
        raise ValueError("移動先が同期対象のMarkdownパターンと一致しません")
    if old_path == new_path or (old_path.exists() and new_path.exists()):
        raise ValueError("移動先が既に存在します")
    if not old_path.is_file() and not new_path.is_file():
        raise ValueError("移動元も移動先も存在しません")
    if new_path.name != old_path.name and (new_path.name in mapping or new_path.name in syncer._load_excluded()):
        raise ValueError("移動先に追跡・除外情報があります")
    if syncer._pending():
        raise ValueError("未完了の同期を解決してからmvしてください")
    print(f"  {old_path} → {new_path}（リモートタイトルは次回pushで更新）")
    if args.dry_run:
        return 0
    with local_transaction(config_path.parent, syncer.backup_paths(), "mv:文書の移動"):
        if old_path.exists():
            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)
        if old_path.name != new_path.name:
            syncer.move_tracking(old_path.name, new_path.name, mapping)
    return 0


def cmd_backup(args):
    root = Path(args.config).resolve().parent
    for path in sorted((root / BACKUPS).glob("*/manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        print(f"  {manifest['id']}  {manifest['reason']}")
    return 0


@project_command
def cmd_restore(args):
    restore(Path(args.config).resolve().parent, args.backup_id, args.dry_run)
    return 0


@project_command
def cmd_rm(args):
    """継続的に追跡解除する。文書は既定で保持し、--local 指定時に削除する。"""
    def fail(message):
        print(f"エラー: {message}", file=sys.stderr)
        sys.exit(1)

    if args.id and not args.entity:
        fail("--id 指定時は --entity も指定してください")
    if args.entity and not args.id:
        fail("--entity は --id と一緒に指定してください")
    regexes = []
    for expression in getattr(args, "regex", None) or []:
        try:
            regexes.append(re.compile(expression))
        except re.error as exc:
            fail(f"正規表現が不正です: {expression}: {exc}")
    if not args.files and not args.id and not regexes:
        fail("ファイル・ディレクトリ・パターン、--regex、または --id と --entity を指定してください")

    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    targets = [t for t in config.targets if _matches_target(t, args.target)]
    if not targets:
        fail(f"ターゲット '{args.target}' が見つかりません")
    states = []
    for target in targets:
        syncer = _make_syncer(None, target, config_path.parent)
        mapping = syncer._load_mapping(migrate=False)
        excluded = syncer._load_excluded()
        states.append((syncer, mapping, excluded, {}))

    selectors = [("file", value) for value in args.files]
    selectors += [("id", value) for value in (args.id or [])]
    selectors += [("regex", value) for value in regexes]
    for kind, value in selectors:
        selector_path = Path(value).resolve() if kind == "file" else None
        is_pattern = kind == "file" and not selector_path.exists() and glob.has_magic(value)
        directories = []
        if kind == "file":
            if selector_path.is_dir():
                directories = [selector_path]
            elif is_pattern:
                directories = [Path(p).resolve() for p in glob.glob(value) if Path(p).is_dir()]
        matches = []
        for index, (syncer, mapping, excluded, selected) in enumerate(states):
            if kind == "id" and syncer.entity != _normalize_entity(args.entity):
                continue
            for name in mapping.keys() | excluded:
                # 同期エンジンのキーはファイル名。状態ファイル由来の外部パスは扱わない。
                if Path(name).name != name or name in ("", ".", ".."):
                    continue
                paths = [p for p in syncer.docs_dir.glob(syncer.target.pattern) if p.name == name]
                if not paths:
                    paths = [syncer.docs_dir / name]
                if kind == "file":
                    matching_paths = [p for p in paths if (
                        p.resolve() == selector_path
                        or any(p.resolve().is_relative_to(d) for d in directories)
                        or (is_pattern and p.resolve().match(str(selector_path)))
                    )]
                elif kind == "regex":
                    matching_paths = paths if value.search(name) else []
                else:
                    matching_paths = paths if mapping.get(name) == value else []
                if matching_paths:
                    if len(paths) > 1:
                        fail(f"同名ファイルが複数あり追跡情報を特定できません: {name}")
                    matches.append((index, name, matching_paths[0]))
        if not matches:
            fail(f"追跡対象が見つかりません: {value}")
        if len({index for index, name, path in matches}) > 1:
            fail(f"対象が複数のターゲットに存在します: {value}（--target で絞り込んでください）")
        for index, name, path in matches:
            states[index][3][name] = path

    for syncer, mapping, excluded, selected in states:
        if not selected:
            continue
        if args.local:
            for name in selected:
                path = selected[name]
                if path.exists() and not path.is_file():
                    fail(f"通常ファイルではありません: {path}")

    for syncer, mapping, excluded, selected in states:
        if not selected:
            continue
        if any(name in mapping for name in selected):
            print("  注意: 解除する文書への相対リンクは、今後の push でリモート URL に変換されなくなります。"
                  "参照元のリンクを eLabFTW の文書 URL に変更してください。")
        needs_change = any(name in mapping or name not in excluded or (args.local and path.exists()) for name, path in selected.items())
        if not args.dry_run and needs_change:
            with local_transaction(config_path.parent, syncer.backup_paths(), "rm:追跡解除"):
                syncer.untrack(set(selected), mapping)
                if args.local:
                    for path in selected.values():
                        path.unlink(missing_ok=True)
        for name in sorted(selected):
            action = "追跡解除予定" if args.dry_run else "追跡解除しました"
            print(f"  {action}: {selected[name]}")
            if args.local:
                path = selected[name]
                action = "ファイル削除予定" if args.dry_run else "ファイル削除済み"
                print(f"  {action}: {path}")


def cmd_verify(args):
    """ローカルとリモートの整合性をチェックする。"""
    config_path = Path(args.config)
    project_root = config_path.parent or Path(".")
    config = load_config(config_path)
    client = ELabFTWClient(config.url, config.api_key, config.verify_ssl)
    issues = 0

    for target in config.targets:
        if not _matches_target(target, args.target):
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


def cmd_profile(args):
    """プロファイルの管理（add / list / remove）。"""
    config_path = Path(args.config)

    if args.profile_action == "list":
        if not config_path.exists():
            print("  設定ファイルがありません")
            return
        raw = yaml.safe_load(_read_yaml_text(config_path)) or {}
        profiles = raw.get("profiles", {})
        # elabftw セクションがあれば default として表示
        elab = raw.get("elabftw", {})
        if "default" not in profiles and elab.get("url"):
            profiles["default"] = {"url": elab["url"], "api_key": elab.get("api_key", ""),
                                   "verify_ssl": elab.get("verify_ssl", True)}
        if not profiles:
            print("  プロファイルがありません")
            return
        for name, pdata in profiles.items():
            url = pdata.get("url", "?")
            has_key = "✓" if pdata.get("api_key") else "✗"
            ssl = "SSL検証あり" if pdata.get("verify_ssl", True) else "SSL検証なし"
            print(f"  {name}: {url} (API キー: {has_key}, {ssl})")

    elif args.profile_action == "add":
        name = args.profile_name
        url = args.url
        api_key = args.api_key or ""
        verify_ssl = not args.no_verify

        raw = {}
        if config_path.exists():
            raw = yaml.safe_load(_read_yaml_text(config_path)) or {}

        profiles = raw.setdefault("profiles", {})
        if name in profiles:
            ans = input(f"  プロファイル '{name}' は既に存在します。上書きしますか？ [y/N]: ").strip().lower()
            if ans != "y":
                print("  中止しました")
                return

        profiles[name] = {"url": url, "api_key": api_key, "verify_ssl": verify_ssl}

        content = yaml.dump(raw, default_flow_style=False, allow_unicode=True)
        atomic_write(config_path, content)
        print(f"  ✅ プロファイル '{name}' を追加しました")
        if not api_key:
            print(f"     API キーを設定してください: .elab-sync.yaml の profiles.{name}.api_key")

    elif args.profile_action == "remove":
        name = args.profile_name
        if not config_path.exists():
            print("  設定ファイルがありません")
            return
        raw = yaml.safe_load(_read_yaml_text(config_path)) or {}
        profiles = raw.get("profiles", {})
        if name not in profiles:
            print(f"  プロファイル '{name}' が見つかりません")
            return
        # 使用中チェック
        using_targets = [t.get("docs_dir", "?") for t in raw.get("targets", []) if t.get("profile") == name]
        if using_targets:
            print(f"  ⚠ プロファイル '{name}' は以下のターゲットで使用中です:")
            for d in using_targets:
                print(f"    - {d}")
            ans = input("  削除しますか？ [y/N]: ").strip().lower()
            if ans != "y":
                print("  中止しました")
                return
        del profiles[name]
        content = yaml.dump(raw, default_flow_style=False, allow_unicode=True)
        atomic_write(config_path, content)
        print(f"  ✅ プロファイル '{name}' を削除しました")


def cmd_entity_status(args):
    """エンティティのステータスを表示または変更する。"""
    config_path = Path(args.config)
    project_root = config_path.parent or Path(".")
    config = load_config(config_path)
    client = ELabFTWClient(config.url, config.api_key, config.verify_ssl)

    all_ids = []
    for target in config.targets:
        if not _matches_target(target, args.target):
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
    common.add_argument("--prune-attachments", action="store_true", help="ローカルに存在しないリモート添付を削除")

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
    pull_parser.add_argument("--dir", default=None, help="保存先ディレクトリ（未指定時は自動振り分け）")
    pull_parser.add_argument("--auto", action="store_true", help="曖昧な振り分けもスコア最大で自動決定")

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
    link_parser.add_argument("entity_id", type=int, nargs="?", help="リモートエンティティ ID")
    link_parser.add_argument("--file", default=None, help="紐付けるローカルファイル名（each モード時）")

    link_parser.add_argument("--new", action="store_true", help="対応するリモート記事が存在しないと確認後、新規追跡を再開")

    rm_parser = sub.add_parser("rm", help="文書を保持して追跡解除し、今後の同期から除外", parents=[common])
    rm_parser.add_argument("files", nargs="*", help="解除するファイル・ディレクトリ・glob（カレントディレクトリ基準、複数指定可）")
    rm_parser.add_argument("--regex", action="append", help="ファイル名に部分一致する正規表現（複数指定可）")
    rm_parser.add_argument("--id", type=int, action="append", help="解除するリモート ID（複数指定可）")
    rm_parser.add_argument("--entity", choices=["items", "experiments", "resources"], help="ID のエンティティ種別")
    rm_parser.add_argument("--local", action="store_true", help="対象のローカル Markdown ファイルも削除する")

    sub.add_parser("verify", help="ローカルとリモートの整合性チェック", parents=[common])

    profile_parser = sub.add_parser("profile", help="接続プロファイルを管理", parents=[common])
    profile_sub = profile_parser.add_subparsers(dest="profile_action")
    profile_sub.add_parser("list", help="プロファイル一覧を表示")
    profile_add_p = profile_sub.add_parser("add", help="プロファイルを追加")
    profile_add_p.add_argument("profile_name", help="プロファイル名")
    profile_add_p.add_argument("--url", required=True, help="eLabFTW の URL")
    profile_add_p.add_argument("--api-key", default=None, help="API キー")
    profile_add_p.add_argument("--no-verify", action="store_true", help="SSL 検証を無効化")
    profile_rm_p = profile_sub.add_parser("remove", help="プロファイルを削除")
    profile_rm_p.add_argument("profile_name", help="削除するプロファイル名")

    estatus_sub = estatus_parser.add_subparsers(dest="status_action")
    estatus_sub.add_parser("show", help="現在のステータスを表示")
    estatus_set_p = estatus_sub.add_parser("set", help="ステータスを変更")
    estatus_set_p.add_argument("status_id", help="ステータス ID")
    estatus_set_p.add_argument("--id", type=int, default=None, help="対象エンティティ ID（省略時は全同期済みエンティティ）")

    backup_parser = sub.add_parser("backup", help="バックアップ一覧", parents=[common])
    backup_parser.add_argument("backup_action", choices=["list"])
    restore_parser = sub.add_parser("restore", help="ローカルバックアップを復元", parents=[common])
    restore_parser.add_argument("backup_id")
    mv_parser = sub.add_parser("mv", help="文書と紐付けを移動", parents=[common])
    mv_parser.add_argument("old")
    mv_parser.add_argument("new")

    args = parser.parse_args()
    commands = {
        None: cmd_sync, "push": cmd_sync, "status": cmd_status, "init": cmd_init,
        "pull": cmd_pull, "diff": cmd_diff, "update": cmd_update, "log": cmd_log,
        "clone": cmd_clone, "tag": cmd_tag, "metadata": cmd_metadata,
        "entity-status": cmd_entity_status, "category": cmd_category,
        "whoami": cmd_whoami, "new": cmd_new, "list": cmd_list,
        "link": cmd_link, "rm": cmd_rm, "verify": cmd_verify, "profile": cmd_profile,
        "mv": cmd_mv, "backup": cmd_backup, "restore": cmd_restore,
    }
    try:
        handler = commands[args.command]
        other_write = args.command in ("init", "new") or (
            args.command == "profile" and args.profile_action in ("add", "remove")) or (
            args.command == "tag" and args.tag_action in ("add", "remove")) or (
            args.command == "metadata" and args.meta_action == "set") or (
            args.command == "entity-status" and args.status_action == "set") or (
            args.command == "category" and args.cat_action == "set")
        if other_write:
            if getattr(args, "dry_run", False):
                raise ValueError("このコマンドは --dry-run に対応していません（変更は行いません）")
            handler = project_command(handler)
        result = handler(args)
    except ValueError as exc:
        print(f"設定・引数エラー: {exc}", file=sys.stderr)
        raise SystemExit(2)
    except Exception as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        raise SystemExit(1)
    if isinstance(result, int) and result:
        raise SystemExit(result)
