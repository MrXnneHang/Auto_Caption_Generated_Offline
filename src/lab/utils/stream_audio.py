from __future__ import annotations

import base64
from typing import TYPE_CHECKING, TypedDict

from loguru import logger
from pydub import AudioSegment
from pydub.utils import make_chunks

if TYPE_CHECKING:
    from lab.agent.output_types import Actions, ActionsDict, DisplayText, DisplayTextDict


class AudioPayload(TypedDict):
    type: str
    audio: str | None
    volumes: list[float]
    slice_length: int
    display_text: DisplayTextDict
    actions: ActionsDict | None
    forwarded: bool
    turn_id: str | None
    tts_error: bool


def _get_volume_by_chunks(audio: AudioSegment, chunk_length_ms: int) -> list[float]:
    """
    Calculate the normalized volume (RMS) for each chunk of the audio.

    Parameters:
        audio (AudioSegment): The audio segment to process.
        chunk_length_ms (int): The length of each audio chunk in milliseconds.

    Returns:
        list[float]: Normalized volumes for each chunk.
    """
    chunks: list[AudioSegment] = make_chunks(audio, chunk_length_ms)
    volumes: list[float] = [chunk.rms for chunk in chunks]
    max_volume = max(volumes)
    if max_volume == 0:
        raise ValueError("Audio is empty or all zero.")
    return [volume / max_volume for volume in volumes]


def prepare_audio_payload(
    audio_path: str | None,
    display_text: DisplayText,
    actions: Actions | None = None,
    chunk_length_ms: int = 20,
    forwarded: bool = False,
    turn_id: str | None = None,
    tts_error: bool = False,
) -> AudioPayload:
    """
    Prepares the audio payload for sending to a broadcast endpoint.
    If audio_path is None, returns a payload with audio=None for silent display.

    Parameters:
        audio_path (str | None): The path to the audio file to be processed, or None for silent display
        chunk_length_ms (int): The length of each audio chunk in milliseconds
        display_text (DisplayText, optional): Text to be displayed with the audio
        actions (Actions, optional): Actions associated with the audio

    Returns:
        dict: The audio payload to be sent
    """

    logger.info(f"display_text: {display_text}")

    if not audio_path:
        # Return payload for silent display
        return {
            "type": "audio",
            "audio": None,
            "volumes": [0.0],  # No audio, so volume is zero
            "slice_length": chunk_length_ms,
            "display_text": display_text.to_dict(),
            "actions": actions.to_dict() if actions else None,
            "forwarded": forwarded,
            "turn_id": turn_id,
            "tts_error": tts_error,
        }

    try:
        audio: AudioSegment | None = AudioSegment.from_file(audio_path)
        if not isinstance(audio, AudioSegment):
            raise TypeError(f"Expected audio to be AudioSegment, got {type(audio)}")
        audio_bytes: bytes = audio.export(format="wav").read()
        if not isinstance(audio_bytes, bytes):
            raise TypeError(f"Expected audio_bytes to be bytes, got {type(audio_bytes)}")
    except Exception as e:
        raise ValueError(f"Error loading or converting generated audio file to wav file '{audio_path}': {e}") from e
    audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
    volumes = _get_volume_by_chunks(audio, chunk_length_ms)
    return {
        "type": "audio",
        "audio": audio_base64,
        "volumes": volumes,
        "slice_length": chunk_length_ms,
        "display_text": display_text.to_dict(),
        "actions": actions.to_dict() if actions else None,
        "forwarded": forwarded,
        "turn_id": turn_id,
        "tts_error": tts_error,
    }


# Example usage:
# payload, duration = prepare_audio_payload("path/to/audio.mp3", display_text="Hello", expression_list=[0,1,2])
