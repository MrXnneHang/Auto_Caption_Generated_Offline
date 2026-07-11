from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeGuard, cast

from pydantic import Field, field_validator, model_validator

from lab.plugin.config import PluginConfigModel
from lab.tools.base import BuiltinTool
from lab.tools.plugin import PromptSegment, ToolPlugin
from lab.tools.types import AgentContext, ToolResult

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

IdleMode = Literal["random", "random_no_repeat"]
DEFAULT_IDLE_STATES = ("listening", "speaking")
DEFAULT_MIXER_LAYER_WEIGHTS = {
    "idle_layer": 1.0,
    "speech_layer": 1.0,
    "backend_pose_layer": 1.0,
    "mouse_attention_layer": 0.35,
}


class AppearancePreset(PluginConfigModel):
    key: Annotated[str, Field(description="可切换的外观 key")]
    description: Annotated[str, Field(default="", description="该外观的说明文案")]

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("appearance_presets[].key must not be empty")
        return normalized


class IdleClip(PluginConfigModel):
    id: Annotated[str, Field(description="待机动作的唯一 ID，供状态分配引用。")]
    url: Annotated[str, Field(description="motion3.json 的相对路径或 URL。")]
    weight: Annotated[
        float,
        Field(
            default=1.0,
            ge=0,
            description="随机抽取权重，可选，需大于等于 0。",
        ),
    ]

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("idle_clips[].id must not be empty")
        return normalized

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("idle_clips[].url must not be empty")
        return normalized


class IdleAssignment(PluginConfigModel):
    mode: Annotated[
        IdleMode,
        Field(
            default="random_no_repeat",
            description="播放方式：`random` 或 `random_no_repeat`。",
        ),
    ]
    clip_ids: Annotated[
        list[str],
        Field(
            default_factory=list,
            description="状态可用的动作 ID 列表，引用上方 idle_clips 中的 id。",
        ),
    ]

    @field_validator("clip_ids")
    @classmethod
    def validate_clip_ids(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        normalized: list[str] = []
        for clip_id in value:
            trimmed = clip_id.strip()
            if not trimmed or trimmed in seen:
                continue
            seen.add(trimmed)
            normalized.append(trimmed)
        return normalized


class ListeningIdleAssignment(IdleAssignment):
    clip_ids: Annotated[
        list[Annotated[str, Field(description="动作 ID。")]],
        Field(
            default_factory=list,
            description="listening 状态可用的动作 ID 列表，引用上方 idle_clips 中的 id。",
        ),
    ]


class SpeakingIdleAssignment(IdleAssignment):
    clip_ids: Annotated[
        list[Annotated[str, Field(description="动作 ID。")]],
        Field(
            default_factory=list,
            description="speaking 状态可用的动作 ID 列表，引用上方 idle_clips 中的 id。",
        ),
    ]


class MixerStateWeights(PluginConfigModel):
    idle_layer: Annotated[
        float,
        Field(default=1.0, ge=0, description="待机层权重。"),
    ]
    speech_layer: Annotated[
        float,
        Field(default=1.0, ge=0, description="说话层权重。"),
    ]
    backend_pose_layer: Annotated[
        float,
        Field(default=1.0, ge=0, description="后端姿态层权重。用于 actions.pose / pose_patch 等后端姿态输入。"),
    ]
    mouse_attention_layer: Annotated[
        float,
        Field(default=0.35, ge=0, description="鼠标注意力层权重。"),
    ]


class IdleAssignmentsByState(PluginConfigModel):
    listening: Annotated[
        ListeningIdleAssignment,
        Field(
            default_factory=lambda: ListeningIdleAssignment(mode="random_no_repeat", clip_ids=[]),
            description="角色处于 listening 状态时的待机动作配置。",
        ),
    ]
    speaking: Annotated[
        SpeakingIdleAssignment,
        Field(
            default_factory=lambda: SpeakingIdleAssignment(mode="random_no_repeat", clip_ids=[]),
            description="角色处于 speaking 状态时的待机动作配置。",
        ),
    ]


class StateClip(PluginConfigModel):
    url: Annotated[str, Field(description="motion3.json 的相对路径或 URL。")]

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("states[].clips[].url must not be empty")
        return normalized


class StateConfig(PluginConfigModel):
    mode: Annotated[
        IdleMode,
        Field(default="random_no_repeat", description="播放方式：random 或 random_no_repeat。"),
    ]
    clips: Annotated[
        list[StateClip],
        Field(default_factory=list, description="该状态使用的待机动作片段列表。"),
    ]
    idle_layer: Annotated[float, Field(default=1.0, ge=0, description="待机层权重。")]
    speech_layer: Annotated[float, Field(default=1.0, ge=0, description="说话层权重。")]
    backend_pose_layer: Annotated[float, Field(default=1.0, ge=0, description="后端姿态层权重。")]
    mouse_attention_layer: Annotated[float, Field(default=0.35, ge=0, description="鼠标注意力层权重。")]


class StatesConfig(PluginConfigModel):
    listening: Annotated[
        StateConfig,
        Field(default_factory=StateConfig, description="listening 状态配置。"),
    ]
    speaking: Annotated[
        StateConfig,
        Field(default_factory=StateConfig, description="speaking 状态配置。"),
    ]


class MixerWeightsByStateConfig(PluginConfigModel):
    listening: Annotated[
        MixerStateWeights,
        Field(
            default_factory=lambda: MixerStateWeights(
                idle_layer=DEFAULT_MIXER_LAYER_WEIGHTS["idle_layer"],
                speech_layer=DEFAULT_MIXER_LAYER_WEIGHTS["speech_layer"],
                backend_pose_layer=DEFAULT_MIXER_LAYER_WEIGHTS["backend_pose_layer"],
                mouse_attention_layer=DEFAULT_MIXER_LAYER_WEIGHTS["mouse_attention_layer"],
            ),
            description="listening 状态下的 mixer 权重。",
        ),
    ]
    speaking: Annotated[
        MixerStateWeights,
        Field(
            default_factory=lambda: MixerStateWeights(
                idle_layer=DEFAULT_MIXER_LAYER_WEIGHTS["idle_layer"],
                speech_layer=DEFAULT_MIXER_LAYER_WEIGHTS["speech_layer"],
                backend_pose_layer=DEFAULT_MIXER_LAYER_WEIGHTS["backend_pose_layer"],
                mouse_attention_layer=DEFAULT_MIXER_LAYER_WEIGHTS["mouse_attention_layer"],
            ),
            description="speaking 状态下的 mixer 权重。",
        ),
    ]


def _default_idle_assignments() -> IdleAssignmentsByState:
    return IdleAssignmentsByState(
        listening=ListeningIdleAssignment(mode="random_no_repeat", clip_ids=[]),
        speaking=SpeakingIdleAssignment(mode="random_no_repeat", clip_ids=[]),
    )


def _default_mixer_weights_by_state() -> MixerWeightsByStateConfig:
    return MixerWeightsByStateConfig(
        listening=MixerStateWeights(
            idle_layer=DEFAULT_MIXER_LAYER_WEIGHTS["idle_layer"],
            speech_layer=DEFAULT_MIXER_LAYER_WEIGHTS["speech_layer"],
            backend_pose_layer=DEFAULT_MIXER_LAYER_WEIGHTS["backend_pose_layer"],
            mouse_attention_layer=DEFAULT_MIXER_LAYER_WEIGHTS["mouse_attention_layer"],
        ),
        speaking=MixerStateWeights(
            idle_layer=DEFAULT_MIXER_LAYER_WEIGHTS["idle_layer"],
            speech_layer=DEFAULT_MIXER_LAYER_WEIGHTS["speech_layer"],
            backend_pose_layer=DEFAULT_MIXER_LAYER_WEIGHTS["backend_pose_layer"],
            mouse_attention_layer=DEFAULT_MIXER_LAYER_WEIGHTS["mouse_attention_layer"],
        ),
    )


class Live2DControlPluginConfig(PluginConfigModel):
    appearance_presets: Annotated[
        list[AppearancePreset],
        Field(
            default_factory=list,
            description="可切换的 Live2D 外观预设列表。需要根据 live2d_presets.json 的 emotionMap 实际情况写 key name。",
        ),
    ]
    states: Annotated[
        StatesConfig,
        Field(
            default_factory=StatesConfig,
            description="按状态配置待机动作与 Pose Mixer 权重（推荐方式）。",
        ),
    ]
    # ── Legacy fields kept for backward compatibility ──────────────────────────
    idle_clips: Annotated[
        list[IdleClip],
        Field(
            default_factory=list,
            description="Legacy: 所有可用的待机动作片段。请改用 states。",
            json_schema_extra={"plugin_meta_hidden": True},
        ),
    ]
    idle_assignments: Annotated[
        IdleAssignmentsByState,
        Field(
            default_factory=_default_idle_assignments,
            description="Legacy: 不同运行状态下使用哪些待机动作。请改用 states。",
            json_schema_extra={"plugin_meta_hidden": True},
        ),
    ]
    idle_banks: Annotated[
        dict[str, dict[str, Any]],
        Field(
            default_factory=dict,
            description="Legacy: recorded idle banks keyed by state name. Prefer states.",
            json_schema_extra={"plugin_meta_hidden": True},
        ),
    ]
    mixer_weights_by_state: Annotated[
        MixerWeightsByStateConfig,
        Field(
            default_factory=_default_mixer_weights_by_state,
            description="Legacy: 前端 Pose Mixer 在不同状态下的各层权重。请改用 states。",
            json_schema_extra={"plugin_meta_hidden": True},
        ),
    ]

    @model_validator(mode="after")
    def validate_unique_keys(self) -> Live2DControlPluginConfig:
        seen: set[str] = set()
        for preset in self.appearance_presets:
            if preset.key in seen:
                raise ValueError(f"appearance_presets contains duplicate key: {preset.key}")
            seen.add(preset.key)

        clip_seen: set[str] = set()
        for clip in self.idle_clips:
            if clip.id in clip_seen:
                raise ValueError(f"idle_clips contains duplicate id: {clip.id}")
            clip_seen.add(clip.id)
        return self


PLUGIN_CONFIG_MODEL = Live2DControlPluginConfig


@dataclass(frozen=True)
class AppearanceOption:
    expression: str
    description: str = ""


_DEFAULT_APPEARANCE_KEY = "默认造型"
_DEFAULT_APPEARANCE_EXPRESSION = "__reset__"


class _ListLive2DAppearancesTool(BuiltinTool):
    name = "list_live2d_appearances"
    description = "列出当前 Live2D 模型可用的持久形态/外观选项（发型预设、部件显隐等）"
    usage_hint = "当用户询问可以切换什么形态、发型、外观，或询问某个造型的区别时调用"

    def __init__(self, appearance_options: dict[str, AppearanceOption]) -> None:
        self._appearance_options = appearance_options

    def get_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        }

    async def execute(self, args: dict[str, Any], ctx: AgentContext) -> ToolResult:
        del args, ctx
        if not self._appearance_options:
            return ToolResult(ok=False, text="", error="当前模型没有可用的持久形态选项")

        lines = ["可用形态:"]
        for display_name, option in self._appearance_options.items():
            line = f"- {display_name} -> {option.expression}"
            if option.description:
                line += f" | 说明: {option.description}"
            lines.append(line)

        return ToolResult(ok=True, text="\n".join(lines))


class _SetLive2DAppearanceTool(BuiltinTool):
    name = "set_live2d_appearance"
    description = "切换 Live2D 模型的持久形态/外观（如发型预设、显隐部件等）。切换后持续保持直到下次切换。"
    usage_hint = "当需要切换形态、发型、显隐部件时调用"

    def __init__(self, appearance_options: dict[str, AppearanceOption]) -> None:
        self._appearance_options = appearance_options

    def get_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "appearance_key": {
                            "type": "string",
                            "description": "要切换到的形态名称（中文 key）",
                        }
                    },
                    "required": ["appearance_key"],
                },
            },
        }

    async def execute(self, args: dict[str, Any], ctx: AgentContext) -> ToolResult:
        key = args.get("appearance_key")
        if not isinstance(key, str) or key not in self._appearance_options:
            available = list(self._appearance_options.keys())
            return ToolResult(ok=False, text="", error=f"无效的形态 key: {key}，可用: {available}")

        expression_value = self._appearance_options[key].expression
        ws_send = ctx.extra.get("websocket_send")
        if callable(ws_send):
            websocket_send = cast("Callable[[str], Awaitable[None]]", ws_send)
            payload: dict[str, Any] = {"type": "set-live2d-appearance"}
            if expression_value == _DEFAULT_APPEARANCE_EXPRESSION:
                payload["expression"] = None
            else:
                payload["expression"] = expression_value
            await websocket_send(json.dumps(payload))

        return ToolResult(ok=True, text=f"已切换形态: {key}")


class Live2DControlPlugin(ToolPlugin):
    name = "live2d_control"
    config_model = Live2DControlPluginConfig
    description = "控制 Live2D 模型的持久形态切换"

    def __init__(
        self,
        appearance_presets: list[dict[str, str]] | list[AppearancePreset] | None = None,
        states: dict[str, Any] | StatesConfig | None = None,
        idle_clips: list[dict[str, Any]] | list[IdleClip] | None = None,
        idle_assignments: dict[str, dict[str, Any]] | IdleAssignmentsByState | None = None,
        idle_banks: dict[str, dict[str, Any]] | None = None,
        mixer_weights_by_state: dict[str, dict[str, Any]] | MixerWeightsByStateConfig | None = None,
    ) -> None:
        self._appearance_presets = [self._coerce_preset(preset) for preset in appearance_presets or []]
        self._appearance_options: dict[str, AppearanceOption] = {}

        if self._states_has_clips(states):
            self._idle_banks, self._mixer_weights_by_state = self._build_from_states(states)
            for s in DEFAULT_IDLE_STATES:
                self._mixer_weights_by_state.setdefault(s, dict(DEFAULT_MIXER_LAYER_WEIGHTS))
        else:
            self._idle_banks = self._build_idle_banks_from_idle_catalog(
                idle_clips=idle_clips or [],
                idle_assignments=idle_assignments or {},
                legacy_idle_banks=idle_banks or {},
            )
            self._mixer_weights_by_state = self._normalize_mixer_weights_by_state(mixer_weights_by_state or {})

    @staticmethod
    def _coerce_preset(raw_preset: dict[str, str] | AppearancePreset) -> AppearancePreset:
        if isinstance(raw_preset, AppearancePreset):
            return raw_preset
        return AppearancePreset.model_validate(raw_preset)

    @staticmethod
    def _normalize_idle_mode(raw_mode: Any) -> IdleMode:
        return "random" if raw_mode == "random" else "random_no_repeat"

    @staticmethod
    def _coerce_idle_clip(raw_clip: dict[str, Any] | IdleClip) -> IdleClip:
        if isinstance(raw_clip, IdleClip):
            return raw_clip
        return IdleClip.model_validate(raw_clip)

    @staticmethod
    def _coerce_idle_assignment(raw_assignment: dict[str, Any] | IdleAssignment) -> IdleAssignment:
        if isinstance(raw_assignment, IdleAssignment):
            return raw_assignment
        return IdleAssignment.model_validate(raw_assignment)

    @staticmethod
    def _coerce_mixer_state_weights(raw_weights: dict[str, Any] | MixerStateWeights) -> MixerStateWeights:
        if isinstance(raw_weights, MixerStateWeights):
            return raw_weights
        return MixerStateWeights.model_validate(raw_weights)

    @classmethod
    def _build_from_states(
        cls,
        states: StatesConfig | dict[str, Any],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, float]]]:
        if isinstance(states, StatesConfig):
            states_items: dict[str, StateConfig] = {
                "listening": states.listening,
                "speaking": states.speaking,
            }
        else:
            states_items = {k: StateConfig.model_validate(v) for k, v in states.items()}

        idle_banks: dict[str, dict[str, Any]] = {}
        mixer_weights: dict[str, dict[str, float]] = {}

        for state_name, sc in states_items.items():
            clips = [{"url": c.url} for c in sc.clips]
            if clips:
                idle_banks[state_name] = {
                    "mode": cls._normalize_idle_mode(sc.mode),
                    "clips": clips,
                }
            mixer_weights[state_name] = {
                "idle_layer": float(sc.idle_layer),
                "speech_layer": float(sc.speech_layer),
                "backend_pose_layer": float(sc.backend_pose_layer),
                "mouse_attention_layer": float(sc.mouse_attention_layer),
            }

        return idle_banks, mixer_weights

    @classmethod
    def _states_has_clips(
        cls, states: StatesConfig | dict[str, Any] | None
    ) -> TypeGuard[StatesConfig | dict[str, Any]]:
        if states is None:
            return False
        if isinstance(states, StatesConfig):
            return bool(states.listening.clips or states.speaking.clips)
        return any((v.get("clips") if isinstance(v, dict) else getattr(v, "clips", None)) for v in states.values())

    @classmethod
    def _normalize_idle_clips(cls, raw_idle_clips: list[dict[str, Any]] | list[IdleClip]) -> dict[str, dict[str, Any]]:
        normalized: dict[str, dict[str, Any]] = {}
        for raw_clip in raw_idle_clips:
            clip = cls._coerce_idle_clip(raw_clip)
            normalized[clip.id] = {
                "id": clip.id,
                "url": clip.url,
                "weight": max(0.0, float(clip.weight)),
            }
        return normalized

    @classmethod
    def _normalize_idle_assignments(
        cls,
        raw_idle_assignments: dict[str, dict[str, Any]] | dict[str, IdleAssignment] | IdleAssignmentsByState,
    ) -> dict[str, dict[str, Any]]:
        if isinstance(raw_idle_assignments, IdleAssignmentsByState):
            raw_idle_assignments = raw_idle_assignments.model_dump(mode="python")

        normalized: dict[str, dict[str, Any]] = {}
        for state_name, raw_assignment in raw_idle_assignments.items():
            state_key = state_name.strip()
            if not state_key:
                continue
            assignment = cls._coerce_idle_assignment(raw_assignment)
            normalized[state_key] = {
                "mode": cls._normalize_idle_mode(assignment.mode),
                "clip_ids": assignment.clip_ids,
            }
        return normalized

    @classmethod
    def _normalize_idle_banks(cls, raw_idle_banks: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        normalized: dict[str, dict[str, Any]] = {}
        for state_name, raw_bank in raw_idle_banks.items():
            key = state_name.strip()
            if not key:
                continue

            raw_clips_obj = raw_bank.get("clips")
            if not isinstance(raw_clips_obj, list):
                continue
            raw_clips = cast("list[object]", raw_clips_obj)

            clips: list[dict[str, Any]] = []
            for item_obj in raw_clips:
                if not isinstance(item_obj, dict):
                    continue

                item = cast("dict[str, object]", item_obj)
                url_obj = item.get("url")
                if not isinstance(url_obj, str):
                    continue
                url = url_obj.strip()
                if not url:
                    continue

                clip: dict[str, Any] = {"url": url}
                clip_id_obj = item.get("id")
                if isinstance(clip_id_obj, str):
                    clip_id = clip_id_obj.strip()
                    if clip_id:
                        clip["id"] = clip_id

                weight_obj = item.get("weight")
                if isinstance(weight_obj, (int, float)):
                    clip["weight"] = max(0.0, float(weight_obj))
                clips.append(clip)

            if not clips:
                continue

            normalized[key] = {
                "clips": clips,
                "mode": cls._normalize_idle_mode(raw_bank.get("mode")),
            }
        return normalized

    @classmethod
    def _build_idle_banks_from_idle_catalog(
        cls,
        idle_clips: list[dict[str, Any]] | list[IdleClip],
        idle_assignments: dict[str, dict[str, Any]] | dict[str, IdleAssignment] | IdleAssignmentsByState,
        legacy_idle_banks: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        clips_by_id = cls._normalize_idle_clips(idle_clips)
        assignments = cls._normalize_idle_assignments(idle_assignments)

        resolved_banks: dict[str, dict[str, Any]] = {}
        for state, assignment in assignments.items():
            clip_ids_obj = assignment.get("clip_ids")
            if not isinstance(clip_ids_obj, list):
                continue
            clip_ids = cast("list[object]", clip_ids_obj)

            selected_clips: list[dict[str, Any]] = []
            for clip_id_obj in clip_ids:
                if not isinstance(clip_id_obj, str):
                    continue
                clip_id = clip_id_obj.strip()
                if not clip_id:
                    continue
                clip = clips_by_id.get(clip_id)
                if clip is not None:
                    selected_clips.append(clip)

            if not selected_clips:
                continue

            resolved_banks[state] = {
                "mode": cls._normalize_idle_mode(assignment.get("mode")),
                "clips": selected_clips,
            }

        if resolved_banks:
            return resolved_banks

        return cls._normalize_idle_banks(legacy_idle_banks)

    @classmethod
    def _normalize_mixer_weights_by_state(
        cls,
        raw_weights_by_state: dict[str, dict[str, Any]] | MixerWeightsByStateConfig,
    ) -> dict[str, dict[str, float]]:
        if isinstance(raw_weights_by_state, MixerWeightsByStateConfig):
            raw_weights_by_state = raw_weights_by_state.model_dump(mode="python")

        normalized: dict[str, dict[str, float]] = {}
        for state_name, raw_weights in raw_weights_by_state.items():
            state_key = state_name.strip()
            if not state_key:
                continue
            weights = cls._coerce_mixer_state_weights(raw_weights)
            normalized[state_key] = {
                "idle_layer": float(weights.idle_layer),
                "speech_layer": float(weights.speech_layer),
                "backend_pose_layer": float(weights.backend_pose_layer),
                "mouse_attention_layer": float(weights.mouse_attention_layer),
            }

        for state in DEFAULT_IDLE_STATES:
            normalized.setdefault(state, dict(DEFAULT_MIXER_LAYER_WEIGHTS))
        return normalized

    async def on_register(self, ctx: AgentContext) -> bool:
        # ── Resolve motion assets (name -> url lookup) ────────────────────────
        motion_asset_map: dict[str, str] = {}

        # Step 1: motionAssets provides bare filenames as baseline
        raw_motion_assets = ctx.extra.get("live2d_motion_assets", [])
        if isinstance(raw_motion_assets, list):
            for asset in cast("list[dict[str, Any]]", raw_motion_assets):
                asset_name = str(asset.get("name", ""))
                asset_file = str(asset.get("file", ""))
                if asset_name and asset_file:
                    motion_asset_map[asset_name] = asset_file

        # Step 2: importedMotions overrides with full repo-relative paths
        raw_imported = ctx.extra.get("live2d_imported_motions", [])
        if isinstance(raw_imported, list):
            for entry in cast("list[dict[str, Any]]", raw_imported):
                name = str(entry.get("name", ""))
                path = str(entry.get("path", ""))
                if name and path:
                    # Convert repo-relative path to server-relative URL:
                    #   "static/live2d-models/调用版/idle1.motion3.json"
                    #   → "/live2d-models/调用版/idle1.motion3.json"
                    url_path = path.replace("\\", "/")
                    if url_path.startswith("static/"):
                        url_path = "/" + url_path[len("static/") :]
                    motion_asset_map[name] = url_path

        # Rebuild idle banks: resolve name references in clips against motion assets
        if motion_asset_map:
            self._idle_banks = self._resolve_idle_banks_with_assets(self._idle_banks, motion_asset_map)

        ctx.extra["live2d_idle_banks"] = self._idle_banks
        ctx.extra["live2d_mixer_weights_by_state"] = self._mixer_weights_by_state

        # ── Four-layer management from preset expressions ─────────────────────
        raw_preset_expressions = ctx.extra.get("live2d_preset_expressions", [])
        if isinstance(raw_preset_expressions, list) and raw_preset_expressions:
            preset_expressions = cast("list[dict[str, Any]]", raw_preset_expressions)
            # Layer 1: emotionMap (role=expression) — label -> name
            emo_map: dict[str, str] = {}
            for exp in preset_expressions:
                if exp.get("role") != "expression":
                    continue
                name = str(exp.get("name", ""))
                label = str(exp.get("label", name))
                if name:
                    emo_map[label.lower()] = name
            if emo_map:
                ctx.extra["live2d_emo_map"] = emo_map

            # Layer 2: appearancePresets (role=appearance)
            self._appearance_options = {}
            for exp in preset_expressions:
                if exp.get("role") != "appearance":
                    continue
                name = str(exp.get("name", ""))
                label = str(exp.get("label", name))
                description = str(exp.get("description", ""))
                if name and label:
                    self._appearance_options[label] = AppearanceOption(
                        expression=name,
                        description=description,
                    )

            # Inject "默认造型" reset option when there are appearance presets
            if self._appearance_options:
                self._appearance_options[_DEFAULT_APPEARANCE_KEY] = AppearanceOption(
                    expression=_DEFAULT_APPEARANCE_EXPRESSION,
                    description="恢复模型启动时的初始造型，清除所有持久外观切换",
                )

            # Layer 3: watermark (role=watermark)
            watermark_exp = next(
                (e for e in preset_expressions if e.get("isWatermarkControl") or e.get("role") == "watermark"),
                None,
            )
            if watermark_exp is not None:
                ctx.extra["live2d_watermark_expression"] = str(watermark_exp.get("name", ""))

            # Layer 4: default expression (role=system + isDefaultStartup)
            default_exp = next(
                (e for e in preset_expressions if e.get("isDefaultStartup")),
                None,
            )
            if default_exp is not None:
                ctx.extra["live2d_default_expression"] = str(default_exp.get("name", ""))

        else:
            # Fallback: legacy path using ctx.extra["live2d_emo_map"] from Live2dModel
            raw_emo_map = ctx.extra.get("live2d_emo_map", {})
            if isinstance(raw_emo_map, dict):
                typed_emo_map = cast("dict[object, object]", raw_emo_map)
                emo_map_str = {
                    key: value
                    for key, value in typed_emo_map.items()
                    if isinstance(key, str) and isinstance(value, str)
                }

                preset_appearance_presets = ctx.extra.get("live2d_appearance_presets")
                if isinstance(preset_appearance_presets, list) and preset_appearance_presets:
                    appearance_list = cast("list[dict[str, str]]", preset_appearance_presets)
                    self._appearance_options = {}
                    for raw_preset in appearance_list:
                        key = raw_preset.get("key", "")
                        expression = raw_preset.get("expression", "")
                        description = raw_preset.get("description", "")
                        if key and expression and expression in emo_map_str:
                            self._appearance_options[key] = AppearanceOption(
                                expression=emo_map_str[expression],
                                description=description or "",
                            )
                else:
                    self._appearance_options = {
                        preset.key: AppearanceOption(
                            expression=emo_map_str[preset.key],
                            description=preset.description,
                        )
                        for preset in self._appearance_presets
                        if preset.key in emo_map_str
                    }
            else:
                self._appearance_options = {}

        # Inject default appearance reset for legacy path as well
        if self._appearance_options and _DEFAULT_APPEARANCE_KEY not in self._appearance_options:
            self._appearance_options[_DEFAULT_APPEARANCE_KEY] = AppearanceOption(
                expression=_DEFAULT_APPEARANCE_EXPRESSION,
                description="恢复模型启动时的初始造型，清除所有持久外观切换",
            )

        return bool(self._appearance_options or self._idle_banks or self._mixer_weights_by_state)

    @staticmethod
    def _resolve_idle_banks_with_assets(
        idle_banks: dict[str, dict[str, Any]],
        motion_asset_map: dict[str, str],
    ) -> dict[str, dict[str, Any]]:
        """Resolve name-only clip references in idle banks against motion assets."""
        resolved: dict[str, dict[str, Any]] = {}
        for state_name, bank in idle_banks.items():
            clips = cast("list[dict[str, str] | str]", bank.get("clips", []))
            resolved_clips: list[dict[str, str]] = []
            for clip in clips:
                if isinstance(clip, dict) and "url" in clip:
                    url = clip["url"]
                    if "/" not in url and "\\" not in url and "." not in url:
                        actual_url = motion_asset_map.get(url, url)
                        resolved_clips.append({"url": actual_url})
                    else:
                        resolved_clips.append({"url": url})
                elif isinstance(clip, str):
                    actual_url = motion_asset_map.get(clip, clip)
                    resolved_clips.append({"url": actual_url})
                else:
                    resolved_clips.append({"url": str(clip)})
            resolved[state_name] = {**bank, "clips": resolved_clips}
        return resolved

    def get_tools(self) -> list[BuiltinTool]:
        return [
            _ListLive2DAppearancesTool(self._appearance_options),
            _SetLive2DAppearanceTool(self._appearance_options),
        ]

    def get_prompt_segments(self) -> list[PromptSegment]:
        content_lines = [
            "你可以通过工具查看和切换角色的外观形态（如发型、部件显隐）。",
            "形态切换是持久的，不需要在每句话里重复。",
            "当用户询问某个造型是什么样、适合什么区别或想比较多个造型时，优先参考下面的造型说明，不要臆测未配置的信息。",
        ]

        if self._appearance_options:
            content_lines.append("当前可切换造型说明:")
            for display_name, option in self._appearance_options.items():
                if option.description:
                    content_lines.append(f"- {display_name}: {option.description}")
                else:
                    content_lines.append(f"- {display_name}: 未提供额外说明，仅按名称理解")

        return [
            PromptSegment(
                name="live2d_control",
                content="\n".join(content_lines),
            )
        ]
