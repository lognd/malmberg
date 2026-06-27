"""Slideshow producers for malmberg_display."""

from __future__ import annotations

from malmberg_display.slideshow.producers.cache import CacheProducer
from malmberg_display.slideshow.producers.directory import (
    classify_file,
    load_flat_from_directory,
    load_recr_from_directory,
)
from malmberg_display.slideshow.producers.infinite import load_infinite
from malmberg_display.slideshow.producers.server import CachedItem, ServerProducer

__all__ = [
    "CacheProducer",
    "CachedItem",
    "ServerProducer",
    "classify_file",
    "load_flat_from_directory",
    "load_infinite",
    "load_recr_from_directory",
]
