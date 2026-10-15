"""Tous les outils de Jarvis, dans un seul registre (lu par la porte des permissions)."""

from __future__ import annotations

from ojarvis.browser.session import BrowserSession
from ojarvis.tools.base import ToolRegistry
from ojarvis.tools.browser import BrowserClick, BrowserFill, BrowserOpen, BrowserRead
from ojarvis.tools.code import ListCapabilities, RunCode
from ojarvis.tools.files import DeleteFile, ListDirectory, ReadFile, WriteFile
from ojarvis.tools.web import ReadPage, WebSearch


def build_registry(browser: BrowserSession) -> ToolRegistry:
    registry = ToolRegistry(
        [
            WebSearch(),
            ReadPage(),
            BrowserOpen(browser),
            BrowserRead(browser),
            BrowserClick(browser),
            BrowserFill(browser),
            ReadFile(),
            ListDirectory(),
            WriteFile(),
            DeleteFile(),
            RunCode(),
        ]
    )
    registry.register(ListCapabilities(registry))
    return registry
