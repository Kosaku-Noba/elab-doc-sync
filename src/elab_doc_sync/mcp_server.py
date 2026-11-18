"""eLabFTW の同期プロジェクトを stdio MCP ツールとして公開する。"""

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import cli
from .config import _read_yaml_text
from .result import CommandResult, error_text, redact
from .safety import project_command, safe_path


@dataclass
class Operation:
    description: str
    fields: str = ""
    write: bool = False


# 各ツールに公開する引数を明示し、型・選択肢・説明は CLI と共有する。
OPERATIONS = {
    "status": Operation("同期状態と次の操作を確認する", "target"),
    "diff": Operation("前回同期後のローカルとリモートの変更を比較する", "target files regex"),
    "log": Operation("同期履歴を読む", "limit"),
    "list": Operation("リソースまたは実験ノートを一覧する", "target entity_type limit"),
    "search": Operation("eLabFTW を検索する", "target keyword entity_type author since until updated_since updated_until tag category status scope order sort limit offset body"),
    "whoami": Operation("接続プロファイルのユーザーとチームを確認する"),
    "verify": Operation("追跡文書の整合性を検証する", "target"),
    "backup_list": Operation("復元可能なバックアップを一覧する"),
    "profile_list": Operation("接続プロファイルを一覧する"),
    "tag_list": Operation("記事のタグを確認する", "target id entity"),
    "tag_add": Operation("記事にタグを追加する", "target id entity tag_name", True),
    "tag_remove": Operation("記事からタグを外す", "target id entity tag_name", True),
    "relate_list": Operation("記事間のリンクを確認する", "target id entity from_docs"),
    "relate_add": Operation("記事間にリンクを追加する", "target id entity from_docs target_ids to", True),
    "relate_remove": Operation("記事間のリンクを解除する", "target id entity from_docs target_ids to", True),
    "metadata_get": Operation("同期済み記事のメタデータを取得する", "target"),
    "metadata_set": Operation("記事のメタデータを更新する", "target keyvalues id", True),
    "entity_status_show": Operation("同期済み記事のステータスを表示する", "target"),
    "category_list": Operation("カテゴリを一覧する", "target entity"),
    "category_show": Operation("記事のカテゴリを確認する", "target id entity"),
    "category_set": Operation("記事のカテゴリを設定する", "target id entity category_value", True),
    "new_list": Operation("実験テンプレートを一覧する", "target"),
    "new": Operation("テンプレートから Markdown を作成する", "target template_id title output force", True),
    "push": Operation("Markdown と添付ファイルを eLabFTW に同期する", "target files regex force prune_attachments", True),
    "pull": Operation("記事をローカルに取得する。auto=true または dir を指定する", "target id entity dir auto force", True),
    "clone": Operation("起動時に設定された接続先からプロジェクトを作成する", "id dir entity", True),
    "link": Operation("文書の追跡を開始・再開する", "target entity_id file new", True),
    "rm": Operation("文書の追跡を解除する。local=true はファイルも削除する", "target files regex id entity local", True),
    "mv": Operation("文書と追跡情報を同じターゲット内で移動する", "target old new", True),
    "restore": Operation("バックアップからローカル状態を復元する", "backup_id", True),
}


def _subcommands(parser):
    return next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)


def _field_schema(action):
    field = {"type": "integer" if action.type is int else "string"}
    if action.choices:
        field["enum"] = list(action.choices)
    if action.dest in {"id", "entity_id", "template_id"}:
        field["minimum"] = 1
    if isinstance(action, argparse._StoreTrueAction):
        field = {"type": "boolean"}
    elif isinstance(action, argparse._AppendAction) or action.nargs in ("*", "+"):
        field = {"type": "array", "items": field}
        if action.required or action.nargs == "+" or action.dest in {"id", "regex", "from_docs"}:
            field["minItems"] = 1
    if action.help:
        field["description"] = action.help.replace("カレントディレクトリ基準", "設定ファイルのディレクトリ基準")
    return field


def _bindings():
    parser = cli.build_parser()
    commands = _subcommands(parser).choices
    bindings = {}
    for name, operation in OPERATIONS.items():
        command, _, action = name.replace("entity_status", "entity-status").partition("_")
        sub = commands[command]
        actions = list(sub._actions)
        fixed = {}
        nested = _subcommands(sub)
        if nested:
            actions.extend(nested.choices[action]._actions)
            fixed[nested.dest] = action
        if command == "new":
            fixed["list_templates"] = action == "list"
        if command == "backup":
            fixed["backup_action"] = "list"
        args = {a.dest: a for a in actions}
        fields = operation.fields.split()
        defaults = {key: None if a.default == argparse.SUPPRESS else a.default
                    for key, a in args.items() if key != "help"}
        for a in actions:
            if a.nargs == "*" and defaults.get(a.dest) is None:
                defaults[a.dest] = []
        defaults.update(fixed)
        # 参照系でも旧形式の mapping を移行しない。
        defaults["dry_run"] = True
        defaults.setdefault("target", None)
        props = {key: _field_schema(args[key]) for key in fields}
        required = [key for key in fields if args[key].required and args[key].nargs not in ("?", "*")]
        if operation.write:
            props["dry_run"] = {"type": "boolean", "default": True, "description": "予定を確認する。false で適用する"}
        if command == "new" and not action:
            required.append("template_id")
        if command == "link":
            required.append("file")
        for key in fields:
            if key not in required and defaults[key] is not None:
                props[key]["default"] = defaults[key]
        schema = {"type": "object", "properties": props, "required": required, "additionalProperties": False}
        handler_name = "profile_list" if command == "profile" else command.replace("-", "_")
        handler = getattr(cli, "run_" + handler_name)
        if operation.write and command in {"tag", "relate", "metadata", "category", "new"}:
            handler = project_command(handler)
        bindings[name] = (schema, defaults, handler)
    return bindings


def _project_path(root, value):
    if not value.strip():
        raise ValueError("空のパスは指定できません")
    path = Path(value)
    if path.is_absolute():
        path = path.relative_to(root)
    if path == Path("."):
        return root
    return safe_path(root, path.as_posix())


def _arguments(name, defaults, values, config, clone_url):
    if any(isinstance(item, str) and not item.strip() for value in values.values()
           for item in (value if isinstance(value, list) else [value])):
        raise ValueError("空の引数は指定できません")
    args = argparse.Namespace(**(defaults | values | {"config": str(config)}))
    root = config.parent
    if name == "clone" and args.dir is None:
        args.dir = f"elab-clone-{args.id[0]}"
    for field in ("old", "new", "output", "dir"):
        value = getattr(args, field, None)
        if isinstance(value, str):
            path = _project_path(root, value)
            # pull の新規ターゲットはプロジェクト相対パスを YAML に保存する。
            setattr(args, field, path.relative_to(root).as_posix() if name == "pull" else str(path))
    for field in ("files", "from_docs"):
        if field in values:
            setattr(args, field, [str(_project_path(root, p)) for p in values[field]])
    if "target_ids" in values:
        args.target_ids = [p if p.isdigit() else str(_project_path(root, p)) for p in values["target_ids"]]
    if name == "pull":
        if not (args.auto or args.dir):
            raise ValueError("pull には auto=true または dir が必要です")
        args.auto = True  # dir が既存ターゲット外でも対話を避ける
    if name == "new" and args.output and (Path(args.output).suffix.lower() != ".md" or Path(args.output) == config):
        raise ValueError("output には Markdown ファイルを指定してください")
    if name == "clone":
        if clone_url:
            args.url, args.no_verify = clone_url, False
        else:
            configured = cli.load_config(config)
            default = configured.profiles.get("default")
            if not default or not default.url:
                raise ValueError("clone の接続先に既定プロファイルまたは --clone-url を指定してください")
            args.url, args.no_verify = default.url, not default.verify_ssl
    return args


def _secrets(config):
    """プロファイル・環境変数の認証情報をツール応答から除く。"""
    secrets = [os.getenv("ELABFTW_API_KEY", "").strip()]
    if config.is_file():
        raw = yaml.safe_load(_read_yaml_text(config)) or {}
        for profile in [raw.get("elabftw", {}), *(raw.get("profiles") or {}).values()]:
            if isinstance(profile, dict) and isinstance(profile.get("api_key"), str):
                secrets.append(profile["api_key"].strip())
    return tuple(set(secrets) - {""})


def _scrub(value, secrets):
    if isinstance(value, str):
        return redact(value, *secrets)
    if isinstance(value, list):
        return [_scrub(item, secrets) for item in value]
    if isinstance(value, dict):
        return {redact(key, *secrets) if key in secrets else key: _scrub(item, secrets)
                for key, item in value.items()}
    return value


def create_server(config, clone_url=None):
    from mcp import types
    from mcp.server import Server

    config = Path(config).resolve()
    server = Server("elab-doc-sync")
    bindings = _bindings()

    @server.list_tools()
    async def list_tools():
        return [types.Tool(name=name, description=op.description, inputSchema=bindings[name][0],
                           annotations=types.ToolAnnotations(readOnlyHint=not op.write))
                for name, op in OPERATIONS.items()]

    def execute(name, arguments):
        if name not in bindings:
            raise ValueError("公開されていないツールです")
        _, defaults, handler = bindings[name]
        secrets = (os.getenv("ELABFTW_API_KEY", "").strip(),)
        try:
            try:
                secrets = _secrets(config)
            except (ValueError, AttributeError, OSError, yaml.YAMLError):
                # YAML の例外には認証情報を含む設定行が載り得る。
                independent = name in {"backup_list", "restore", "log"} or (name == "clone" and clone_url)
                if not independent:
                    raise ValueError("プロジェクトの設定を読み取れません") from None
            args = _arguments(name, defaults, arguments, config, clone_url)
            result = handler(args)
        except SystemExit:
            result = CommandResult().fail("プロジェクトの設定を確認してください", 2)
        except Exception as exc:
            result = getattr(exc, "partial_result", None) or CommandResult()
            reason = "設定の YAML が不正です" if isinstance(exc, yaml.YAMLError) else error_text(exc)
            result.fail(reason, 2 if isinstance(exc, ValueError) else 1)
        payload = _scrub(result.to_dict(), secrets)
        return types.CallToolResult(isError=bool(result.exit_code), structuredContent=payload,
                                    content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))])

    @server.call_tool()
    async def call_tool(name, arguments):
        return await asyncio.to_thread(execute, name, arguments)

    return server


def main():
    parser = argparse.ArgumentParser(description="eLabFTW 同期プロジェクトの stdio MCP サーバー")
    parser.add_argument("--config", default=cli.DEFAULT_CONFIG, help="操作対象の設定ファイル")
    parser.add_argument("--clone-url", help="clone の接続先（省略時は設定ファイルの既定接続先）")
    args = parser.parse_args()
    try:
        from mcp.server.stdio import stdio_server
    except ModuleNotFoundError as exc:
        if exc.name != "mcp":
            raise
        parser.exit(2, "MCP SDK が必要です。elab-doc-sync[mcp] をインストールしてください。\n")
    server = create_server(args.config, args.clone_url)

    async def serve():
        async with stdio_server() as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())

    asyncio.run(serve())


if __name__ == "__main__":
    main()
