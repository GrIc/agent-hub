"""Auto-discovery registry for MCP tools.

Scans the ``src.mcp.tools`` package for concrete subclasses of
:class:`~src.mcp.base.BaseTool` and instantiates them, producing a
mapping from tool name to tool instance.

This enables the MCP server to automatically expose new tools without
manual registration — any module that defines a ``BaseTool`` subclass
and is placed inside the tools package will be picked up on import.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from typing import Any, Dict, Type, Union

from src.mcp.base import BaseTool

logger = logging.getLogger("mcp.registry")


def discover_tools(package: str = "src.mcp.tools") -> Dict[str, BaseTool]:
    """Discover and instantiate all concrete :class:`BaseTool` subclasses.

    This function performs the following steps:

    1. Imports the specified package (default ``src.mcp.tools``).
    2. Iterates over every submodule in the package using
       :func:`pkgutil.iter_modules`.
    3. Imports each submodule (silently skipping modules that fail to
       import, with a warning logged).
    4. Inspects the module's public attributes for classes that are
       **concrete** (non-abstract) subclasses of :class:`BaseTool`.
    5. Instantiates each discovered class using its no-argument
       constructor.
    6. Collects the instances into a dictionary keyed by each tool's
       ``name`` class attribute.

    Parameters
    ----------
    package:
        Dotted Python package path to scan.  Defaults to
        ``"src.mcp.tools"``.

    Returns
    -------
    dict[str, BaseTool]
        A mapping from tool ``name`` to the instantiated tool object.

    Raises
    ------
    TypeError
        If a discovered class cannot be instantiated with no arguments
        (the constructor signature is incompatible).

    Examples
    --------
    >>> tools = discover_tools()  # scans src.mcp.tools
    >>> for name, tool in tools.items():
    ...     print(f"{name}: {tool.description}")
    """
    tool_registry: Dict[str, BaseTool] = {}

    # Step 1: Import the package and validate it is a package.
    try:
        mod = importlib.import_module(package)
    except ModuleNotFoundError as exc:
        logger.warning(
            "Package '%s' not found; no tools will be discovered. %s",
            package,
            exc,
        )
        return tool_registry
    except ImportError as exc:
        logger.warning(
            "Failed to import package '%s'; no tools will be discovered. %s",
            package,
            exc,
        )
        return tool_registry

    if not getattr(mod, "__path__", None) and not getattr(mod, "__file__", None):
        logger.warning(
            "Package '%s' is not a valid package; no tools will be discovered.",
            package,
        )
        return tool_registry

    # Ensure __path__ is set (some namespace packages may lack it).
    package_path = getattr(mod, "__path__", None) or [
        mod.__file__  # type: ignore[union-attr]
    ]

    # Step 2: Iterate over all modules in the package.
    for importer, modname, ispkg in pkgutil.iter_modules(package_path):
        # Skip sub-packages (we only scan top-level modules for tools).
        if ispkg:
            logger.debug("Skipping sub-package: %s", modname)
            continue

        # Step 3: Import the module.
        full_name = f"{package}.{modname}"
        try:
            module = importlib.import_module(full_name)
        except (ImportError, ModuleNotFoundError) as exc:
            logger.warning(
                "Failed to import module '%s'; skipping. %s",
                full_name,
                exc,
            )
            continue

        # Step 4: Inspect module attributes for concrete BaseTool subclasses.
        _scan_module(module, full_name, tool_registry)

    logger.info(
        "Discovery complete: %d tool(s) registered from package '%s'.",
        len(tool_registry),
        package,
    )
    return tool_registry


def _scan_module(
    module: Any,
    module_name: str,
    registry: Dict[str, BaseTool],
) -> None:
    """Scan a single module for concrete BaseTool subclasses.

    Parameters
    ----------
    module:
        The imported Python module.
    module_name:
        Fully-qualified module name (used for logging).
    registry:
        Mutable dictionary to populate with discovered tools.
    """
    for attr_name, attr_value in inspect.getmembers(module, inspect.isclass):
        # Skip the BaseTool class itself.
        if attr_value is BaseTool:
            continue

        # Skip classes not defined in this module (avoids cross-module
        # pollution when a base class is imported elsewhere).
        if getattr(attr_value, "__module__", None) != module_name:
            continue

        # Verify it is a concrete subclass of BaseTool.
        if not _is_concrete_tool_subclass(attr_value):
            continue

        # Step 5: Instantiate the class.
        try:
            instance = attr_value()
        except TypeError as exc:
            logger.warning(
                "Class '%s.%s' cannot be instantiated with no arguments; "
                "skipping. %s",
                module_name,
                attr_name,
                exc,
            )
            continue
        except Exception as exc:
            logger.warning(
                "Unexpected error instantiating '%s.%s'; skipping. %s",
                module_name,
                attr_name,
                exc,
            )
            continue

        # Step 6: Register by name.
        tool_name = getattr(instance, "name", None)
        if not tool_name:
            logger.warning(
                "Discovered tool class '%s.%s' has no 'name' attribute; "
                "skipping.",
                module_name,
                attr_name,
            )
            continue

        if tool_name in registry:
            logger.warning(
                "Tool name '%s' already registered; overwriting with "
                "instance from '%s.%s'.",
                tool_name,
                module_name,
                attr_name,
            )

        registry[tool_name] = instance
        logger.info("Registered tool '%s' from module '%s'.", tool_name, module_name)


def _is_concrete_tool_subclass(cls: Type[Any]) -> bool:
    """Return ``True`` if *cls* is a concrete (instantiable) subclass of
    :class:`BaseTool`.

    A class is considered **concrete** when:

    - It inherits (directly or indirectly) from :class:`BaseTool`.
    - It is **not** :class:`BaseTool` itself.
    - It is **not** an abstract class (i.e. has no unimplemented
      abstract methods as reported by :func:`inspect.isabstract`).
    """
    # Must be a subclass of BaseTool.
    try:
        if not issubclass(cls, BaseTool):
            return False
    except TypeError:
        return False

    # Must not be BaseTool itself.
    if cls is BaseTool:
        return False

    # Must not be abstract.
    if inspect.isabstract(cls):
        logger.debug(
            "Class '%s.%s' is abstract; skipping.",
            getattr(cls, "__module__", "?"),
            cls.__name__,
        )
        return False

    return True
