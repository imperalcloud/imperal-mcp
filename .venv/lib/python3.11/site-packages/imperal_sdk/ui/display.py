"""Imperal SDK · Display UI Components."""
from __future__ import annotations

from typing import Any
from .base import UINode, UIAction


def Text(content: str, variant: str = "body") -> UINode:
    """Text block. variant: heading/body/caption/code."""
    return UINode(type="Text", props={"content": content, "variant": variant})


def Icon(name: str, size: int = 16, color: str = "") -> UINode:
    """Lucide icon by name."""
    return UINode(type="Icon", props={"name": name, "size": size, "color": color})


def Header(text: str, level: int = 2, subtitle: str = "") -> UINode:
    """Heading element h1-h4 with optional subtitle."""
    props: dict[str, Any] = {"text": text, "level": level}
    if subtitle: props["subtitle"] = subtitle
    return UINode(type="Header", props=props)


def Image(src: str, alt: str = "", width: str = "", height: str = "",
          on_click: UIAction | None = None, object_fit: str = "",
          caption: str = "") -> UINode:
    """Image element with optional click action and styling."""
    props: dict[str, Any] = {"src": src}
    if alt: props["alt"] = alt
    if width: props["width"] = width
    if height: props["height"] = height
    if on_click: props["on_click"] = on_click
    if object_fit: props["object_fit"] = object_fit
    if caption: props["caption"] = caption
    return UINode(type="Image", props=props)


def Code(content: str, language: str = "", line_numbers: bool = False) -> UINode:
    """Syntax-highlighted code block."""
    props: dict[str, Any] = {"content": content, "line_numbers": line_numbers}
    if language: props["language"] = language
    return UINode(type="Code", props=props)


def Markdown(content: str) -> UINode:
    """Raw markdown rendered to HTML."""
    return UINode(type="Markdown", props={"content": content})


def Empty(message: str = "No data", icon: str = "", action: UIAction | None = None) -> UINode:
    """Empty state placeholder."""
    props: dict[str, Any] = {"message": message}
    if icon: props["icon"] = icon
    if action: props["action"] = action
    return UINode(type="Empty", props=props)


def Divider(label: str = "") -> UINode:
    """Horizontal rule with optional centered label."""
    props: dict[str, Any] = {}
    if label: props["label"] = label
    return UINode(type="Divider", props=props)


def Html(
    content: str,
    sandbox: bool = True,
    max_height: int = 0,
    theme: str = "dark",
) -> UINode:
    """Raw HTML block.

    sandbox: True isolates in an iframe.
    max_height: scroll container height (0 = auto-size).
    theme: "dark" (default, transparent bg) or "light" (white bg, for email).
    """
    props: dict[str, Any] = {"content": content, "sandbox": sandbox}
    if max_height: props["max_height"] = max_height
    if theme != "dark": props["theme"] = theme
    return UINode(type="Html", props=props)


def Video(
    src: str,
    poster: str = "",
    title: str = "",
    autoplay: bool = False,
    controls: bool = True,
    loop: bool = False,
    muted: bool = False,
    width: str = "",
    height: str = "",
) -> UINode:
    """HTML5 video player.

    src: video URL (mp4, webm, ogg, or HLS m3u8).
    poster: thumbnail image shown before playback.
    controls: show play/pause/seek/volume (default True).
    """
    props: dict[str, Any] = {"src": src, "controls": controls}
    if poster: props["poster"] = poster
    if title: props["title"] = title
    if autoplay: props["autoplay"] = autoplay
    if loop: props["loop"] = loop
    if muted: props["muted"] = muted
    if width: props["width"] = width
    if height: props["height"] = height
    return UINode(type="Video", props=props)


def Audio(
    src: str,
    title: str = "",
    controls: bool = True,
    autoplay: bool = False,
    loop: bool = False,
) -> UINode:
    """HTML5 audio player.

    src: audio URL (mp3, wav, ogg).
    controls: show play/pause/seek/volume (default True).
    """
    props: dict[str, Any] = {"src": src, "controls": controls}
    if title: props["title"] = title
    if autoplay: props["autoplay"] = autoplay
    if loop: props["loop"] = loop
    return UINode(type="Audio", props=props)
