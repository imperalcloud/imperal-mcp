"""Imperal SDK · Input UI Components."""
from __future__ import annotations

from typing import Any
from .base import UINode, UIAction

# The single source of truth for the allowed ui.Input HTML input types.
# Consumed by Input() validation (here), the manifest schema (Ф2), the
# reference generator (Ф1), and the docs <SdkRef> (Ф3). Add new types here only.
INPUT_TYPES = ("text", "password", "email", "number", "url")


def Input(
    placeholder: str = "",
    on_submit: UIAction | None = None,
    value: str = "",
    param_name: str = "value",
    type: str = "text",
) -> UINode:
    """Text input field. on_submit fires on Enter, value merged as param_name.

    ``type`` (v4.2.6+) is a hint to the Panel renderer for native HTML input
    behaviour: ``"text"`` (default), ``"password"`` (browser-blind, no echo),
    ``"email"``, ``"number"``, ``"url"``. Prefer ``ui.Password(...)`` for
    credential entry — it's a thin convenience wrapper that pins type for
    federal EXT-SECRETS-V1 UIs.
    """
    if type not in INPUT_TYPES:
        raise ValueError(f"ui.Input type must be one of {INPUT_TYPES}, got {type!r}")
    props: dict[str, Any] = {"placeholder": placeholder, "value": value, "param_name": param_name}
    if type and type != "text":
        props["type"] = type
    if on_submit: props["on_submit"] = on_submit
    return UINode(type="Input", props=props)


def Password(
    placeholder: str = "paste value…",
    on_submit: UIAction | None = None,
    value: str = "",
    param_name: str = "value",
) -> UINode:
    """Password input — browser-blind, no echo, autocomplete='new-password'.

    EXT-SECRETS-V1 (federal v4.2.6+) — the canonical credential-entry primitive.
    Renders as ``<input type="password" autocomplete="new-password">`` in the
    Panel UI so values are visually masked while the user types. Submitted
    value rides into the action as ``param_name`` (default ``"value"``); use
    inside ``ui.Form(defaults={...})`` to attach hidden context fields like
    ``app_id`` and ``name``.

    Federal note: type=password is a defence against shoulder-surfing, NOT a
    security control. The plaintext still travels in the POST body to the
    server, which is the only correctness boundary. Audit chokepoint + Vault
    transit are what make this federal-grade.
    """
    return Input(
        placeholder=placeholder,
        on_submit=on_submit,
        value=value,
        param_name=param_name,
        type="password",
    )


def Form(
    children: list[UINode],
    action: str = "",
    submit_label: str = "Submit",
    defaults: dict | None = None,
) -> UINode:
    """Form container — collects child input values and submits as one action."""
    props: dict[str, Any] = {"children": children, "submit_label": submit_label}
    if action: props["action"] = action
    if defaults: props["defaults"] = defaults
    return UINode(type="Form", props=props)


def Select(
    options: list[dict],
    value: str = "",
    placeholder: str = "",
    on_change: UIAction | None = None,
    param_name: str = "value",
) -> UINode:
    """Single-select dropdown. Each option: {"value", "label"}."""
    props: dict[str, Any] = {"options": options, "value": value, "param_name": param_name}
    if placeholder: props["placeholder"] = placeholder
    if on_change: props["on_change"] = on_change
    return UINode(type="Select", props=props)


def MultiSelect(
    options: list[dict],
    values: list[str] | None = None,
    placeholder: str = "",
    param_name: str = "values",
) -> UINode:
    """Multi-select dropdown. Each option: {"value", "label"}."""
    props: dict[str, Any] = {"options": options, "values": values or [], "param_name": param_name}
    if placeholder: props["placeholder"] = placeholder
    return UINode(type="MultiSelect", props=props)


def Toggle(
    label: str = "",
    value: bool = False,
    on_change: UIAction | None = None,
    param_name: str = "enabled",
) -> UINode:
    """Boolean toggle switch."""
    props: dict[str, Any] = {"value": value, "param_name": param_name}
    if label: props["label"] = label
    if on_change: props["on_change"] = on_change
    return UINode(type="Toggle", props=props)


def Slider(
    min: int = 0,
    max: int = 100,
    value: int = 50,
    step: int = 1,
    label: str = "",
    param_name: str = "value",
) -> UINode:
    """Numeric range slider."""
    props: dict[str, Any] = {"min": min, "max": max, "value": value, "step": step, "param_name": param_name}
    if label: props["label"] = label
    return UINode(type="Slider", props=props)


def DatePicker(
    value: str = "",
    placeholder: str = "Select date",
    on_change: UIAction | None = None,
    param_name: str = "date",
) -> UINode:
    """Date picker calendar input."""
    props: dict[str, Any] = {"value": value, "placeholder": placeholder, "param_name": param_name}
    if on_change: props["on_change"] = on_change
    return UINode(type="DatePicker", props=props)


def FileUpload(
    accept: str = "*",
    max_size_mb: int = 10,
    multiple: bool = False,
    on_upload: UIAction | None = None,
    param_name: str = "files",
    blocked_extensions: list[str] | None = None,
    max_total_mb: int = 0,
    max_files: int = 0,
) -> UINode:
    """File upload dropzone with validation.
    blocked_extensions: reject these file types (e.g. ["exe", "bat"]).
    max_total_mb: total size limit across all files (0 = no limit).
    max_files: max number of files (0 = no limit).
    Frontend sends base64 file data in on_upload action.
    """
    props: dict[str, Any] = {
        "accept": accept,
        "max_size_mb": max_size_mb,
        "multiple": multiple,
        "param_name": param_name,
    }
    if on_upload: props["on_upload"] = on_upload
    if blocked_extensions: props["blocked_extensions"] = blocked_extensions
    if max_total_mb: props["max_total_mb"] = max_total_mb
    if max_files: props["max_files"] = max_files
    return UINode(type="FileUpload", props=props)


def TextArea(
    placeholder: str = "",
    value: str = "",
    rows: int = 4,
    on_submit: UIAction | None = None,
    param_name: str = "text",
) -> UINode:
    """Multi-line text area."""
    props: dict[str, Any] = {"placeholder": placeholder, "value": value, "rows": rows, "param_name": param_name}
    if on_submit: props["on_submit"] = on_submit
    return UINode(type="TextArea", props=props)


def RichEditor(content: str = "", placeholder: str = "Start writing...",
               on_save: UIAction | None = None, on_change: UIAction | None = None,
               param_name: str = "content", toolbar: bool = True) -> UINode:
    """Rich text editor (TipTap). content: HTML string. on_save fires on Ctrl+S."""
    props: dict[str, Any] = {"content": content, "placeholder": placeholder,
             "param_name": param_name, "toolbar": toolbar}
    if on_save: props["on_save"] = on_save
    if on_change: props["on_change"] = on_change
    return UINode(type="RichEditor", props=props)


def TagInput(
    values: list[str] | None = None,
    suggestions: list[str] | None = None,
    placeholder: str = "Add...",
    param_name: str = "tags",
    on_change: UIAction | None = None,
    grouped_by: str = "",
    delimiters: list[str] | None = None,
    validate: str = "",
    validate_message: str = "",
) -> UINode:
    """Tag/chip input with autocomplete.

    grouped_by      : group suggestions by prefix (e.g. 'extensions:read').
    delimiters      : extra keystrokes that create a tag in addition to Enter.
                      Accepts individual characters (e.g. [' ', ',', ';']). Default
                      is Enter-only to preserve prior behaviour.
    validate        : optional regex pattern (string). Tags failing the pattern are
                      refused; the input is highlighted red and ``validate_message``
                      is shown as a tooltip. Anchor yourself — use '^...$' for
                      full-string match.
    validate_message: human-readable hint shown on rejected tags. Fallback generic
                      message is used when empty.
    """
    props: dict[str, Any] = {
        "values": values or [],
        "suggestions": suggestions or [],
        "placeholder": placeholder,
        "param_name": param_name,
        "grouped_by": grouped_by,
    }
    if on_change: props["on_change"] = on_change
    if delimiters:
        # Keep the list homogenous — strings only, each one a single char or short key.
        props["delimiters"] = [str(d) for d in delimiters if d]
    if validate:
        props["validate"] = validate
    if validate_message:
        props["validate_message"] = validate_message
    return UINode(type="TagInput", props=props)
