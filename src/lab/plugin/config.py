from __future__ import annotations

import importlib
import importlib.util
import inspect
import tomllib
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from pathlib import Path

SUPPORTED_SCHEMA_TYPE_MAP = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
}


class PluginConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _field_hidden_from_plugin_meta(config_model: type[BaseModel], field_name: str) -> bool:
    field_info = config_model.model_fields.get(field_name)
    if field_info is None:
        return False

    extra_obj = field_info.json_schema_extra
    if not isinstance(extra_obj, dict):
        return False

    extra = cast("dict[str, object]", extra_obj)
    return bool(extra.get("plugin_meta_hidden"))


def import_plugin_module(plugin_id: str, plugin_dir: Path) -> Any:
    module_name = f"lab.plugins.{plugin_id}"
    try:
        return importlib.import_module(module_name)
    except ImportError:
        spec = importlib.util.spec_from_file_location(module_name, plugin_dir / "__init__.py")
        if spec is None or spec.loader is None:
            raise
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def get_plugin_config_model(module: Any, meta: dict[str, Any]) -> type[BaseModel] | None:
    model = getattr(module, "PLUGIN_CONFIG_MODEL", None)
    if inspect.isclass(model) and issubclass(model, BaseModel):
        return model

    entry_name = meta.get("type_config", {}).get("entry")
    if not entry_name:
        return None

    plugin_cls = getattr(module, entry_name, None)
    model = getattr(plugin_cls, "config_model", None)
    if inspect.isclass(model) and issubclass(model, BaseModel):
        return model
    return None


def validate_plugin_config(config_model: type[BaseModel], raw_config: dict[str, Any]) -> dict[str, Any]:
    validated = config_model.model_validate(raw_config)
    return validated.model_dump(mode="python", exclude_none=True)


def validate_plugin_override(plugin_id: str, plugin_dir: Path, override: dict[str, Any]) -> dict[str, Any]:
    with (plugin_dir / "plugin.toml").open("rb") as file:
        meta = tomllib.load(file)

    module = import_plugin_module(plugin_id, plugin_dir)
    config_model = get_plugin_config_model(module, meta)
    if config_model is None:
        return override

    config_defaults = meta.get("config", {})
    defaults: dict[str, Any] = cast("dict[str, Any]", config_defaults) if isinstance(config_defaults, dict) else {}
    merged: dict[str, Any] = {**defaults, **override}
    return validate_plugin_config(config_model, merged)


def build_default_plugin_config(config_model: type[BaseModel]) -> dict[str, Any]:
    defaults = config_model()
    data = defaults.model_dump(mode="python", exclude_none=True)
    return {key: value for key, value in data.items() if not _field_hidden_from_plugin_meta(config_model, key)}


def _get_str_value(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) else None


def _extract_schema_type(prop: dict[str, object]) -> str | None:
    schema_type = prop.get("type")
    if isinstance(schema_type, str):
        return schema_type
    if isinstance(schema_type, list):
        schema_type_list = cast("list[object]", schema_type)
        for item in schema_type_list:
            if isinstance(item, str) and item != "null":
                return item
    return None


def _resolve_schema_ref(prop: dict[str, object], defs: dict[str, object]) -> dict[str, object]:
    ref = _get_str_value(prop, "$ref")
    if ref is None or not ref.startswith("#/$defs/"):
        return prop

    ref_name = ref.removeprefix("#/$defs/")
    resolved = defs.get(ref_name)
    if not isinstance(resolved, dict):
        return prop
    merged = dict(cast("dict[str, object]", resolved))
    for key, value in prop.items():
        if key == "$ref":
            continue
        merged[key] = value
    return merged


def _build_field_schema(prop: dict[str, object], defs: dict[str, object]) -> dict[str, Any] | None:
    resolved_prop = _resolve_schema_ref(prop, defs)
    schema_type = _extract_schema_type(resolved_prop)
    if schema_type is None:
        return None

    description = _get_str_value(resolved_prop, "description")

    if schema_type == "array":
        items_obj = resolved_prop.get("items")
        if not isinstance(items_obj, dict):
            return None

        item_schema = _build_field_schema(cast("dict[str, object]", items_obj), defs)
        if item_schema is None:
            return None

        field_schema: dict[str, Any] = {"type": "list", "items": item_schema}
        if description:
            field_schema["description"] = description
        return field_schema

    if schema_type == "object":
        properties_obj = resolved_prop.get("properties", {})
        if not isinstance(properties_obj, dict):
            return None

        properties = cast("dict[str, object]", properties_obj)
        child_fields: dict[str, Any] = {}
        for raw_name, raw_child in properties.items():
            if not isinstance(raw_child, dict):
                continue
            child_schema = _build_field_schema(cast("dict[str, object]", raw_child), defs)
            if child_schema is not None:
                child_fields[raw_name] = child_schema

        field_schema = {"type": "object", "properties": child_fields}
        if description:
            field_schema["description"] = description
        return field_schema

    mapped_type = SUPPORTED_SCHEMA_TYPE_MAP.get(schema_type)
    if mapped_type is None:
        return None

    field_schema = {"type": mapped_type}
    if not description:
        description = _get_str_value(resolved_prop, "title")
    if description:
        field_schema["description"] = description
    minimum = resolved_prop.get("minimum")
    if minimum is not None:
        field_schema["min"] = minimum
    maximum = resolved_prop.get("maximum")
    if maximum is not None:
        field_schema["max"] = maximum
    return field_schema


def build_plugin_config_schema(config_model: type[BaseModel]) -> dict[str, dict[str, Any]]:
    json_schema = cast("dict[str, object]", config_model.model_json_schema())
    properties_obj = json_schema.get("properties", {})
    if not isinstance(properties_obj, dict):
        return {}

    defs_obj = json_schema.get("$defs", {})
    defs = cast("dict[str, object]", defs_obj) if isinstance(defs_obj, dict) else {}
    properties = cast("dict[str, object]", properties_obj)

    out: dict[str, dict[str, Any]] = {}
    for raw_name, raw_prop in properties.items():
        if not isinstance(raw_prop, dict):
            continue
        if _field_hidden_from_plugin_meta(config_model, raw_name):
            continue
        field_schema = _build_field_schema(cast("dict[str, object]", raw_prop), defs)
        if field_schema is not None:
            out[raw_name] = field_schema

    return out
