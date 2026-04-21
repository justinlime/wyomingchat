"""Global push-to-talk integration through the XDG Global Shortcuts portal."""

from __future__ import annotations

import asyncio
import secrets
from typing import Any

from dbus_next import Variant
from dbus_next.aio import MessageBus
from PySide6.QtCore import QObject, QThread, Signal

from .constants import APP_ID, DEFAULT_SHORTCUT_DESCRIPTION, SHORTCUT_ID_PUSH_TO_TALK

PORTAL_BUS_NAME = "org.freedesktop.portal.Desktop"
PORTAL_OBJECT_PATH = "/org/freedesktop/portal/desktop"
PORTAL_GLOBAL_SHORTCUTS_INTERFACE = "org.freedesktop.portal.GlobalShortcuts"
PORTAL_REQUEST_INTERFACE = "org.freedesktop.portal.Request"
PORTAL_SESSION_INTERFACE = "org.freedesktop.portal.Session"
HOST_REGISTRY_INTERFACE = "org.freedesktop.host.portal.Registry"
HOST_REGISTRY_CANDIDATES = (
    ("org.freedesktop.host.portal.Desktop", "/org/freedesktop/host/portal/desktop"),
    ("org.freedesktop.host.portal.Desktop", "/org/freedesktop/host/portal/Registry"),
)


# Usage: build a D-Bus variant dictionary from plain Python string values.
# Parameters: payload - a mapping of option keys to Python values that should become D-Bus Variants.
# Return: a dictionary suitable for dbus-next method arguments typed as a{sv}.
def build_variant_dict(payload: dict[str, Any]) -> dict[str, Variant]:
    """Convert a plain Python dictionary into a D-Bus variant dictionary."""

    variants: dict[str, Variant] = {}
    for key, value in payload.items():
        if isinstance(value, bool):
            variants[key] = Variant("b", value)
        elif isinstance(value, int):
            variants[key] = Variant("u", value)
        else:
            variants[key] = Variant("s", str(value))
    return variants


# Usage: recursively unwrap dbus-next Variant objects and nested portal result structures.
# Parameters: value - the value returned by dbus-next, which may contain Variants, lists, tuples, or dictionaries.
# Return: the same structure with Variant wrappers removed.
def unwrap_variants(value: Any) -> Any:
    """Recursively remove dbus-next Variant wrappers from a nested result value."""

    if isinstance(value, Variant):
        return unwrap_variants(value.value)
    if isinstance(value, dict):
        return {str(key): unwrap_variants(item) for key, item in value.items()}
    if isinstance(value, list):
        return [unwrap_variants(item) for item in value]
    if isinstance(value, tuple):
        return tuple(unwrap_variants(item) for item in value)
    return value


# Usage: create unique object path tokens required by portal request and session methods.
# Parameters: prefix - a short human-readable prefix that identifies the token's purpose.
# Return: a valid object-path-safe token string.
def generate_token(prefix: str) -> str:
    """Return a unique token string suitable for portal request and session handles."""

    return f"{prefix}_{secrets.token_hex(8)}"


class GlobalShortcutWorker(QThread):
    """Bind a global shortcut through the portal and listen for press/release signals."""

    binding_succeeded = Signal(str)
    binding_failed = Signal(str)
    shortcut_pressed = Signal()
    shortcut_released = Signal()
    availability_changed = Signal(bool)

    # Usage: create a background worker that binds one portal-managed global shortcut.
    # Parameters: app_id - the desktop application id used for portal registration; shortcut_id - the stable app-defined shortcut identifier; preferred_trigger - the user's requested key combination; description - the user-facing shortcut description.
    # Return: None.
    def __init__(
        self,
        app_id: str,
        shortcut_id: str,
        preferred_trigger: str,
        description: str,
    ) -> None:
        """Initialize the global shortcut worker thread."""

        super().__init__()
        self._app_id = app_id
        self._shortcut_id = shortcut_id
        self._preferred_trigger = preferred_trigger
        self._description = description or DEFAULT_SHORTCUT_DESCRIPTION
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bus: MessageBus | None = None
        self._stop_future: asyncio.Future[None] | None = None
        self._session_handle: str | None = None

    # Usage: execute the portal registration and signal-listening workflow in a dedicated thread.
    # Parameters: none.
    # Return: None.
    def run(self) -> None:
        """Run the asynchronous portal client inside the QThread context."""

        try:
            asyncio.run(self._run_async())
        except Exception as exc:  # noqa: BLE001 - this is the final worker error boundary.
            self.binding_failed.emit(str(exc))
            self.availability_changed.emit(False)

    # Usage: request that the worker shut down, close its portal session, and stop listening for signals.
    # Parameters: none.
    # Return: None.
    def stop(self) -> None:
        """Signal the worker's event loop to shut down cleanly."""

        if self._loop is None or self._stop_future is None or self._stop_future.done():
            return

        self._loop.call_soon_threadsafe(self._stop_future.set_result, None)

    # Usage: orchestrate host portal registration, shortcut binding, signal subscription, and shutdown.
    # Parameters: none.
    # Return: None.
    async def _run_async(self) -> None:
        """Run the end-to-end asynchronous shortcut binding workflow."""

        self._loop = asyncio.get_running_loop()
        self._bus = await MessageBus().connect()

        try:
            await self._register_with_host_portal()
            portal_interface = await self._get_global_shortcuts_interface()
            portal_interface.on_activated(self._handle_activated)
            portal_interface.on_deactivated(self._handle_deactivated)
            self._session_handle = await self._create_session(portal_interface)
            trigger_description = await self._bind_shortcut(portal_interface, self._session_handle)
            self.binding_succeeded.emit(trigger_description)
            self.availability_changed.emit(True)
            self._stop_future = self._loop.create_future()
            await self._stop_future
        finally:
            await self._close_session()
            if self._bus is not None:
                self._bus.disconnect()
            self.availability_changed.emit(False)

    # Usage: register the process with the host portal when available so unsandboxed apps map to a desktop id.
    # Parameters: none.
    # Return: None.
    async def _register_with_host_portal(self) -> None:
        """Best-effort host portal registration for unsandboxed desktop sessions."""

        if self._bus is None:
            return

        for bus_name, object_path in HOST_REGISTRY_CANDIDATES:
            try:
                introspection = await self._bus.introspect(bus_name, object_path)
                proxy = self._bus.get_proxy_object(bus_name, object_path, introspection)
                registry = proxy.get_interface(HOST_REGISTRY_INTERFACE)
                await registry.call_register(self._app_id, {})
                return
            except Exception:  # noqa: BLE001 - host portal support is optional and backend-specific.
                continue

    # Usage: introspect the desktop portal and return the GlobalShortcuts interface proxy.
    # Parameters: none.
    # Return: the dbus-next proxy interface for org.freedesktop.portal.GlobalShortcuts.
    async def _get_global_shortcuts_interface(self):
        """Return a proxy interface for the portal's GlobalShortcuts API."""

        if self._bus is None:
            raise RuntimeError("The D-Bus session bus is not connected")

        introspection = await self._bus.introspect(PORTAL_BUS_NAME, PORTAL_OBJECT_PATH)
        proxy = self._bus.get_proxy_object(PORTAL_BUS_NAME, PORTAL_OBJECT_PATH, introspection)
        return proxy.get_interface(PORTAL_GLOBAL_SHORTCUTS_INTERFACE)

    # Usage: create a new global-shortcuts portal session that owns future bindings.
    # Parameters: portal_interface - the proxy interface used to call portal methods.
    # Return: the object path of the newly created session.
    async def _create_session(self, portal_interface) -> str:
        """Create and return a new portal session for global shortcut bindings."""

        request_handle = await portal_interface.call_create_session(
            build_variant_dict(
                {
                    "handle_token": generate_token("request"),
                    "session_handle_token": generate_token("session"),
                }
            )
        )
        response_code, results = await self._await_request_response(str(request_handle))
        if response_code != 0:
            raise RuntimeError("The desktop portal did not grant a global shortcut session")

        session_handle = str(results.get("session_handle", "")).strip()
        if not session_handle:
            raise RuntimeError("The desktop portal did not return a session handle")

        return session_handle

    # Usage: bind the configured shortcut into an existing portal session and return its human-readable trigger.
    # Parameters: portal_interface - the proxy interface used to call portal methods; session_handle - the object path of the portal session.
    # Return: the final trigger description shown to the user by the portal backend.
    async def _bind_shortcut(self, portal_interface, session_handle: str) -> str:
        """Bind the user's requested shortcut and return the backend's display text."""

        shortcuts = [
            (
                self._shortcut_id,
                build_variant_dict(
                    {
                        "description": self._description,
                        "preferred_trigger": self._preferred_trigger,
                    }
                ),
            )
        ]
        request_handle = await portal_interface.call_bind_shortcuts(
            session_handle,
            shortcuts,
            "",
            build_variant_dict({"handle_token": generate_token("bind")}),
        )
        response_code, results = await self._await_request_response(str(request_handle))
        if response_code != 0:
            raise RuntimeError("The desktop portal rejected the global shortcut binding request")

        bound_shortcuts = results.get("shortcuts", [])
        for shortcut_id, shortcut_data in bound_shortcuts:
            if str(shortcut_id) != self._shortcut_id:
                continue
            trigger_description = str(shortcut_data.get("trigger_description", "")).strip()
            if trigger_description:
                return trigger_description

        return self._preferred_trigger

    # Usage: wait for the response signal emitted on a portal request object path.
    # Parameters: request_handle - the request object path returned by a portal method.
    # Return: a tuple containing the numeric response code and the unwrapped results dictionary.
    async def _await_request_response(self, request_handle: str) -> tuple[int, dict[str, Any]]:
        """Wait for a portal request object to emit its Response signal."""

        if self._bus is None or self._loop is None:
            raise RuntimeError("The D-Bus session bus is not connected")

        introspection = await self._bus.introspect(PORTAL_BUS_NAME, request_handle)
        proxy = self._bus.get_proxy_object(PORTAL_BUS_NAME, request_handle, introspection)
        request_interface = proxy.get_interface(PORTAL_REQUEST_INTERFACE)
        response_future: asyncio.Future[tuple[int, dict[str, Any]]] = self._loop.create_future()

        def on_response(response: int, results: dict[str, Any]) -> None:
            """Capture the portal request response and resolve the waiting future."""

            if response_future.done():
                return
            response_future.set_result((response, unwrap_variants(results)))

        request_interface.on_response(on_response)
        return await asyncio.wait_for(response_future, timeout=30.0)

    # Usage: close the active portal session during worker shutdown.
    # Parameters: none.
    # Return: None.
    async def _close_session(self) -> None:
        """Close the global shortcut portal session if one was created."""

        if self._bus is None or not self._session_handle:
            return

        try:
            introspection = await self._bus.introspect(PORTAL_BUS_NAME, self._session_handle)
            proxy = self._bus.get_proxy_object(PORTAL_BUS_NAME, self._session_handle, introspection)
            session_interface = proxy.get_interface(PORTAL_SESSION_INTERFACE)
            await session_interface.call_close()
        except Exception:
            pass
        finally:
            self._session_handle = None

    # Usage: handle the portal's Activated signal and relay it to the Qt controller layer.
    # Parameters: session_handle - portal session object path; shortcut_id - the app-defined shortcut id; timestamp - activation time; options - extra portal metadata.
    # Return: None.
    def _handle_activated(
        self,
        session_handle: str,
        shortcut_id: str,
        timestamp: int,
        options: dict[str, Any],
    ) -> None:
        """Emit a Qt signal when the configured global shortcut is pressed."""

        del timestamp, options
        if session_handle == self._session_handle and shortcut_id == self._shortcut_id:
            self.shortcut_pressed.emit()

    # Usage: handle the portal's Deactivated signal and relay it to the Qt controller layer.
    # Parameters: session_handle - portal session object path; shortcut_id - the app-defined shortcut id; timestamp - deactivation time; options - extra portal metadata.
    # Return: None.
    def _handle_deactivated(
        self,
        session_handle: str,
        shortcut_id: str,
        timestamp: int,
        options: dict[str, Any],
    ) -> None:
        """Emit a Qt signal when the configured global shortcut is released."""

        del timestamp, options
        if session_handle == self._session_handle and shortcut_id == self._shortcut_id:
            self.shortcut_released.emit()


class GlobalShortcutPortal(QObject):
    """High-level Qt wrapper around the background portal worker thread."""

    binding_changed = Signal(str)
    binding_failed = Signal(str)
    shortcut_pressed = Signal()
    shortcut_released = Signal()
    availability_changed = Signal(bool)

    # Usage: create the portal integration service used by the controller and UI.
    # Parameters: parent - optional QObject parent used for Qt ownership.
    # Return: None.
    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize the portal shortcut wrapper without binding anything yet."""

        super().__init__(parent)
        self._worker: GlobalShortcutWorker | None = None

    # Usage: start or replace the background worker that registers the user's push-to-talk shortcut.
    # Parameters: preferred_trigger - the portal shortcut string requested by the user; description - the text shown in portal permission dialogs.
    # Return: None.
    def register_shortcut(
        self,
        preferred_trigger: str,
        description: str = DEFAULT_SHORTCUT_DESCRIPTION,
    ) -> None:
        """Bind the configured push-to-talk shortcut through the desktop portal."""

        self.shutdown()
        self._worker = GlobalShortcutWorker(
            app_id=APP_ID,
            shortcut_id=SHORTCUT_ID_PUSH_TO_TALK,
            preferred_trigger=preferred_trigger,
            description=description,
        )
        self._worker.binding_succeeded.connect(self.binding_changed.emit)
        self._worker.binding_failed.connect(self.binding_failed.emit)
        self._worker.shortcut_pressed.connect(self.shortcut_pressed.emit)
        self._worker.shortcut_released.connect(self.shortcut_released.emit)
        self._worker.availability_changed.connect(self.availability_changed.emit)
        self._worker.start()

    # Usage: stop the active background worker when the app exits or the shortcut is reconfigured.
    # Parameters: none.
    # Return: None.
    def shutdown(self) -> None:
        """Stop the active shortcut worker, if one exists."""

        if self._worker is None:
            return

        self._worker.stop()
        self._worker.wait(3_000)
        self._worker.deleteLater()
        self._worker = None
