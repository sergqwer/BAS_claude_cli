# BAS MCP Server

MCP server that enables Claude AI to control BrowserAutomationStudio (BAS) projects. Create, execute, and debug automation scripts using natural language.

## Installation

Copy these files to your BAS installation folder:

| File | Destination |
|------|-------------|
| `index.js` | `BrowserAutomationStudio\apps\29.6.1\html\scenario\helper\index.js` |
| `bas_mcp.exe` | `BrowserAutomationStudio\apps\29.6.1\Worker.31\bas_mcp.exe` |
| `HelperGui.exe` | `BrowserAutomationStudio\apps\29.6.1\Worker.31\HelperGui.exe` |

> **⚠️ Restart BAS after copying `index.js`!**

## Configuration

Add to Claude Code settings (`.claude/settings.json`):

```json
{
  "mcpServers": {
    "bas": {
      "command": "D:\\BAS\\BrowserAutomationStudio\\apps\\29.6.1\\Worker.31\\bas_mcp.exe",
      "args": ["--pid", "<BAS_PID>"]
    }
  }
}
```

Replace `<BAS_PID>` with BAS process ID (visible in Task Manager or BAS title bar).

## Features

- Create/edit/delete BAS actions
- Control script execution (play, pause, step, restart)
- Get page HTML, screenshots, check elements
- Inspect variables and debug scripts
- Work with functions and custom modules

## License

MIT
