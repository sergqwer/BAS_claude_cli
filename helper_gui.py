#!/usr/bin/env python3
"""
Claude + BAS Launcher

Simple launcher that:
1. Creates MCP config for BAS integration
2. Launches Claude CLI in interactive console mode
3. Claude can only use BAS MCP tools (no other tools allowed)
"""

import sys
import os
import json
import argparse
import subprocess
import shutil
from pathlib import Path
from typing import Optional


def get_exe_dir() -> Path:
    """Get directory where the EXE (or script) is located."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def find_bas_mcp_exe() -> Optional[str]:
    """Find bas_mcp.exe next to launcher."""
    exe_dir = get_exe_dir()

    # Check same directory
    mcp_path = exe_dir / 'bas_mcp.exe'
    if mcp_path.exists():
        return str(mcp_path)

    # Check dist subfolder (for development)
    mcp_path = exe_dir / 'dist' / 'bas_mcp.exe'
    if mcp_path.exists():
        return str(mcp_path)

    # For development - check if bas_mcp_server.py exists
    mcp_py = exe_dir / 'bas_mcp_server.py'
    if mcp_py.exists():
        return f"python {mcp_py}"

    return None


def find_claude_cli() -> Optional[str]:
    """Find Claude CLI executable."""
    # 1. Check if 'claude' is in PATH
    claude_in_path = shutil.which('claude')
    if claude_in_path:
        return claude_in_path

    # 2. Check common npm global locations on Windows
    possible_paths = []

    # AppData/Roaming/npm (npm global)
    appdata = os.environ.get('APPDATA', '')
    if appdata:
        possible_paths.append(Path(appdata) / 'npm' / 'claude.cmd')
        possible_paths.append(Path(appdata) / 'npm' / 'claude')

    # User profile npm
    userprofile = os.environ.get('USERPROFILE', '')
    if userprofile:
        possible_paths.append(Path(userprofile) / 'AppData' / 'Roaming' / 'npm' / 'claude.cmd')
        possible_paths.append(Path(userprofile) / '.npm-global' / 'claude.cmd')
        possible_paths.append(Path(userprofile) / 'node_modules' / '.bin' / 'claude.cmd')

    # Program Files
    possible_paths.append(Path('C:/Program Files/nodejs/claude.cmd'))
    possible_paths.append(Path('C:/Program Files (x86)/nodejs/claude.cmd'))

    # nvm locations
    if userprofile:
        nvm_path = Path(userprofile) / '.nvm'
        if nvm_path.exists():
            for version_dir in nvm_path.glob('v*'):
                possible_paths.append(version_dir / 'claude.cmd')
                possible_paths.append(version_dir / 'node_modules' / '.bin' / 'claude.cmd')

    # Check each path
    for p in possible_paths:
        if p.exists():
            return str(p)

    return None


def create_mcp_config(bas_pid: int) -> Optional[Path]:
    """
    Create MCP config file for Claude CLI.
    Returns path to config file or None if failed.
    """
    mcp_exe = find_bas_mcp_exe()
    if not mcp_exe:
        return None

    # Create config in same directory as EXE
    config_path = get_exe_dir() / 'claude_mcp_config.json'

    # Build MCP config
    if mcp_exe.startswith("python "):
        # Development mode - use python to run script
        script_path = mcp_exe.replace("python ", "")
        mcp_config = {
            "mcpServers": {
                "bas": {
                    "command": "python",
                    "args": [script_path, "--pid", str(bas_pid)]
                }
            }
        }
    else:
        # Production mode - use exe directly
        mcp_config = {
            "mcpServers": {
                "bas": {
                    "command": mcp_exe.replace('\\', '/'),
                    "args": ["--pid", str(bas_pid)]
                }
            }
        }

    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(mcp_config, f, indent=2, ensure_ascii=False)
        return config_path
    except Exception as e:
        print(f"Error: Failed to create MCP config: {e}")
        return None


def show_error(message: str):
    """Show error message."""
    print(f"ERROR: {message}")
    # Also show Windows message box
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, "Claude + BAS Launcher Error", 0x10)
    except:
        pass


def main():
    parser = argparse.ArgumentParser(description='Claude + BAS Launcher')
    parser.add_argument('--parent-process-id', type=str, default='0')
    parser.add_argument('--bas-lang', type=str, default='en')
    parser.add_argument('--bas-version', type=str, default='0.0.0')
    parser.add_argument('--modules', type=str, default='')
    parser.add_argument('--url', type=str, default='')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--pid', type=str, default=None)

    args = parser.parse_args()

    # Use --pid if provided, otherwise --parent-process-id
    bas_pid = int(args.pid or args.parent_process_id)

    if args.debug:
        print(f"BAS PID: {bas_pid}")
        print(f"Claude CLI: {find_claude_cli()}")
        print(f"MCP Server: {find_bas_mcp_exe()}")

    # Find Claude CLI
    claude_path = find_claude_cli()
    if not claude_path:
        show_error(
            "Claude CLI not found!\n\n"
            "Install with: npm install -g @anthropic-ai/claude-code\n\n"
            "Make sure npm is in PATH."
        )
        sys.exit(1)

    # Create MCP config
    config_path = create_mcp_config(bas_pid)
    if not config_path:
        show_error(
            "Failed to create MCP config!\n\n"
            "Make sure bas_mcp.exe is in the same folder as this launcher."
        )
        sys.exit(1)

    # Build command for Claude CLI
    # --mcp-config: use our MCP config
    # --strict-mcp-config: only use our MCP, ignore others
    # --allowedTools: only allow tools from our MCP (bas_*)
    claude_args = (
        f'--mcp-config "{config_path}" '
        f'--strict-mcp-config '
        f'--allowedTools "mcp__bas*"'
    )

    # Use 'start' command to open new console window
    # start "" opens new window, cmd /k keeps it open after command finishes
    cmd = f'start "Claude + BAS" cmd /k ""{claude_path}" {claude_args}"'

    if args.debug:
        print(f"Command: {cmd}")

    try:
        # Launch via os.system - more reliable for 'start' command
        os.system(cmd)
    except Exception as e:
        show_error(f"Failed to launch Claude CLI:\n\n{e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
