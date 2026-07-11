# copyright@https://github.com/Open-LLM-VTuber/Open-LLM-VTuber

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import chardet
from loguru import logger

# This class will only prepare the payload for the live2d model
# the process of sending the payload should be done by the caller
# This class is **Not responsible** for sending the payload to the server


class Live2dModel:
    """
    A class to represent a Live2D model. This class only prepares and stores the information of the Live2D model. It does not send anything to the frontend or server or anything.

    Attributes:
        model_dict_path (str): The path to the model dictionary file.
        live2d_model_name (str): The name of the Live2D model.
        model_info (dict[str, Any]): The information of the Live2D model.
        emo_map (dict[str, Any]): The emotion map of the Live2D model.
        emo_str (str): The string representation of the emotion map of the Live2D model.
    """

    model_dict_path: str
    live2d_model_name: str
    model_info: dict[str, Any]
    emo_map: dict[str, Any]
    emo_str: str

    def __init__(self, live2d_model_name: str, model_dict_path: str = "config/live2d_presets.json"):
        self.model_dict_path: str = model_dict_path
        self.live2d_model_name: str = live2d_model_name
        self.set_model(live2d_model_name)

    def set_model(self, model_name: str) -> None:
        """
        Set the model with its name and load the model information. This method will initialize the `self.model_info`, `self.emo_map`, and `self.emo_str` attributes.
        This method is called in the constructor.

        Parameters:
            model_name (str): The name of the live2d model.

            Returns:
            None
        """

        self.model_info = self._lookup_model_info(model_name)
        self.emo_map = {k.lower(): v for k, v in self.model_info["emotionMap"].items()}
        self.emo_key: list[str] = list(self.emo_map.keys())
        self.emo_str: str = " ".join([f"[{key}]," for key in self.emo_map.keys()])
        # emo_str is a string of the keys in the emoMap dictionary. The keys are enclosed in square brackets.
        # example: `"[fear], [anger], [disgust], [sadness], [joy], [neutral], [surprise]"`

    def _load_file_content(self, file_path: str) -> str:
        """Load the content of a file with robust encoding handling."""
        # Try common encodings first
        encodings = ["utf-8", "utf-8-sig", "gbk", "gb2312", "ascii"]

        for encoding in encodings:
            try:
                with Path(file_path).open("r", encoding=encoding) as file:
                    return file.read()
            except UnicodeDecodeError:
                continue

        # If all common encodings fail, try to detect encoding
        try:
            with Path(file_path).open("rb") as file:
                raw_data = file.read()
            detected = chardet.detect(raw_data)
            detected_encoding = detected["encoding"]

            if detected_encoding:
                try:
                    return raw_data.decode(detected_encoding)
                except UnicodeDecodeError:
                    pass
        except Exception as e:
            logger.error(f"Error detecting encoding for {file_path}: {e}")

        raise UnicodeError(f"Failed to decode {file_path} with any encoding")

    def _lookup_model_info(self, model_name: str) -> dict[str, Any]:
        """
        Find the model information from the model dictionary and return the information about the matched model.

        Parameters:
            model_name (str): The name of the live2d model.

        Returns:
            dict: The dictionary with the information of the matched model.

        Raises:
            FileNotFoundError if the model dictionary file is not found.

            json.JSONDecodeError if the model dictionary file is not a valid JSON file.

            KeyError if the model name is not found in the model dictionary.

        """

        self.live2d_model_name = model_name

        try:
            file_content = self._load_file_content(self.model_dict_path)
            model_dict = json.loads(file_content)
        except FileNotFoundError as file_e:
            logger.critical(f"Model dictionary file not found at {self.model_dict_path}.")
            raise file_e
        except json.JSONDecodeError as json_e:
            logger.critical(f"Error decoding JSON from model dictionary file at {self.model_dict_path}.")
            raise json_e
        except UnicodeError as uni_e:
            logger.critical(f"Error reading model dictionary file at {self.model_dict_path}.")
            raise uni_e
        except Exception as e:
            logger.critical(f"Error occurred while reading model dictionary file at {self.model_dict_path}.")
            raise e

        # Find the model in the model_dict
        matched_model = next((model for model in model_dict if model["name"] == model_name), None)

        if matched_model is None:
            logger.critical(f"Unable to find {model_name} in {self.model_dict_path}.")
            raise KeyError(f"{model_name} not found in model dictionary {self.model_dict_path}.")

        if "model" in matched_model or "modelPathRelative" in matched_model:
            matched_model = self._adapt_preset_to_model_info(matched_model)

        logger.info("Model Information Loaded.")

        return matched_model

    @staticmethod
    def _adapt_preset_to_model_info(preset: dict[str, Any]) -> dict[str, Any]:
        """Convert a live2d_presets.json entry to the legacy model_info dict shape."""
        info: dict[str, Any] = {}

        info["name"] = preset.get("name", "")
        if "description" in preset:
            info["description"] = preset["description"]

        model_obj = preset.get("model", {})
        if isinstance(model_obj, dict):
            for key in (
                "url",
                "kScale",
                "initialXshift",
                "initialYshift",
                "kXOffset",
                "kYOffset",
                "idleMotionGroupName",
            ):
                if key in model_obj:
                    info[key] = model_obj[key]

        for key in ("url", "kScale", "initialXshift", "initialYshift", "kXOffset", "kYOffset", "idleMotionGroupName"):
            if key not in info and key in preset:
                info[key] = preset[key]

        if "url" not in info:
            model_path_relative = preset.get("modelPathRelative", "")
            if model_path_relative:
                # Strip "static/" prefix to get the serve path, e.g.
                # "static/live2d-models/X/X.model3.json" -> "/live2d-models/X/X.model3.json"
                path = model_path_relative.removeprefix("static/")
                info["url"] = "/" + path

        expressions = preset.get("expressions")

        # Build emotionMap from expressions with role=expression (label -> name).
        # This makes the preset self-describing: no need to maintain a separate map.
        if isinstance(expressions, list):
            generated_emo_map: dict[str, str] = {}
            for exp in expressions:
                if exp.get("role") != "expression":
                    continue
                name = exp.get("name", "")
                label = exp.get("label", name)
                if name:
                    generated_emo_map[label] = name
            if generated_emo_map:
                info["emotionMap"] = generated_emo_map

        if "emotionMap" not in info and "emotionMap" in preset:
            info["emotionMap"] = preset["emotionMap"]

        if isinstance(expressions, list):
            catalog = []
            for exp in expressions:
                exp_file = exp.get("file", "")
                if not exp_file:
                    continue
                entry: dict[str, Any] = {
                    "name": exp["name"],
                    "label": exp.get("label", exp["name"]),
                    "file": exp_file,
                }
                if exp.get("hotkey"):
                    entry["hotkey"] = exp["hotkey"]
                catalog.append(entry)
            if catalog:
                info["expressionCatalog"] = catalog

        if "excludedExpressions" in preset:
            info["excludedExpressions"] = preset["excludedExpressions"]

        if isinstance(expressions, list):
            watermark_exp = next(
                (e for e in expressions if e.get("isWatermarkControl") or e.get("role") == "watermark"),
                None,
            )
            if watermark_exp is not None:
                info["defaultEmotion"] = watermark_exp["name"]
                info["_watermark_expression_name"] = watermark_exp["name"]

        if "defaultEmotion" not in info and isinstance(expressions, list):
            default_exp = next(
                (e for e in expressions if e.get("isDefaultStartup")),
                None,
            )
            if default_exp is not None:
                info["defaultEmotion"] = default_exp["name"]

        if "defaultEmotion" not in info and "defaultEmotion" in preset:
            info["defaultEmotion"] = preset["defaultEmotion"]

        # Build appearancePresets from expressions with role=appearance.
        if isinstance(expressions, list):
            appearance_presets = []
            for exp in expressions:
                if exp.get("role") != "appearance":
                    continue
                name = exp.get("name", "")
                label = exp.get("label", name)
                if name:
                    appearance_presets.append(
                        {
                            "key": label,
                            "expression": name,
                            "description": exp.get("description", ""),
                        }
                    )
            if appearance_presets:
                info["appearancePresets"] = appearance_presets

        if "appearancePresets" not in info and "appearancePresets" in preset:
            info["appearancePresets"] = preset["appearancePresets"]

        if "tapMotions" in preset:
            info["tapMotions"] = preset["tapMotions"]

        if "motionAssets" in preset:
            info["motionAssets"] = preset["motionAssets"]

        if "expressions" in preset:
            info["_preset_expressions"] = preset["expressions"]

        return info

    def extract_emotion(self, str_to_check: str) -> list:
        """
        Check the input string for any emotion keywords and return a list of values (the expression index) of the emotions found in the string.

        Parameters:
            str_to_check (str): The string to check for emotions.

        Returns:
            list: A list of values of the emotions found in the string. An empty list is returned if no emotions are found.
        """

        expression_list = []
        str_to_check = str_to_check.lower()

        i = 0
        while i < len(str_to_check):
            if str_to_check[i] != "[":
                i += 1
                continue
            for key in self.emo_map.keys():
                emo_tag = f"[{key}]"
                if str_to_check[i : i + len(emo_tag)] == emo_tag:
                    expression_list.append(self.emo_map[key])
                    i += len(emo_tag) - 1
                    break
            i += 1
        return expression_list

    def remove_emotion_keywords(self, target_str: str) -> str:
        """
        Remove the emotion keywords from the input string and return the cleaned string.

        Parameters:
            str_to_check (str): The string to check for emotions.

        Returns:
            str: The cleaned string with the emotion keywords removed.
        """

        lower_str = target_str.lower()

        for key in self.emo_map.keys():
            lower_key = f"[{key}]".lower()
            while lower_key in lower_str:
                start_index = lower_str.find(lower_key)
                end_index = start_index + len(lower_key)
                target_str = target_str[:start_index] + target_str[end_index:]
                lower_str = lower_str[:start_index] + lower_str[end_index:]
        return target_str
