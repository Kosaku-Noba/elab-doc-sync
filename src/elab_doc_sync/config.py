"""Load and validate .elab-sync.yaml configuration."""

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
import yaml
from .safety import atomic_write


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
    api_key_env: str | None = None  # API キーを読む環境変数の名前（指定時は api_key に環境変数の値が入る）


@dataclass
class TargetConfig:
    title: str
    docs_dir: str
    id_file: str
    pattern: str = "*.md"
    mode: str = "each"        # "each" (1ファイル=1エンティティ)
    entity: str = "items"     # "items" or "experiments"
    tags: list[str] = None    # push 時に自動設定するタグ
    body_format: str = BODY_FORMAT_DEFAULT
    attachments_dir: str | None = None  # 添付ファイルディレクトリ（画像以外）
    attachments_pattern: str = "*"  # prune する添付名の glob フィルタ
    category: str | int | None = None   # push 時に自動設定するカテゴリ（ID or 名前）
    title_pattern: str | None = None    # pull 時のタイトルマッチング用 glob パターン
    profile: str = "default"  # 使用するプロファイル名
    team: str | int | None = None  # 送信先チーム名 or ID（profileを自動選択）
    links: dict[str, list[int]] = None  # push 時に追加するリンク {"experiments": [...], "items": [...]}

    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.links is None:
            self.links = {}


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


class ConfigError(ValueError):
    """設定ファイルの読み込み・検証エラー。"""


def _abort(msg: str) -> None:
    raise ConfigError(msg)


def _parse_links(raw) -> dict[str, list[int]]:
    """ターゲットの links を {"experiments": [ID...], "items": [ID...]} に正規化する。

    resources は items のエイリアス。空のリストは省く。
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        _abort("linksは experiments / items（resources）をキーにしたID一覧で指定してください")
    links: dict[str, set[int]] = {}
    for key, ids in raw.items():
        link_type = "items" if key in ("resources", "resource") else key
        if link_type not in ("items", "experiments"):
            _abort(f"linksのキーはexperiments・items・resourcesのいずれかを指定してください（現在: {key!r}）")
        if not isinstance(ids, list) or any(isinstance(i, bool) or not isinstance(i, int) or i <= 0 for i in ids):
            _abort(f"links.{key}は正の整数IDのリストで指定してください")
        links.setdefault(link_type, set()).update(ids)
    return {k: sorted(v) for k, v in links.items() if v}


_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_api_key_env(section: dict, where: str) -> str | None:
    """api_key_env（API キーを読む環境変数の名前）を検証して返す。キーが無いときは None。空・null・空白だけはエラー。

    キーの値を誤って書いた場合に値をエラーへ出さないよう、名前として不正なときは値を表示しない。
    """
    if "api_key_env" not in section:
        return None
    name = section["api_key_env"]
    if name is None or (isinstance(name, str) and not name.strip()):
        _abort(
            f"{where}.api_key_env が空です\n"
            "→ 環境変数の名前を指定するか、api_key_env の行を削除してください"
            "（空のままでは ELABFTW_API_KEY や api_key には切り替わりません）"
        )
    if not isinstance(name, str) or not _ENV_NAME_RE.match(name.strip()):
        _abort(
            f"{where}.api_key_env には環境変数の名前を指定してください"
            "（英数字とアンダースコア。キーの値そのものは書かないでください）"
        )
    return name.strip()


def _resolve_api_key_env(name: str) -> str:
    """名前の環境変数の値（前後の空白を除く）を返す。未設定・空なら空文字。"""
    return os.environ.get(name, "").strip()


def _missing_api_key_env_message(name: str, where: str) -> str:
    return (
        f"{where} の api_key_env に指定された環境変数 {name} が設定されていないか、空です\n"
        f"→ 環境変数 {name} に API キーを設定してください"
        "（api_key_env を指定したときは ELABFTW_API_KEY や api_key には切り替えません）"
    )


def profile_connection(profile: "ProfileConfig") -> tuple[str, str, bool]:
    """プロファイルの (url, api_key, verify_ssl) を返す。

    api_key_env を指定したのに環境変数が無い・空のときは ValueError（キーの値は含めない）。
    """
    if profile.api_key_env and not profile.api_key:
        raise ValueError(_missing_api_key_env_message(profile.api_key_env, f"プロファイル '{profile.name}'"))
    return profile.url, profile.api_key, profile.verify_ssl


def _valid_server_url(url) -> bool:
    """http(s) のスキームとホストを持つ URL か。

    検証した文字列をそのまま接続・表示に使えるよう、前後を含めて空白（全角空白などを含む）や制御文字を
    一切含まない URL だけを有効とする。
    """
    from urllib.parse import urlsplit
    text = str(url)
    if not text or any(c.isspace() or not c.isprintable() for c in text):
        return False
    try:
        parts = urlsplit(text)
        parts.port  # 数字でないポートや 0〜65535 の範囲外（区切りの誤記でパスワードがポート扱いになった場合など）は ValueError
        return parts.scheme in ("http", "https") and bool(parts.hostname)
    except ValueError:
        return False


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
        api_key_env = _parse_api_key_env(pdata, f"profiles.{name}")
        if api_key_env:
            # 指定した環境変数だけを見る。無い・空でも api_key には戻さない（使うときにエラーにする）
            api_key = _resolve_api_key_env(api_key_env)
        verify_ssl = pdata.get("verify_ssl", True)
        team = pdata.get("team")  # str (名前) or int (ID) or None
        profiles[name] = ProfileConfig(
            name=name, url=url, api_key=api_key, verify_ssl=verify_ssl,
            team=team, api_key_env=api_key_env,
        )
    return profiles


def load_config(config_path: Path) -> Config:
    """従来の CLI 互換 API。設定エラーは標準エラー出力と終了コード 2 で示す。"""
    try:
        return read_config(config_path)
    except ConfigError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


def read_config(config_path: Path) -> Config:
    if not config_path.exists():
        _abort(
            f"設定ファイルが見つかりません: {config_path}\n"
            "→ 'elab-doc-sync init' で作成できます"
        )

    try:
        raw = yaml.safe_load(_read_yaml_text(config_path))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f"（{mark.line + 1}行目、{mark.column + 1}列目）" if mark else ""
        _abort(f"YAMLの形式が不正です{location}")
    if not isinstance(raw, dict):
        _abort("設定ファイルはYAMLのマッピング形式で記述してください")

    # profiles セクションをパース
    profiles = _parse_profiles(raw)

    # 後方互換: elabftw セクションがあれば default プロファイルとして扱う
    elab = raw.get("elabftw", {})
    url = elab.get("url", "")
    elab_key_env = _parse_api_key_env(elab, "elabftw")
    if elab_key_env:
        api_key = _resolve_api_key_env(elab_key_env)
    else:
        api_key = os.environ.get("ELABFTW_API_KEY", "").strip() or elab.get("api_key", "").strip()
    verify_ssl = elab.get("verify_ssl", True)

    # elabftw セクションから default プロファイルを構築（profiles に default がなければ）
    if "default" not in profiles and url:
        profiles["default"] = ProfileConfig(
            name="default", url=url, api_key=api_key, verify_ssl=verify_ssl,
            api_key_env=elab_key_env,
        )
    elif "default" in profiles:
        # profiles.default が存在する場合、環境変数は default プロファイルの api_key を上書き
        # （api_key_env を指定したプロファイルは、その環境変数だけを見る）
        env_key = "" if profiles["default"].api_key_env else os.environ.get("ELABFTW_API_KEY", "").strip()
        if env_key:
            profiles["default"] = ProfileConfig(
                name="default",
                url=profiles["default"].url,
                api_key=env_key,
                verify_ssl=profiles["default"].verify_ssl,
                team=profiles["default"].team,
                api_key_env=profiles["default"].api_key_env,
            )

    # 接続先 URL の形を確かめる。不正な URL は認証情報ごとエラー文や JSON に出かねないので、値は表示しない。
    for profile in profiles.values():
        if profile.url and not _valid_server_url(profile.url):
            _abort(f"プロファイル '{profile.name}' の url が不正です\n"
                   "→ https://elab.example.com のように、http:// または https:// から始まる URL を指定してください")

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

    if not api_key and default_profile.api_key_env:
        _abort(_missing_api_key_env_message(
            default_profile.api_key_env, f"プロファイル '{default_profile.name}'"))
    if not api_key:
        _abort(
            "API キーが設定されていません\n"
            "→ .elab-sync.yaml の elabftw.api_key に設定するか、\n"
            "  api_key_env に環境変数の名前を指定するか、\n"
            '  環境変数を設定してください: export ELABFTW_API_KEY="your_key"'
        )

    targets_raw = raw.get("targets", [])
    if not isinstance(targets_raw, list):
        _abort("targetsはリスト形式で指定してください")
    targets = []
    for t in targets_raw:
        if not isinstance(t, dict) or not isinstance(t.get("docs_dir"), str) or not t["docs_dir"].strip():
            _abort("各ターゲットにはdocs_dirが必要です")
        mode = t.get("mode", "each")
        if mode != "each":
            _abort("v1.0ではeachのみ対応します。merge設定の移行手順は docs/13_MIGRATION_V1.md を参照してください")
        entity = t.get("entity", "items")
        # resources は items のエイリアス（eLabFTW Web UI の表示名）
        if entity in ("resources", "resource"):
            entity = "items"
        if entity not in ("items", "experiments"):
            _abort("entityはitemsまたはexperimentsを指定してください")
        title = t.get("title", "")
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
            links=_parse_links(t.get("links")),
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
        if not profile:
            raise ValueError(f"接続プロファイルが見つかりません: {target.profile}")
        return profile_connection(profile)

    # team が指定されている場合、profiles から対応するものを探す
    if target.team is not None and config.profiles:
        for profile in config.profiles.values():
            if profile.team is not None and _team_matches(profile.team, target.team):
                return profile_connection(profile)
        # team 指定があるが対応するプロファイルが見つからない場合はエラー情報を出す
        print(
            f"警告: ターゲット '{target.docs_dir}' の team '{target.team}' に対応する"
            f"プロファイルが見つかりません。default プロファイルを使用します。",
            file=sys.stderr,
        )

    # フォールバック: profile 名で検索 → config のデフォルト値
    profile = config.profiles.get(target.profile)
    if profile:
        return profile_connection(profile)
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
    atomic_write(config_path, content)


def append_target_to_yaml(config_path: Path, target_data: dict) -> None:
    """YAML ファイルに新しいターゲットを追記する。"""
    raw = yaml.safe_load(_read_yaml_text(config_path)) or {}
    raw.setdefault("targets", []).append(target_data)
    content = yaml.dump(raw, default_flow_style=False, allow_unicode=True)
    atomic_write(config_path, content)
