"""Helpers for choosing playback targets for synthesized audio."""

from __future__ import annotations


# Usage: merge user-selected speaker outputs with an optional managed virtual-microphone sink while preserving order and removing duplicates.
# Parameters: selected_output_ids - the playback outputs chosen by the user; virtual_microphone_output_id - the optional managed PipeWire sink output id that should also receive TTS audio.
# Return: a de-duplicated list of output ids that MultiOutputPlayer should target for synthesized speech playback.
def build_tts_output_device_ids(
    selected_output_ids: list[str],
    virtual_microphone_output_id: str | None = None,
) -> list[str]:
    """Return the playback output ids that should receive TTS audio, including the managed virtual mic sink when available."""

    merged_output_ids: list[str] = []
    for output_id in list(selected_output_ids) + ([virtual_microphone_output_id] if virtual_microphone_output_id else []):
        normalized_output_id = str(output_id).strip()
        if not normalized_output_id or normalized_output_id in merged_output_ids:
            continue
        merged_output_ids.append(normalized_output_id)

    return merged_output_ids


# Usage: resolve which persisted output ids should actually be used given the currently available outputs and the system default.
# Parameters: requested_output_ids - explicit persisted output ids requested by the caller; available_output_ids - output ids that are currently available from Qt; default_output_id - optional persisted id for the current system default output.
# Return: the output ids that should be opened, using the default output only when no explicit output ids were requested.
def choose_available_output_device_ids(
    requested_output_ids: list[str],
    available_output_ids: list[str],
    default_output_id: str | None = None,
) -> list[str]:
    """Return matching output ids without falling back to an unrelated default when explicit targets were requested."""

    normalized_requested_ids = [str(output_id).strip() for output_id in requested_output_ids if str(output_id).strip()]
    normalized_available_ids = [str(output_id).strip() for output_id in available_output_ids if str(output_id).strip()]
    available_id_set = set(normalized_available_ids)

    if normalized_requested_ids:
        return [output_id for output_id in normalized_requested_ids if output_id in available_id_set]

    normalized_default_output_id = str(default_output_id).strip() if default_output_id else ""
    if normalized_default_output_id and normalized_default_output_id in available_id_set:
        return [normalized_default_output_id]

    return normalized_available_ids[:1]
