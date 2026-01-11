#!/usr/bin/env python3
"""
BAS Client - communicates with BAS via hex-encoded file IPC.
Uses the original BrowserAutomationStudio_SendMessageToHelper protocol.
"""

import json
import asyncio
import random
import time
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple


def get_exe_directory() -> Path:
    """Get directory of the running executable or script."""
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller exe
        return Path(sys.executable).parent
    else:
        # Running as script
        return Path(__file__).parent


def find_helperipc_dir(start_path: Optional[Path] = None) -> Path:
    """
    Auto-detect helperipc directory relative to exe location.

    Priority:
    1. BAS_IPC_DIR environment variable
    2. Search up from exe location for helperipc in BAS structure (apps/VERSION/helperipc)
    3. Search common BAS installation paths
    4. Fallback to exe directory

    Structure examples:
    - D:/BAS/App/apps/29.6.1/Worker.31/bas_mcp.exe -> D:/BAS/App/apps/29.6.1/helperipc
    - D:/BAS/App/apps/29.6.1/bas_mcp.exe -> D:/BAS/App/apps/29.6.1/helperipc
    """
    import os
    import sys

    # Priority 1: Environment variable
    env_ipc = os.environ.get('BAS_IPC_DIR')
    if env_ipc:
        return Path(env_ipc)

    if start_path is None:
        start_path = get_exe_directory()

    # Priority 2: Search up from exe location for BAS version folder
    # BAS structure: .../apps/VERSION/helperipc (VERSION like 29.6.1)
    # Exe can be in: .../apps/VERSION/Worker.XX/ or .../apps/VERSION/
    current = start_path
    for _ in range(5):
        # Check if current folder is a BAS version folder (parent is "apps")
        if current.parent.name == "apps":
            helperipc = current / "helperipc"
            if helperipc.exists():
                return helperipc
            # Create if doesn't exist (BAS will create files here)
            helperipc.mkdir(exist_ok=True)
            return helperipc

        parent = current.parent
        if parent == current:
            break
        current = parent

    # Priority 3: Search common BAS installation paths
    common_paths = [
        Path("D:/BAS/BrowserAutomationStudio/apps"),
        Path("C:/BAS/BrowserAutomationStudio/apps"),
        Path.home() / "BAS/BrowserAutomationStudio/apps",
    ]
    for base in common_paths:
        if base.exists():
            # Find latest version folder
            versions = sorted([d for d in base.iterdir() if d.is_dir() and d.name[0].isdigit()], reverse=True)
            for ver in versions:
                helperipc = ver / "helperipc"
                if helperipc.exists():
                    return helperipc

    # Fallback: create helperipc next to exe
    return start_path / "helperipc"


def find_logs_dir(start_path: Optional[Path] = None) -> Optional[Path]:
    """
    Auto-detect BAS logs directory.

    Structure: D:/BAS/App/logs/log/
    From exe:  D:/BAS/App/apps/29.6.1/Worker.31/bas_mcp.exe
    """
    if start_path is None:
        start_path = get_exe_directory()

    # Search up to find BAS root (folder containing 'apps' and 'logs')
    current = start_path
    for _ in range(6):
        logs_dir = current / "logs" / "log"
        if logs_dir.exists():
            return logs_dir

        # Check if parent has logs
        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def list_log_files(logs_dir: Optional[Path] = None, limit: int = 20) -> List[Dict]:
    """List available log files, newest first."""
    if logs_dir is None:
        logs_dir = find_logs_dir()

    if not logs_dir or not logs_dir.exists():
        return []

    log_files = sorted(logs_dir.glob("*.txt"), reverse=True)[:limit]
    result = []
    for f in log_files:
        result.append({
            "name": f.name,
            "path": str(f),
            "size": f.stat().st_size,
            "modified": f.stat().st_mtime
        })
    return result


def read_log_file(log_name: Optional[str] = None, logs_dir: Optional[Path] = None,
                  tail_lines: int = 0) -> Dict:
    """
    Read a log file content.

    Args:
        log_name: Log filename (e.g., "2026.01.11.04.20.11.txt") or None for latest
        logs_dir: Logs directory or None to auto-detect
        tail_lines: If > 0, return only last N lines
    """
    if logs_dir is None:
        logs_dir = find_logs_dir()

    if not logs_dir or not logs_dir.exists():
        return {"success": False, "error": "Logs directory not found"}

    if log_name:
        log_path = logs_dir / log_name
    else:
        # Get latest log
        log_files = sorted(logs_dir.glob("*.txt"), reverse=True)
        if not log_files:
            return {"success": False, "error": "No log files found"}
        log_path = log_files[0]

    if not log_path.exists():
        return {"success": False, "error": f"Log file not found: {log_name}"}

    try:
        content = log_path.read_text(encoding='utf-8', errors='replace')
        lines = content.splitlines()

        if tail_lines > 0:
            lines = lines[-tail_lines:]
            content = '\n'.join(lines)

        return {
            "success": True,
            "name": log_path.name,
            "path": str(log_path),
            "lines_count": len(lines),
            "content": content
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


class BASClient:
    """Client for BAS communication via hex-encoded file IPC."""

    def __init__(self, bas_pid: int, ipc_dir: Optional[Path] = None):
        self.bas_pid = bas_pid

        # IPC directory - auto-detect if not provided
        if ipc_dir:
            self.ipc_dir = Path(ipc_dir)
        else:
            self.ipc_dir = find_helperipc_dir()

        self.ipc_dir.mkdir(parents=True, exist_ok=True)

        # File paths with PID
        self.helper_to_bas = self.ipc_dir / f"helper-to-bas.{bas_pid}.txt"
        self.bas_to_helper = self.ipc_dir / f"bas-to-helper.{bas_pid}.txt"

        self.message_id = 0
        self._poll_interval = 0.05  # 50ms
        self._last_response_pos = 0

    def _next_id(self) -> int:
        self.message_id = random.randint(100000000, 999999999)
        return self.message_id

    @staticmethod
    def _string_to_hex(s: str) -> str:
        """Convert string to hex-encoded UTF-8."""
        return s.encode('utf-8').hex()

    @staticmethod
    def _hex_to_string(h: str) -> str:
        """Convert hex-encoded UTF-8 bytes back to string."""
        return bytes.fromhex(h).decode('utf-8', errors='replace')

    def _write_command(self, cmd: dict) -> bool:
        """Write hex-encoded command to helper-to-bas file."""
        try:
            json_str = json.dumps(cmd, ensure_ascii=False)  # Keep Unicode chars
            hex_str = self._string_to_hex(json_str)

            # Write command file (overwrite) - hex is ASCII-safe
            with open(self.helper_to_bas, 'w', encoding='ascii') as f:
                f.write(hex_str)

            return True
        except Exception as e:
            print(f"Error writing command: {e}", flush=True)
            return False

    def _read_response(self, expected_id: int, timeout: float = 30.0) -> Optional[dict]:
        """Read response from bas-to-helper file (double hex-encoded)."""
        start_time = time.time()
        checked_lines = set()  # Track which lines we've already checked

        while time.time() - start_time < timeout:
            try:
                if self.bas_to_helper.exists():
                    # Hex is ASCII-safe
                    content = self.bas_to_helper.read_text(encoding='ascii')
                    lines = content.strip().split('\n')

                    # Check ALL lines - responses are double hex encoded
                    for i, line in enumerate(lines):
                        line = line.strip()
                        if not line or line in checked_lines:
                            continue

                        checked_lines.add(line)

                        try:
                            # Try double hex decode (for JS responses)
                            inner_hex = self._hex_to_string(line)
                            json_str = self._hex_to_string(inner_hex)
                            response = json.loads(json_str)

                            if response.get('id') == expected_id:
                                # Delete file after successful read
                                try:
                                    self.bas_to_helper.unlink()
                                except Exception:
                                    pass
                                return response
                        except Exception:
                            # Line is not double hex encoded (e.g., initial BAS message)
                            continue

            except Exception:
                pass

            time.sleep(self._poll_interval)

        return None

    async def _call(self, cmd_type: str, data: Any = None, timeout: float = 30.0) -> Any:
        """Send command and wait for response."""
        msg_id = self._next_id()

        command = {
            "type": cmd_type,
            "id": msg_id,
            "data": data
        }

        # Write command
        if not self._write_command(command):
            return {"error": "Failed to write command"}

        # Wait for response (run in thread to not block)
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, self._read_response, msg_id, timeout
        )

        if response is None:
            return None  # Timeout

        return response.get('data')

    # ============= PUBLIC API =============

    async def ping(self) -> bool:
        """Check connection to BAS. Returns True if BAS responds."""
        msg_id = self._next_id()
        command = {"type": "ping", "id": msg_id, "data": None}

        if not self._write_command(command):
            return False

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None, self._read_response, msg_id, 10.0
        )

        return response is not None

    async def list_modules(self) -> List[Dict]:
        """Get list of available BAS modules."""
        return await self._call("list-modules") or []

    async def list_actions(self, module: str) -> List[Dict]:
        """Get list of actions in a module. Use '*' for all actions."""
        return await self._call("list-actions", {"module": module}) or []

    async def get_action_schema(self, action: str) -> Dict:
        """Get parameter schema for an action type."""
        return await self._call("get-action-schema", {"action": action}) or {}

    async def get_project(self) -> List[Dict]:
        """Get all actions in current project."""
        return await self._call("get-project") or []

    async def get_task_raw(self, action_id: int) -> Dict:
        """Get raw task data including code field."""
        return await self._call("get-task-raw", {"action_id": action_id}) or {}

    async def create_action(self, action: str, params: Dict = None,
                           after_id: int = 0, parent_id: int = 0,
                           comment: str = "", color: str = "green",
                           execute: bool = False, include_html: bool = True) -> Dict:
        """Create a new action in the project."""
        return await self._call("create-action", {
            "action": action,
            "params": params or {},
            "after_id": after_id,
            "parent_id": parent_id,
            "comment": comment,
            "color": color,
            "execute": execute,
            "include_html": include_html
        }, timeout=120.0 if execute else 30.0) or {"success": False, "error": "No response"}

    async def update_action(self, action_id: int, params: Dict = None,
                           comment: str = None) -> Dict:
        """Update an existing action."""
        data = {"action_id": action_id}
        if params:
            data["params"] = params
        if comment is not None:
            data["comment"] = comment
        return await self._call("update-action", data) or {"success": False, "error": "No response"}

    async def delete_actions(self, action_ids: List[int]) -> Dict:
        """Delete actions by IDs."""
        return await self._call("delete-actions", {"action_ids": action_ids}) or {"success": False}

    async def run_from(self, action_id: int) -> Dict:
        """Run scenario starting from specific action."""
        return await self._call("run-from", {"action_id": action_id}) or {"success": False}

    async def get_html(self) -> Dict:
        """Get current browser page HTML."""
        return await self._call("get-html", timeout=60.0) or {"success": False, "error": "No response"}

    async def get_url(self) -> Dict:
        """Get current browser page URL."""
        return await self._call("get-url") or {"success": False, "error": "No response"}

    # ============= SCRIPT CONTROL =============

    async def play(self) -> Dict:
        """Start/continue script execution."""
        return await self._call("play") or {"success": False, "error": "No response"}

    async def step_next(self) -> Dict:
        """Execute next action and pause."""
        return await self._call("step-next") or {"success": False, "error": "No response"}

    async def pause(self) -> Dict:
        """Pause script execution."""
        return await self._call("pause") or {"success": False, "error": "No response"}

    async def restart(self) -> Dict:
        """Restart script in Record mode."""
        result = await self._call("restart") or {"success": False, "error": "No response"}
        if result.get("success"):
            await asyncio.sleep(15)  # Wait for restart
        return result

    async def stop(self) -> Dict:
        """Stop script execution completely."""
        return await self._call("stop") or {"success": False, "error": "No response"}

    async def get_status(self) -> Dict:
        """Get current script execution status."""
        return await self._call("get-status") or {"success": False, "error": "No response"}

    # ============= DEBUG / EXECUTION =============

    async def move_to(self, action_id: int) -> Dict:
        """Move execution point to specific action ID."""
        return await self._call("move-execution-point", {"action_id": action_id}) or {"success": False, "error": "No response"}

    async def get_variables(self) -> Dict:
        """Get list of all variables in project."""
        return await self._call("get-variables") or {"success": False, "error": "No response"}

    async def get_variable(self, name: str, no_truncate: bool = True) -> Dict:
        """Get value of specific variable.

        Args:
            name: Variable name (with or without VAR_ prefix)
            no_truncate: If True, return full value without truncation (default: True)
        """
        return await self._call("get-variable", {"name": name, "no_truncate": no_truncate}) or {"success": False, "error": "No response"}

    async def get_resources(self) -> Dict:
        """Get list of all resources in project."""
        return await self._call("get-resources") or {"success": False, "error": "No response"}

    async def get_resource(self, name: str) -> Dict:
        """Get value of specific resource."""
        return await self._call("get-resource", {"name": name}) or {"success": False, "error": "No response"}

    async def eval_expr(self, expression: str) -> Dict:
        """Evaluate JavaScript expression in BAS context."""
        return await self._call("eval", {"expression": expression}) or {"success": False, "error": "No response"}

    # ============= HIGH-LEVEL HELPERS =============

    async def _wait_for_idle(self, timeout: float = 30.0) -> bool:
        """Wait until script stops executing (both is_executing and is_task_executing are False)."""
        start = time.time()
        while time.time() - start < timeout:
            status = await self.get_status()
            if not status.get("is_executing", False) and not status.get("is_task_executing", False):
                return True
            await asyncio.sleep(0.2)
        return False

    async def load_page(self, url: str, timeout: float = 60.0) -> Dict:
        """
        Load a page using create_action with execute=True.
        Cleans up the temporary action after execution.

        Args:
            url: URL to load
            timeout: Timeout for page load

        Returns:
            {success: True/False, url: loaded_url, error: message}
        """
        try:
            result = await self.create_action(
                action="load",
                params={"LoadUrl": url},
                execute=True,
                include_html=False,
                comment="_temp_load_"
            )

            action_id = result.get("action_id")

            if result.get("execution_result") == "completed":
                if action_id:
                    await self.delete_actions([action_id])
                return {"success": True, "url": url}
            else:
                if action_id:
                    await self.delete_actions([action_id])
                return {"success": False, "error": result.get("execution_error", "Execution failed")}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_page_html_safe(self, timeout: float = 60.0) -> Dict:
        """
        Get current page HTML using JavaScript action with execute=True.
        Creates browserjavascript action, executes it, reads variable, deletes action.

        Uses [[VARNAME]] syntax which creates VAR_VARNAME variable.

        Args:
            timeout: Execution timeout

        Returns:
            {success: True/False, html: html_content, error: message}
        """
        # Generate unique variable name
        var_suffix = random.randint(10000, 99999)
        var_name = f"HTML_{var_suffix}"

        try:
            # Create and execute JS action that saves HTML to variable
            js_code = f"[[{var_name}]] = await (async () => {{ return document.documentElement.outerHTML; }})();"

            result = await self.create_action(
                action="browserjavascript",
                params={"Code": js_code},
                execute=True,
                include_html=False,
                comment="_temp_html_"
            )

            action_id = result.get("action_id")

            if result.get("execution_result") != "completed":
                if action_id:
                    await self.delete_actions([action_id])
                return {"success": False, "error": result.get("execution_error", "Execution failed")}

            # Read the variable (BAS adds VAR_ prefix)
            full_var_name = f"VAR_{var_name}"
            var_result = await self.get_variable(full_var_name)

            # Clean up action
            if action_id:
                await self.delete_actions([action_id])

            if not var_result.get("success"):
                return {"success": False, "error": f"Failed to get variable: {var_result.get('error')}"}

            return {"success": True, "html": var_result.get("value", "")}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def execute_browser_js(self, code: str, save_to: Optional[str] = None,
                                  timeout: float = 60.0) -> Dict:
        """
        Execute JavaScript code in browser context using execute=True.

        For returning values, use await and [[VARNAME]] syntax in code:
            code = "[[RESULT]] = await (async () => { return document.title; })();"
            save_to = "RESULT"

        Args:
            code: JavaScript code to execute
            save_to: Variable name to read result from (without VAR_ prefix)
            timeout: Execution timeout

        Returns:
            {success: True/False, result: value (if save_to specified), error: message}
        """
        try:
            # Create and execute browserjavascript action
            result = await self.create_action(
                action="browserjavascript",
                params={"Code": code},
                execute=True,
                include_html=False,
                comment="_temp_js_"
            )

            action_id = result.get("action_id")

            if result.get("execution_result") != "completed":
                if action_id:
                    await self.delete_actions([action_id])
                return {"success": False, "error": result.get("execution_error", "Execution failed")}

            # Read result variable if requested
            response = {"success": True}
            if save_to:
                full_var_name = f"VAR_{save_to}"
                var_result = await self.get_variable(full_var_name)
                if var_result.get("success"):
                    response["result"] = var_result.get("value")
                else:
                    # Clean up and return error
                    if action_id:
                        await self.delete_actions([action_id])
                    return {"success": False, "error": f"Failed to get result: {var_result.get('error')}"}

            # Clean up action
            if action_id:
                await self.delete_actions([action_id])

            return response

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def load_and_get_html(self, url: str, timeout: float = 60.0) -> Dict:
        """
        Convenience method: Load page and get its HTML in one call.

        Args:
            url: URL to load
            timeout: Total timeout

        Returns:
            {success: True/False, html: html_content, url: loaded_url, error: message}
        """
        # Load the page
        load_result = await self.load_page(url, timeout=timeout)
        if not load_result.get("success"):
            return load_result

        # Get HTML
        html_result = await self.get_page_html_safe(timeout=timeout)
        if not html_result.get("success"):
            return html_result

        return {
            "success": True,
            "url": url,
            "html": html_result.get("html", "")
        }

    # ============= FUNCTION MANAGEMENT =============

    async def list_functions(self) -> Dict:
        """
        Get list of all functions (sections) in the project.

        Returns:
            {
                success: True/False,
                functions: [
                    {id: 123, name: "FunctionName", actions_count: 5},
                    ...
                ],
                count: N
            }
        """
        try:
            project = await self.get_project()
            if not project:
                return {"success": False, "error": "Failed to get project"}

            functions = []
            for action in project:
                if action.get("type") == "section_insert":
                    func_id = action.get("id")
                    func_name = action.get("comment", "")

                    # Count actions inside this function
                    actions_count = sum(
                        1 for a in project
                        if a.get("parent_id") == func_id
                    )

                    functions.append({
                        "id": func_id,
                        "name": func_name,
                        "actions_count": actions_count
                    })

            return {
                "success": True,
                "functions": functions,
                "count": len(functions)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_function_actions(self, function_name: str = None, function_id: int = None) -> Dict:
        """
        Get all actions inside a specific function.

        Args:
            function_name: Name of the function
            function_id: ID of the function (alternative to name)

        Returns:
            {
                success: True/False,
                function: {id, name},
                actions: [...],
                count: N
            }
        """
        try:
            project = await self.get_project()
            if not project:
                return {"success": False, "error": "Failed to get project"}

            # Find the function
            func = None
            for action in project:
                if action.get("type") == "section_insert":
                    if function_id and action.get("id") == function_id:
                        func = action
                        break
                    if function_name and action.get("comment") == function_name:
                        func = action
                        break

            if not func:
                return {"success": False, "error": f"Function not found: {function_name or function_id}"}

            func_id = func.get("id")

            # Get actions inside this function
            actions = [
                a for a in project
                if a.get("parent_id") == func_id
            ]

            return {
                "success": True,
                "function": {"id": func_id, "name": func.get("comment", "")},
                "actions": actions,
                "count": len(actions)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def create_function(self, name: str, after_function: str = None) -> Dict:
        """
        Create a new function (section) in the project.

        Args:
            name: Name of the function to create
            after_function: Name of function to insert after (optional)

        Returns:
            {success: True/False, function_id: ID, name: "..."}
        """
        try:
            after_id = 0

            # Find position to insert after
            if after_function:
                project = await self.get_project()
                for action in project:
                    if action.get("type") == "section_insert" and action.get("comment") == after_function:
                        after_id = action.get("id")
                        break

            # Create section_insert action via IPC
            result = await self._call("create-function", {
                "name": name,
                "after_id": after_id
            })

            if result is None:
                return {"success": False, "error": "No response from BAS"}

            return result

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def delete_function(self, function_name: str = None, function_id: int = None,
                             delete_contents: bool = True) -> Dict:
        """
        Delete a function and optionally its contents.

        Args:
            function_name: Name of the function to delete
            function_id: ID of the function (alternative to name)
            delete_contents: If True, delete all actions inside the function too

        Returns:
            {success: True/False, deleted_count: N}
        """
        try:
            project = await self.get_project()
            if not project:
                return {"success": False, "error": "Failed to get project"}

            # Find the function
            func = None
            for action in project:
                if action.get("type") == "section_insert":
                    if function_id and action.get("id") == function_id:
                        func = action
                        break
                    if function_name and action.get("comment") == function_name:
                        func = action
                        break

            if not func:
                return {"success": False, "error": f"Function not found: {function_name or function_id}"}

            func_id = func.get("id")
            ids_to_delete = [func_id]

            # Collect actions inside this function
            if delete_contents:
                for action in project:
                    if action.get("parent_id") == func_id:
                        ids_to_delete.append(action.get("id"))

            # Delete all collected IDs
            result = await self.delete_actions(ids_to_delete)

            if result.get("success"):
                return {"success": True, "deleted_count": len(ids_to_delete)}
            return result

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def open_function(self, function_name: str = None, function_id: int = None) -> Dict:
        """
        Open/navigate to a function for editing (scroll to it in BAS UI).

        Args:
            function_name: Name of the function
            function_id: ID of the function (alternative to name)

        Returns:
            {success: True/False, function: {id, name}}
        """
        try:
            project = await self.get_project()
            if not project:
                return {"success": False, "error": "Failed to get project"}

            # Find the function
            func = None
            for action in project:
                if action.get("type") == "section_insert":
                    if function_id and action.get("id") == function_id:
                        func = action
                        break
                    if function_name and action.get("comment") == function_name:
                        func = action
                        break

            if not func:
                return {"success": False, "error": f"Function not found: {function_name or function_id}"}

            func_id = func.get("id")

            # Move execution point to this function (will scroll to it)
            result = await self.move_to(func_id)

            if result.get("success"):
                return {
                    "success": True,
                    "function": {"id": func_id, "name": func.get("comment", "")}
                }
            return result

        except Exception as e:
            return {"success": False, "error": str(e)}

    # ============= SCREENSHOT =============

    async def take_screenshot(self, selector: str = ">CSS> html") -> Dict:
        """
        Take a screenshot of the page or specific element.

        Args:
            selector: Element selector (default: ">CSS> html" for full page)

        Returns:
            {success: True/False, screenshot_base64: "...", error: message}
        """
        var_name = f"SCREENSHOT_{random.randint(10000, 99999)}"

        try:
            # Create and execute screenshot action
            result = await self.create_action(
                action="screenshot",
                params={
                    "PATH": selector,
                    "Save": var_name
                },
                execute=True,
                include_html=False,
                comment="_temp_screenshot_"
            )

            action_id = result.get("action_id")

            if result.get("execution_result") != "completed":
                if action_id:
                    await self.delete_actions([action_id])
                return {"success": False, "error": result.get("execution_error", "Screenshot failed")}

            # Read the screenshot variable
            full_var_name = f"VAR_{var_name}"
            var_result = await self.get_variable(full_var_name)

            # Clean up action
            if action_id:
                await self.delete_actions([action_id])

            if not var_result.get("success"):
                return {"success": False, "error": f"Failed to get screenshot: {var_result.get('error')}"}

            return {
                "success": True,
                "screenshot_base64": var_result.get("value", "")
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def check_element(self, selector: str) -> Dict:
        """
        Check element existence, visibility and count.

        Args:
            selector: Element selector in PATH format (>CSS>, >XPATH>, etc.)

        Returns:
            {success: True, exists: bool, visible: bool, count: int}
        """
        import random
        action_ids = []

        try:
            # 1. Check if element EXISTS (without visibility check)
            var_exists = f"CHK_EXISTS_{random.randint(10000, 99999)}"
            result1 = await self.create_action(
                action="exist",
                params={
                    "PATH": selector,
                    "Save": var_exists
                },
                execute=True,
                include_html=False,
                comment="_temp_check_exists_"
            )
            if result1.get("action_id"):
                action_ids.append(result1["action_id"])

            # 2. Check if element is VISIBLE (with Check=True)
            var_visible = f"CHK_VISIBLE_{random.randint(10000, 99999)}"
            result2 = await self.create_action(
                action="exist",
                params={
                    "PATH": selector,
                    "Check": True,  # Also check if visible
                    "Save": var_visible
                },
                execute=True,
                include_html=False,
                comment="_temp_check_visible_"
            )
            if result2.get("action_id"):
                action_ids.append(result2["action_id"])

            # 3. Get element COUNT
            var_count = f"CHK_COUNT_{random.randint(10000, 99999)}"
            result3 = await self.create_action(
                action="length",
                params={
                    "PATH": selector,
                    "Save": var_count
                },
                execute=True,
                include_html=False,
                comment="_temp_check_count_"
            )
            if result3.get("action_id"):
                action_ids.append(result3["action_id"])

            # Read results
            exists_val = await self.get_variable(f"VAR_{var_exists}")
            visible_val = await self.get_variable(f"VAR_{var_visible}")
            count_val = await self.get_variable(f"VAR_{var_count}")

            # Clean up temporary actions
            if action_ids:
                await self.delete_actions(action_ids)

            # Parse results (BAS returns boolean True/False)
            exists = bool(exists_val.get("value")) if exists_val.get("success") else False
            visible = bool(visible_val.get("value")) if visible_val.get("success") else False

            # Count is a number
            try:
                count = int(count_val.get("value", 0)) if count_val.get("success") else 0
            except (ValueError, TypeError):
                count = 0

            return {
                "success": True,
                "exists": exists,
                "visible": visible,
                "count": count,
                "selector": selector
            }

        except Exception as e:
            # Clean up on error
            if action_ids:
                try:
                    await self.delete_actions(action_ids)
                except:
                    pass
            return {"success": False, "error": str(e)}


    # ============= MODULE PARAMETER ANALYSIS =============

    async def analyze_module_action(self, action_id: int) -> Dict:
        """
        Analyze a module action to discover parameter mapping.

        Examines an existing module action and tries to determine what each
        parameter does based on its value patterns.

        Args:
            action_id: ID of existing module action to analyze

        Returns:
            {
                success: True/False,
                action_type: "call" or "call_function",
                params_mapping: {
                    "random_param_name": {
                        "value": "current_value",
                        "guessed_purpose": "phone_number|regex|selector|api_key|timeout|...",
                        "description": "Human readable description"
                    },
                    ...
                }
            }
        """
        try:
            project = await self.get_project()
            if not project:
                return {"success": False, "error": "Failed to get project"}

            # Find the action
            action = None
            for a in project:
                if a.get("id") == action_id:
                    action = a
                    break

            if not action:
                return {"success": False, "error": f"Action {action_id} not found"}

            action_type = action.get("type", "")
            params = action.get("params", {})

            # Analyze each parameter
            params_mapping = {}
            for param_name, value in params.items():
                value_str = str(value)

                # Try to guess purpose based on value patterns
                purpose = "unknown"
                description = ""

                # Skip known standard params
                if param_name in ["FunctionName", "Save", "Check", "Check2", "Check3"]:
                    purpose = param_name.lower()
                    description = f"Standard BAS parameter: {param_name}"

                # Save-to variable params (saveXxx, Xxx_Save patterns)
                elif param_name.lower().startswith("save") or param_name.lower().endswith("save"):
                    purpose = "save_variable"
                    description = f"Variable to save result: {param_name}"

                # Get/enable boolean params (getXxx, enableXxx)
                elif param_name.lower().startswith("get") or param_name.lower().startswith("enable"):
                    purpose = "boolean_option"
                    description = f"Enable/get option: {param_name}"

                # Delete/set after params
                elif param_name.lower().startswith("del") or param_name.lower().endswith("after"):
                    purpose = "action_flag"
                    description = f"Action flag: {param_name}"

                # Phone number patterns
                elif "[[" in value_str and ("NUMBER" in value_str.upper() or "PHONE" in value_str.upper()):
                    purpose = "phone_number"
                    description = "Phone number variable"
                elif value_str.startswith("+") and any(c.isdigit() for c in value_str):
                    purpose = "phone_number"
                    description = "Phone number value"

                # Regex patterns
                elif "(" in value_str and ")" in value_str and any(c in value_str for c in ["\\d", "\\w", "[0-9]", "+"]):
                    purpose = "regex_pattern"
                    description = "Regular expression for parsing"

                # CSS/XPath selectors
                elif value_str.strip().startswith(">CSS>") or value_str.strip().startswith(">XPATH>"):
                    purpose = "element_selector"
                    description = "Element selector (PATH format)"
                elif value_str.startswith(".") or value_str.startswith("#") or "geetest" in value_str.lower():
                    purpose = "css_selector"
                    description = "CSS selector for element"

                # URLs
                elif value_str.startswith("http://") or value_str.startswith("https://"):
                    purpose = "url"
                    description = "URL endpoint"

                # Timeout/numeric values
                elif value_str.isdigit() and int(value_str) >= 1000:
                    purpose = "timeout_ms"
                    description = "Timeout in milliseconds"
                elif value_str.isdigit():
                    purpose = "numeric"
                    description = "Numeric value (count, index, etc.)"

                # Boolean
                elif value_str.lower() in ["true", "false"]:
                    purpose = "boolean"
                    description = "Boolean flag"

                # Filter patterns (like "p|a|y|n|e|r")
                elif "|" in value_str and len(value_str.split("|")) > 3:
                    purpose = "filter_pattern"
                    description = "Filter pattern (characters or words to match)"

                # Variable reference
                elif value_str.startswith("[[") and value_str.endswith("]]"):
                    purpose = "variable_reference"
                    description = f"Variable: {value_str}"

                # Service ID pattern (hex-like, 8-16 chars)
                elif len(value_str) >= 8 and len(value_str) <= 32 and all(c in "0123456789abcdef" for c in value_str.lower()):
                    purpose = "service_id"
                    description = "Service/API identifier"

                # API key pattern (long alphanumeric)
                elif len(value_str) > 20 and value_str.isalnum():
                    purpose = "api_key_or_id"
                    description = "API key or service ID (hidden for security)"
                    value_str = "***HIDDEN***"  # Hide potential API keys

                # Query (SQL-like)
                elif any(kw in value_str.upper() for kw in ["SELECT", "INSERT", "UPDATE", "DELETE", "CREATE"]):
                    purpose = "sql_query"
                    description = "SQL query"

                params_mapping[param_name] = {
                    "value": value_str[:100] + ("..." if len(value_str) > 100 else ""),
                    "guessed_purpose": purpose,
                    "description": description
                }

            return {
                "success": True,
                "action_id": action_id,
                "action_type": action_type,
                "comment": action.get("comment", ""),
                "params_mapping": params_mapping,
                "params_count": len(params_mapping)
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def find_module_actions(self, module_hint: str = None) -> Dict:
        """
        Find all module actions in project, optionally filtered by hint.

        Args:
            module_hint: Optional filter like "sms", "sql", "captcha", "fingerprint", "vpn", "imap"

        Returns:
            {
                success: True/False,
                modules: [
                    {
                        action_id: 123,
                        action_type: "call_function",
                        detected_module: "sms",
                        params_preview: {...}
                    },
                    ...
                ]
            }
        """
        try:
            project = await self.get_project()
            if not project:
                return {"success": False, "error": "Failed to get project"}

            modules = []

            for action in project:
                if action.get("type") not in ["call", "call_function"]:
                    continue

                params = action.get("params", {})
                params_str = json.dumps(params, ensure_ascii=False).lower()

                # Detect module type
                detected = "unknown"
                if "query" in params and ("select" in params_str or "insert" in params_str):
                    detected = "sql"
                elif "geetest" in params_str or "captcha" in params_str:
                    detected = "captcha"
                elif "fingerprint" in params_str or "canvas" in params_str or "webgl" in params_str:
                    detected = "fingerprint"
                elif any(kw in params_str for kw in ["vpn", "proxy_data", "udp"]):
                    detected = "vpn"
                elif any(kw in params_str for kw in ["imap", "inbox", "mail", "getsubject", "getbody"]):
                    detected = "imap"
                elif any(kw in params_str for kw in ["phone", "number", "sms", "code"]) or \
                     any(kw in params_str for kw in ["\\d{4", "\\d{5", "\\d{6"]):
                    detected = "sms"
                elif any(kw in params_str for kw in ["timezone", "geolocation", "ipinfo", "webrtc"]):
                    detected = "geolocation"

                # Filter by hint if provided
                if module_hint and module_hint.lower() != detected:
                    continue

                # Skip simple function calls
                if action.get("type") == "call_function":
                    non_standard = {k: v for k, v in params.items()
                                   if k not in ["FunctionName", "Save", "Check"]}
                    if not non_standard:
                        continue

                # Create preview of params
                params_preview = {}
                for k, v in list(params.items())[:5]:
                    v_str = str(v)
                    if len(v_str) > 30:
                        v_str = v_str[:30] + "..."
                    # Hide potential secrets
                    if any(s in k.lower() for s in ["key", "token", "pass", "secret"]):
                        v_str = "***"
                    params_preview[k] = v_str

                modules.append({
                    "action_id": action.get("id"),
                    "action_type": action.get("type"),
                    "detected_module": detected,
                    "comment": action.get("comment", ""),
                    "params_preview": params_preview,
                    "params_count": len(params)
                })

            return {
                "success": True,
                "modules": modules,
                "count": len(modules),
                "hint_used": module_hint
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_module_schema(self, module_name: str, action_id: int = None) -> Dict:
        """
        Get schema for a BAS module including parameter descriptions, defaults, and variants.

        Args:
            module_name: Name of the module (e.g., "GoodXevilPaySolver_GXP_ReCaptcha_Bypass_No_Exten")
            action_id: Optional action ID to get code-to-param mapping

        Returns:
            {
                success: True/False,
                module_name: "...",
                params: [
                    {
                        id: "random_id",
                        description: "Readable Name",
                        data_type: "string" | "int" | "variable",
                        default_value: "...",
                        variants: ["option1", "option2"],  # if applicable
                        code_name: "readable_name"  # from code field
                    },
                    ...
                ],
                code_params: {"readable_name": "readable_name", ...}
            }
        """
        # First try to get code_params from BAS
        bas_result = await self._call("get-module-schema", {
            "module_name": module_name,
            "action_id": action_id
        }) or {}

        result = {
            "success": True,
            "module_name": module_name,
            "params": [],
            "code_params": bas_result.get("code_params", {})
        }

        # Parse interface.js file directly from filesystem
        interface_content = self._load_module_interface(module_name)
        if interface_content:
            result["params"] = self._parse_module_interface(interface_content, result["code_params"])
            result["interface_loaded"] = True
        else:
            result["interface_loaded"] = False
            result["interface_error"] = "Could not find interface file"

        return result

    def _load_module_interface(self, module_name: str) -> Optional[str]:
        """Load interface.js file for a module from BAS installation."""
        import re

        # Extract module folder from module name
        # e.g., GoodXevilPaySolver_GXP_ReCaptcha_Bypass_No_Exten -> GoodXevilPaySolver
        parts = module_name.split('_')
        module_folder = parts[0]

        # Find BAS apps directory from IPC dir
        # IPC dir is like: D:\BAS\...\apps\29.6.1\helperipc
        bas_apps_dir = self.ipc_dir.parent if self.ipc_dir else None
        if not bas_apps_dir:
            return None

        # Try different locations
        interface_filename = f"{module_name}_interface.js"
        search_paths = [
            bas_apps_dir / "custom" / module_folder / interface_filename,
        ]

        # Also search in external folders (they have numeric IDs)
        external_dir = bas_apps_dir / "external"
        if external_dir.exists():
            for subdir in external_dir.iterdir():
                if subdir.is_dir():
                    candidate = subdir / module_folder / interface_filename
                    search_paths.append(candidate)

        for path in search_paths:
            if path.exists():
                try:
                    return path.read_text(encoding='utf-8')
                except Exception:
                    pass

        return None

    def _parse_module_interface(self, html: str, code_params: Dict) -> List[Dict]:
        """Parse interface.js content to extract parameter definitions."""
        import re
        params = []

        # Parse input_constructor calls
        # Format: $('#input_constructor').html())({id:"xxx", ...}) %>
        # The content between ({ and }) may contain nested braces like help: {...}
        # We use a greedy match up to "}) %>" to capture the full content
        constructor_pattern = r"#input_constructor'\)\.html\(\)\)\(\{(.+?)\}\s*\)\s*%>"
        for match in re.finditer(constructor_pattern, html, re.DOTALL):
            content = match.group(1)
            param = self._parse_constructor_params(content, code_params)
            if param:
                params.append(param)

        # Parse variable_constructor calls (for Save params)
        var_pattern = r"#variable_constructor'\)\.html\(\)\)\(\{(.+?)\}\s*\)\s*%>"
        for match in re.finditer(var_pattern, html, re.DOTALL):
            content = match.group(1)
            param = self._parse_variable_constructor(content)
            if param:
                params.append(param)

        return params

    def _parse_constructor_params(self, content: str, code_params: Dict) -> Optional[Dict]:
        """Parse a single input_constructor content."""
        import re
        try:
            param = {"type": "input"}

            # Extract id
            id_match = re.search(r'id:\s*"([^"]+)"', content)
            if id_match:
                param["id"] = id_match.group(1)

            # Extract description (readable name)
            desc_match = re.search(r'description:\s*"([^"]+)"', content)
            if desc_match:
                param["description"] = desc_match.group(1)

            # Extract default_selector (type)
            type_match = re.search(r'default_selector:\s*"([^"]+)"', content)
            if type_match:
                param["data_type"] = type_match.group(1)

            # Extract variants (list of options)
            variants_match = re.search(r'variants:\s*\[([^\]]+)\]', content)
            if variants_match:
                variants_str = variants_match.group(1)
                items = []
                # Parse array: "a", "b" or 0, 1
                for item_match in re.finditer(r'"([^"]+)"|(\d+)', variants_str):
                    items.append(item_match.group(1) or item_match.group(2))
                param["variants"] = items

            # Extract default value
            value_string_match = re.search(r'value_string:\s*"([^"]*)"', content)
            if value_string_match:
                param["default_value"] = value_string_match.group(1)

            value_number_match = re.search(r'value_number:\s*(\d+)', content)
            if value_number_match:
                param["default_value"] = int(value_number_match.group(1))

            # Map to code param name if available
            if param.get("description") and code_params:
                lower_desc = param["description"].lower()
                if lower_desc in code_params:
                    param["code_name"] = code_params[lower_desc]

            return param if param.get("id") else None
        except Exception:
            return None

    def _parse_variable_constructor(self, content: str) -> Optional[Dict]:
        """Parse a variable_constructor content."""
        import re
        try:
            param = {"type": "variable"}

            # Extract id
            id_match = re.search(r'id:\s*"([^"]+)"', content)
            if id_match:
                param["id"] = id_match.group(1)

            # Extract description
            desc_match = re.search(r'description:\s*"([^"]+)"', content)
            if desc_match:
                param["description"] = desc_match.group(1)

            # Extract default_variable
            default_match = re.search(r'default_variable:\s*"([^"]+)"', content)
            if default_match:
                param["default_value"] = default_match.group(1)

            param["data_type"] = "variable"

            return param if param.get("id") else None
        except Exception:
            return None

    async def create_module_action_from_template(self, template_action_id: int,
                                                   new_values: Dict[str, str],
                                                   after_id: int = 0,
                                                   parent_id: int = 0,
                                                   comment: str = "") -> Dict:
        """
        Create a new module action based on existing template, replacing values.

        This allows Claude to use logical value descriptions and have them mapped
        to the correct random parameter names.

        Args:
            template_action_id: ID of existing module action to use as template
            new_values: Dict mapping PURPOSE to new value, e.g.:
                {
                    "phone_number": "[[MY_PHONE]]",
                    "regex_pattern": "([0-9]{6})",
                    "timeout_ms": "30000"
                }
            after_id: Insert after this action ID
            parent_id: Parent action ID for nesting
            comment: Comment for new action

        Returns:
            {success: True/False, action_id: new_id, mapped_params: {...}}
        """
        try:
            # First analyze the template
            analysis = await self.analyze_module_action(template_action_id)
            if not analysis.get("success"):
                return analysis

            # Get the original action
            project = await self.get_project()
            template = None
            for a in project:
                if a.get("id") == template_action_id:
                    template = a
                    break

            if not template:
                return {"success": False, "error": "Template action not found"}

            # Build new params by matching purposes
            new_params = dict(template.get("params", {}))
            mapped = {}

            for param_name, info in analysis.get("params_mapping", {}).items():
                purpose = info.get("guessed_purpose", "unknown")

                # Check if user provided a value for this purpose
                if purpose in new_values:
                    new_params[param_name] = new_values[purpose]
                    mapped[param_name] = {
                        "purpose": purpose,
                        "old_value": info.get("value"),
                        "new_value": new_values[purpose]
                    }
                # Also check by param name directly (fallback)
                elif param_name in new_values:
                    new_params[param_name] = new_values[param_name]
                    mapped[param_name] = {
                        "purpose": purpose,
                        "old_value": info.get("value"),
                        "new_value": new_values[param_name]
                    }

            # Create the new action
            result = await self.create_action(
                action=template.get("type"),
                params=new_params,
                after_id=after_id,
                parent_id=parent_id,
                comment=comment or template.get("comment", ""),
                color=template.get("color", "green")
            )

            result["mapped_params"] = mapped
            result["template_id"] = template_action_id

            return result

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def clone_module_action(self, template_id: int, new_params: Dict[str, str],
                                   comment: str = "") -> Dict:
        """
        Clone a module action with modified parameters.

        This properly handles the complex structure of BAS module actions
        (Dat JSON encoding, JavaScript code updates, etc.)

        Args:
            template_id: ID of existing module action to clone
            new_params: Dict mapping parameter ID to new value, e.g.:
                {
                    "pmvdseyg": "{{apikey}}",     # Use resource for ApiKey
                    "xknmvqbc": "Multibot",       # Change solver
                }
            comment: Optional comment for new action

        Returns:
            {
                success: True/False,
                action_id: new_id,
                updated_params: {param_id: {old: "...", new: "..."}, ...}
            }

        Example workflow:
            1. schema = await client.get_module_schema("ModuleName", template_id)
            2. Find param IDs from schema: pmvdseyg -> ApiKey
            3. result = await client.clone_module_action(template_id, {"pmvdseyg": "{{apikey}}"})
        """
        return await self._call("clone-module-action", {
            "template_id": template_id,
            "new_params": new_params,
            "comment": comment
        }) or {"success": False, "error": "No response"}


async def main():
    """Test the client."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python bas_client.py <BAS_PID>")
        sys.exit(1)

    pid = int(sys.argv[1])
    print(f"Starting BAS Client for PID {pid}...")

    client = BASClient(pid)
    print(f"IPC directory: {client.ipc_dir}")
    print(f"Helper->BAS: {client.helper_to_bas}")
    print(f"BAS->Helper: {client.bas_to_helper}")
    print("\nSending ping...")

    result = await client.ping()
    if result:
        print("PING SUCCESS! BAS is responding.")
    else:
        print("PING FAILED! No response from BAS.")


if __name__ == "__main__":
    asyncio.run(main())
