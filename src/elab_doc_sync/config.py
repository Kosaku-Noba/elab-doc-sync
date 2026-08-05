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


def _read_yaml_text(path: Path) -> str:
    """UTF-8 で読み、失敗したら cp932 にフォールバックする。"""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="cp932")


@dataclass
class ProfileConfig:
    """接続プロファイル（サーバー + 認証情報）。"""
    name: str
    url: str
    api_key: str
    verify_ssl: bool = True
    team: str | int | None = None  # チーム名 or ID（宣言的。起動時に検証可能）


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
    attachments_pattern: str = "*"  # 添付ファイルの glob フィルタ
    category: str | int | None = None   # push 時に自動設定するカテゴリ（ID or 名前）
    title_pattern: str | None = None    # pull 時のタイトルマッチング用 glob パターン
    profile: str = "default"  # 使用するプロファイル名
    team: str | int | None = None  # 送信先チーム名 or ID（profileを自動選択）

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


@dataclass
class Config:
    url: str
    api_key: str
    verify_ssl: bool
    targets: list[TargetConfig]
    profiles: dict[str, ProfileConfig] = None  # name → ProfileConfig

    def __post_init__(self):
        if self.profiles is None:
            self.profiles = {}


def _abort(msg: str) -> None:
    print(f"エラー: {msg}", file=sys.stderr)
    sys.exit(1)


def _parse_profiles(raw: dict) -> dict[str, ProfileConfig]:
    """YAML の profiles セクションをパースする。"""
    profiles_raw = raw.get("profiles", {})
    if not profiles_raw or not isinstance(profiles_raw, dict):
        return {}
    profiles = {}
    for name, pdata in profiles_raw.items():
        if not isinstance(pdata, dict):
            continue
        url = pdata.get("url", "")
        api_key = pdata.get("api_key", "").strip()
        verify_ssl = pdata.get("verify_ssl", True)
        team = pdata.get("team")  # str (名前) or int (ID) or None
        profiles[name] = ProfileConfig(
            name=name, url=url, api_key=api_key, verify_ssl=verify_ssl,
            team=team,
        )
    return profiles


def load_config(config_path: Path) -> Config:
    if not config_path.exists():
        _abort(
            f"設定ファイルが見つかりません: {config_path}\n"
            "→ 'elab-doc-sync init' で作成できます"
        )

    raw = yaml.safe_load(_read_yaml_text(config_path))

    # profiles セクションをパース
    profiles = _parse_profiles(raw)

    # 後方互換: elabftw セクションがあれば default プロファイルとして扱う
    elab = raw.get("elabftw", {})
    url = elab.get("url", "")
    api_key = os.environ.get("ELABFTW_API_KEY", "").strip() or elab.get("api_key", "").strip()
    verify_ssl = elab.get("verify_ssl", True)

    # elabftw セクションから default プロファイルを構築（profiles に default がなければ）
    if "default" not in profiles and url:
        profiles["default"] = ProfileConfig(
            name="default", url=url, api_key=api_key, verify_ssl=verify_ssl
        )
    elif "default" in profiles:
        # profiles.default が存在する場合、環境変数は default プロファイルの api_key を上書き
        env_key = os.environ.get("ELABFTW_API_KEY", "").strip()
        if env_key:
            profiles["default"] = ProfileConfig(
                name="default",
                url=profiles["default"].url,
                api_key=env_key,
                verify_ssl=profiles["default"].verify_ssl,
            )

    # url / api_key のバリデーション（default プロファイルベース）
    default_profile = profiles.get("default")
    if not default_profile or not default_profile.url:
        # profiles に何らかの定義があればURL未設定エラーを出さない
        if not profiles:
            _abort(
                "eLabFTW の URL が設定されていません\n"
                "→ .elab-sync.yaml の elabftw.url を確認してください"
            )
        # profiles があるが default がない場合、最初のプロファイルを使う
        default_profile = next(iter(profiles.values()))
        url = default_profile.url
        api_key = default_profile.api_key
        verify_ssl = default_profile.verify_ssl
    else:
        url = default_profile.url
        api_key = default_profile.api_key
        verify_ssl = default_profile.verify_ssl

    if not api_key:
        _abort(
            "API キーが設定されていません\n"
            "→ .elab-sync.yaml の elabftw.api_key に設定するか、\n"
            '  環境変数を設定してください: export ELABFTW_API_KEY="your_key"'
        )

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
        # id_file のデフォルト: docs_dir からユニークなサブディレクトリを生成
        # これにより mapping.json / hash ファイルもターゲットごとに分離される
        # 例: docs_dir="elab_docs" → ".elab-sync-ids/elab_docs/default.id"
        #     docs_dir="elab_weekly_reports/" → ".elab-sync-ids/elab_weekly_reports/default.id"
        docs_dir_name = t["docs_dir"].rstrip("/").replace("/", "_").replace("\\", "_")
        default_id_file = f".elab-sync-ids/{docs_dir_name}/default.id"

        targets.append(TargetConfig(
            title=title,
            docs_dir=t["docs_dir"],
            id_file=t.get("id_file", default_id_file),
            pattern=t.get("pattern", "*.md"),
            mode=mode,
            entity=entity,
            tags=t.get("tags", []),
            body_format=body_format,
            attachments_dir=t.get("attachments_dir"),
            attachments_pattern=t.get("attachments_pattern", "*"),
            category=t.get("category"),
            title_pattern=t.get("title_pattern"),
            profile=t.get("profile", "default"),
            team=t.get("team"),
        ))

    if not targets:
        _abort(
            "同期ターゲットが定義されていません\n"
            "→ .elab-sync.yaml の targets を確認してください"
        )

    return Config(url=url, api_key=api_key, verify_ssl=verify_ssl,
                  targets=targets, profiles=profiles)


def get_client_for_target(config: Config, target: TargetConfig):
    """ターゲットのプロファイルに基づいて ELabFTWClient を生成する。

    返り値は (url, api_key, verify_ssl) のタプル。
    client のインスタンス化は呼び出し元で行う（循環 import 回避）。

    target.team が指定されている場合:
      - profiles の中から同じ team 値を持つプロファイルを自動選択
      - target.profile が明示的に指定されている場合は profile を優先
    """
    # profile が明示的に指定されている場合はそれを優先
    if target.profile != "default":
        profile = config.profiles.get(target.profile)
        if profile:
            return profile.url, profile.api_key, profile.verify_ssl

    # team が指定されている場合、profiles から対応するものを探す
    if target.team is not None and config.profiles:
        for profile in config.profiles.values():
            if profile.team is not None and _team_matches(profile.team, target.team):
                return profile.url, profile.api_key, profile.verify_ssl
        # team 指定があるが対応するプロファイルが見つからない場合はエラー情報を出す
        print(
            f"警告: ターゲット '{target.docs_dir}' の team '{target.team}' に対応する"
            f"プロファイルが見つかりません。default プロファイルを使用します。",
            file=sys.stderr,
        )

    # フォールバック: profile 名で検索 → config のデフォルト値
    profile = config.profiles.get(target.profile)
    if profile:
        return profile.url, profile.api_key, profile.verify_ssl
    return config.url, config.api_key, config.verify_ssl


def _team_matches(profile_team: str | int, target_team: str | int) -> bool:
    """プロファイルの team とターゲットの team が一致するか判定する。

    両方が int に変換可能なら数値比較、そうでなければ文字列比較（大文字小文字無視）。
    """
    try:
        return int(profile_team) == int(target_team)
    except (ValueError, TypeError):
        return str(profile_team).lower() == str(target_team).lower()


def update_target_in_yaml(config_path: Path, target_index: int, **fields) -> None:
    """YAML ファイル内の指定ターゲットのフィールドを更新する。

    fields に渡されたキーのみ上書きする。存在しないキーは追加される。
    書き込みは文字列にシリアライズしてからファイルに書く（部分書き込み防止）。
    """
    raw = yaml.safe_load(_read_yaml_text(config_path)) or {}
    targets = raw.get("targets", [])
    if target_index < 0 or target_index >= len(targets):
        return
    for k, v in fields.items():
        targets[target_index][k] = v
    content = yaml.dump(raw, default_flow_style=False, allow_unicode=True)
    config_path.write_text(content, encoding="utf-8")


def append_target_to_yaml(config_path: Path, target_data: dict) -> None:
    """YAML ファイルに新しいターゲットを追記する。"""
    raw = yaml.safe_load(_read_yaml_text(config_path)) or {}
    raw.setdefault("targets", []).append(target_data)
    content = yaml.dump(raw, default_flow_style=False, allow_unicode=True)
    config_path.write_text(content, encoding="utf-8")
