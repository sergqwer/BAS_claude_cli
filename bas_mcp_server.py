#!/usr/bin/env python3
"""
BAS MCP Server - provides BAS control as tools for Claude CLI.

This server exposes BAS automation through MCP protocol using file-based IPC.
Uses hex-encoded messages via BrowserAutomationStudio_SendMessageToHelper.

Usage:
    python bas_mcp_server.py --pid <BAS_PID>

Or as compiled EXE:
    bas_mcp.exe --pid <BAS_PID>
"""

import json
import sys
import os
import asyncio
import argparse
from typing import Any, Dict, List, Optional

# CRITICAL: Set UTF-8 encoding and UNBUFFERED I/O BEFORE any operations
# This fixes: 1) Ukrainian/Cyrillic text corruption 2) MCP response delays
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
os.environ.setdefault('PYTHONUNBUFFERED', '1')

# Reconfigure for UTF-8 with line buffering (buffering=1) for faster response
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
if hasattr(sys.stdin, 'reconfigure'):
    sys.stdin.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from bas_client import (BASClient, get_exe_directory, find_helperipc_dir,
                        find_logs_dir, list_log_files, read_log_file)


# ============= ACTION HELP DATABASE =============
# Detailed help for each action type, returned by bas_get_action_help
ACTION_HELP = {
    # === BROWSER NAVIGATION ===
    "load": {
        "name": "Load URL",
        "category": "Browser Navigation",
        "description": "Navigate browser to specified URL",
        "params": {
            "LoadUrl": "(required) URL to load, can include [[VARIABLES]]",
            "Referrer": "(optional) Referrer URL to send"
        },
        "example": {"LoadUrl": "https://example.com", "Referrer": "https://google.com"}
    },
    "url": {
        "name": "Get Current URL",
        "category": "Browser Navigation",
        "description": "Save current page URL to a variable",
        "params": {
            "SaveUrl": "(required) Variable name to save URL (without VAR_ prefix)"
        },
        "example": {"SaveUrl": "CURRENT_URL"}
    },
    "page": {
        "name": "Execute Page JavaScript",
        "category": "Browser Navigation",
        "description": "Execute JavaScript code on the current page context",
        "params": {
            "Code": "(required) JavaScript code to execute"
        },
        "example": {"Code": "document.querySelector('iframe').remove();"}
    },

    # === ELEMENT INTERACTION ===
    "wait_element_visible": {
        "name": "Wait For Element & Click",
        "category": "Element Interaction",
        "description": "Wait for element to become visible, then optionally click it. Most common click action!",
        "requires_path": True,
        "params": {
            "PATH": "(required) Element selector: >CSS> #id, >XPATH> //button",
            "Select": "(optional) Click button: 'left', 'right', 'middle'",
            "Check": "(optional) If true, also clicks the element",
            "Check2": "(optional) Additional click option",
            "Speed": "(optional) Mouse movement speed, default '100'",
            "Gravity": "(optional) Mouse curve gravity, default '6'",
            "Deviation": "(optional) Mouse curve deviation, default '2.5'",
            "TypeData": "(optional) Text to type after clicking",
            "TypeInterval": "(optional) Typing speed in ms"
        },
        "example": {"PATH": ">CSS> #login-btn", "Select": "left", "Check": False}
    },
    "wait_element": {
        "name": "Wait For Element",
        "category": "Element Interaction",
        "description": "Wait for element to appear in DOM (not necessarily visible)",
        "requires_path": True,
        "params": {
            "PATH": "(required) Element selector",
            "SaveXml": "(optional) Save element's outer HTML to variable",
            "SaveText": "(optional) Save element's text content to variable"
        },
        "example": {"PATH": ">CSS> .result", "SaveXml": "SAVED_XML"}
    },
    "get_element_selector": {
        "name": "Check Element Exists",
        "category": "Element Interaction",
        "description": "Check if element exists, with option to check visibility",
        "requires_path": True,
        "params": {
            "PATH": "(required) Element selector",
            "Save": "(required) Variable name to save result (true/false)",
            "Check": "(optional) If true, checks visibility too; if false, only DOM existence"
        },
        "example": {"PATH": ">CSS> #submit-btn", "Save": "IS_EXISTS", "Check": True}
    },
    "type": {
        "name": "Type Text",
        "category": "Element Interaction",
        "description": "Type text into the currently focused element (use after click)",
        "params": {
            "TypeData": "(required) Text to type. Special keys: <RETURN>, <TAB>, <ESCAPE>, <BACKSPACE>, <DELETE>, <UP>, <DOWN>, <LEFT>, <RIGHT>, <HOME>, <END>, <CTRL>, <ALT>, <SHIFT>",
            "TypeInterval": "(optional) Delay between keystrokes in ms, default '100'"
        },
        "example": {"TypeData": "username<TAB>password<RETURN>", "TypeInterval": "50"}
    },

    # === DELAYS & WAITING ===
    "sleep": {
        "name": "Sleep/Delay",
        "category": "Delays",
        "description": "Pause execution for specified time",
        "params": {
            "sleepfrom": "(required) Minimum delay in milliseconds",
            "sleepto": "(required) Maximum delay in milliseconds (for random delay)",
            "sleepfromto": "(optional) Alternative max value",
            "sleeprandom": "(optional) If true, uses random delay between from-to"
        },
        "example": {"sleepfrom": "1000", "sleepto": "3000", "sleeprandom": False}
    },
    "waiter_timeout_next": {
        "name": "Set Timeout For Next Waiter",
        "category": "Delays",
        "description": "Set custom timeout for the next wait_element action",
        "params": {
            "Value": "(required) Timeout in milliseconds",
            "Check": "(optional) Additional option"
        },
        "example": {"Value": "10000"}
    },
    "waiter_nofail_next": {
        "name": "No Fail For Next Waiter",
        "category": "Delays",
        "description": "Make next wait_element not fail if element not found",
        "params": {
            "Select": "(optional) Click button type",
            "Speed": "(optional) Mouse speed",
            "Gravity": "(optional) Mouse curve gravity",
            "Deviation": "(optional) Mouse curve deviation"
        },
        "example": {}
    },

    # === VARIABLES ===
    "PSet": {
        "name": "Set/Increment Variable",
        "category": "Variables",
        "description": "Set variable value or increment existing variable",
        "params": {
            "SetVariableName": "(required) Variable name (without VAR_ prefix)",
            "SetVariableValue": "(optional) Value to set",
            "IncVariableValue": "(optional) Value to add to current value",
            "Name": "(optional) Alternative param for variable name",
            "Value": "(optional) Alternative param for value"
        },
        "example_set": {"SetVariableName": "COUNTER", "SetVariableValue": "0"},
        "example_inc": {"SetVariableName": "COUNTER", "IncVariableValue": "1"}
    },
    "RS": {
        "name": "Resource/String Operations",
        "category": "Variables",
        "description": "Various string operations, regex matching, resource iteration",
        "params": {
            "Value": "(optional) Input value or string",
            "Regexp": "(optional) Regular expression pattern",
            "Result": "(optional) Save match result",
            "ResultAll": "(optional) Save all matches",
            "Save": "(optional) Variable to save result",
            "ForFrom": "(optional) Loop start index",
            "ForTo": "(optional) Loop end index"
        },
        "example": {"Value": "[[INPUT]]", "Regexp": "\\d+", "Save": "NUMBERS"}
    },

    # === CONDITIONS ===
    "if": {
        "name": "If Condition",
        "category": "Conditions",
        "description": "Conditional branch based on expression",
        "params": {
            "IfExpression": "(required) JavaScript expression, use [[VAR]] for variables",
            "IfElse": "(optional) If true, has else branch"
        },
        "example": {"IfExpression": "[[COUNTER]] > 10", "IfElse": True}
    },
    "set_if_expression": {
        "name": "Set If Expression",
        "category": "Conditions",
        "description": "Same as 'if' - conditional execution",
        "params": {
            "IfExpression": "(required) JavaScript expression",
            "IfElse": "(optional) Has else branch"
        },
        "example": {"IfExpression": "[[STATUS]] == \"success\"", "IfElse": False}
    },
    "cycle_params": {
        "name": "Cycle Parameters (Loop Condition)",
        "category": "Conditions",
        "description": "Set parameters for loop continuation condition",
        "params": {
            "IfExpression": "(required) Loop continuation expression",
            "IfElse": "(optional) Has else handling"
        },
        "example": {"IfExpression": "[[INDEX]] < [[TOTAL]]", "IfElse": True}
    },

    # === LOOPS ===
    "do": {
        "name": "Do/While Loop",
        "category": "Loops",
        "description": "Loop with while condition or for-style iteration",
        "params": {
            "WhileExpression": "(for while) JavaScript condition",
            "ForFrom": "(for for-loop) Start index",
            "ForTo": "(for for-loop) End index"
        },
        "example_while": {"WhileExpression": "[[CONTINUE]] == true"},
        "example_for": {"ForFrom": "1", "ForTo": "10"}
    },
    "do_with_params": {
        "name": "For Each Loop",
        "category": "Loops",
        "description": "Iterate over array variable",
        "params": {
            "ForArray": "(required) Array variable to iterate, use [[ARRAY_VAR]]"
        },
        "example": {"ForArray": "[[LIST_ITEMS]]"}
    },
    "break": {
        "name": "Break Loop",
        "category": "Loops",
        "description": "Exit from current loop",
        "params": {},
        "example": {}
    },
    "next": {
        "name": "Continue Loop",
        "category": "Loops",
        "description": "Skip to next iteration of current loop",
        "params": {},
        "example": {}
    },

    # === FUNCTIONS ===
    "call_function": {
        "name": "Call Function / Module",
        "category": "Functions",
        "description": """Execute a named function OR call a module action.

=== CALLING PROJECT FUNCTION ===
params={"FunctionName": "MyFunctionName"}

=== SQL MODULE ===
Execute database queries:
params={
    "query": "SELECT * FROM users WHERE id = [[USER_ID]]",
    "data_format": "CSV list",  # or "JSON", "Single value"
    "Save": "SQL_RESULTS",
    "Check": true
}
Note: SQL connection must be configured in module settings.

=== SMS MODULE ===
Work with SMS services. Params have RANDOM NAMES generated by BAS!
Look at your module's action in BAS UI to find correct param names.
Common pattern:
params={
    "<random_id>": "service-api-id",          # SMS service API ID
    "<random_phone>": "[[PHONE_NUMBER]]",      # phone number variable
    "<random_regex>": "([0-9]{4,6})",          # regex to extract code
    "<random_filter>": "verification|code",    # text filter for SMS
    "<random_timeout>": "60000",               # timeout in ms
    "<random_attempts>": "10",                 # retry attempts
    "Save": "SMS_CODE"
}

=== CAPTCHA MODULE (GeeTest, reCAPTCHA, etc.) ===
Solve captchas. Params have RANDOM NAMES!
Common pattern:
params={
    "<random_key>": "captcha-service-api-key",
    "<random_selector>": ">CSS> .captcha-container",  # captcha element
    "<random_refresh>": ">CSS> .refresh-button",      # refresh button
    "Save": "CAPTCHA_RESULT"
}

=== VPN/PROXY MODULE ===
Connect to VPN or configure proxy:
params={
    "<random_address>": "[[VPN_SERVER]]",     # server address
    "<random_data>": "[[CONNECTION_DATA]]",    # connection parameters
    "Save": "VPN_STATUS"
}

=== IMAP/EMAIL MODULE ===
Read emails via IMAP:
params={
    "query": "UNSEEN",                         # IMAP search query
    "<random_box>": "INBOX",                   # mailbox name
    "<random_getsubject>": true,               # get subject
    "<random_getbody>": true,                  # get body
    "<random_savesubject>": "EMAIL_SUBJECT",
    "<random_savebody>": "EMAIL_BODY",
    "Save": "EMAIL_LIST"
}

IMPORTANT: Module params have random names like 'hkvfgjkd', 'rxenllxc'.
These are unique per module installation. Check your BAS project to see actual param names.
""",
        "params": {
            "FunctionName": "(optional) Function name to call, empty for module actions",
            "query": "(for SQL/IMAP) Query string",
            "data_format": "(for SQL) Result format: 'CSV list', 'JSON', 'Single value'",
            "Check": "(optional) Enable/check option",
            "Save": "(optional) Variable to save result"
        },
        "example": {"FunctionName": "ProcessItem"},
        "example_sql": {"query": "SELECT * FROM users LIMIT 10", "data_format": "CSV list", "Save": "RESULTS", "Check": True}
    },
    "call": {
        "name": "Call Module Function",
        "category": "Functions",
        "description": """Call a BAS module/extension function. Common modules:

=== FINGERPRINTSWITCHER MODULE ===
Apply browser fingerprint to avoid detection:
params={
    "Fingerprint": "[[FINGERPRINT_DATA]]",  # fingerprint JSON from GetFingerprint
    "Key": "your-api-key",                   # module license key
    "PerfectCanvas": "true",                 # enable perfect canvas emulation
    "CanvasNoise": "false",                  # add noise to canvas (alternative to PerfectCanvas)
    "WebglNoise": "false",                   # add noise to WebGL
    "AudioNoise": "false",                   # add noise to audio context
    "SafeBattery": "true",                   # safe battery API emulation
    "FontData": "true",                      # use fingerprint fonts
    "SafeRectangles": "false",               # safe getBoundingClientRect
    "EmulateSensor": "true",                 # emulate device sensors
    "EmulateDeviceScaleFactor": "true"       # emulate device pixel ratio
}

=== IP INFO / GEOLOCATION MODULE ===
Get IP information and apply geolocation:
params={
    "Value": "[[IP_ADDRESS]]",               # IP to lookup
    "IpInfoMethod": "database",              # method: 'database' or 'api'
    "IpApiKey": "your-api-key",              # API key if using api method
    "ChangeTimezone": "true",                # apply timezone from IP
    "ChangeGeolocation": "true",             # apply geolocation from IP
    "ChangeWebrtcIp": "true",                # change WebRTC IP
    "ChangeBrowserLanguage": "true",         # change browser language
    # Save results to variables:
    "SaveValid": "IPINFO_VALID",
    "SaveCountry": "IPINFO_COUNTRY",
    "SaveCity": "IPINFO_CITY",
    "SaveLatitude": "IPINFO_LATITUDE",
    "SaveLongitude": "IPINFO_LONGITUDE",
    "SaveTimezone": "IPINFO_TIMEZONE",
    "SaveOffset": "IPINFO_OFFSET",
    "SaveDstOffset": "IPINFO_DST_OFFSET"
}

=== GET FINGERPRINT ===
Get fingerprint from service:
params={
    "FunctionName": "",  # empty for GetFingerprint
    # Module-specific params with random names - check your module's UI
    "Save": "FINGERPRINT"
}
""",
        "params": {
            "FunctionName": "(optional) Empty or specific function name",
            "Key": "(optional) Module API/license key",
            "Value": "(optional) Input value (IP address, etc.)",
            "Fingerprint": "(optional) Fingerprint JSON data",
            "Save": "(optional) Variable to save result"
        },
        "example": {"Fingerprint": "[[FINGERPRINT]]", "PerfectCanvas": "true", "CanvasNoise": "false"}
    },
    "section_insert": {
        "name": "Section/Function Definition",
        "category": "Functions",
        "description": "Defines a new function/section (created via BAS UI or bas_create_function)",
        "params": {},
        "note": "Usually created via bas_create_function MCP tool, not directly"
    },

    # === LOGGING ===
    "logger_log": {
        "name": "Log Message",
        "category": "Logging",
        "description": "Write message to BAS log panel",
        "params": {
            "ru": "(required) Message text (Russian locale)",
            "en": "(required) Message text (English locale)",
            "level": "(optional) 'info', 'warning', or 'error'",
            "color": "(optional) 'orange', 'red', 'green', 'blue', 'white'"
        },
        "example": {"ru": "Status: [[STATUS]]", "en": "Status: [[STATUS]]", "level": "info", "color": "green"}
    },
    "logger_success": {
        "name": "Log Success",
        "category": "Logging",
        "description": "Log success message",
        "params": {
            "ru": "(required) Success message (Russian)",
            "en": "(required) Success message (English)"
        },
        "example": {"ru": "Done!", "en": "Done!"}
    },

    # === STATUS ===
    "success": {
        "name": "Mark Success",
        "category": "Status",
        "description": "Mark current thread/task as successful",
        "params": {
            "SuccessMessage": "(optional) Success message to display"
        },
        "example": {"SuccessMessage": "Task completed successfully"}
    },
    "fail": {
        "name": "Mark Fail",
        "category": "Status",
        "description": "Mark current thread/task as failed and save data",
        "params": {
            "Data": "(optional) Data to save with failure",
            "Path": "(optional) Path for saving data",
            "Save": "(optional) Variable to save status"
        },
        "example": {"Data": "[[ERROR_MSG]]"}
    },
    "fail_user": {
        "name": "Fail With Message",
        "category": "Status",
        "description": "Fail with custom error message for user",
        "params": {
            "FailMessage": "(required) Error message to show",
            "Check": "(optional) Additional option"
        },
        "example": {"FailMessage": "Login failed: invalid credentials", "Check": False}
    },
    "result": {
        "name": "Set Result",
        "category": "Status",
        "description": "Set thread result value",
        "params": {
            "Value": "(required) Result value",
            "Select": "(optional) Result type selection"
        },
        "example": {"Value": "[[OUTPUT_DATA]]", "Select": "1"}
    },

    # === BROWSER SETTINGS ===
    "browser_mode": {
        "name": "Browser Mode",
        "category": "Browser Settings",
        "description": "Enable or disable browser mode",
        "params": {
            "Enable": "(required) true/false to enable/disable browser"
        },
        "example": {"Enable": True}
    },
    "require_extensions": {
        "name": "Require Extensions",
        "category": "Browser Settings",
        "description": "Configure browser extensions and settings",
        "params": {
            "QUIC": "(optional) 'enable'/'disable' QUIC protocol",
            "Tunneling": "(optional) 'enable'/'disable' tunneling",
            "MaxFPS": "(optional) Max FPS limit",
            "BrowserVersion": "(optional) Browser version",
            "CommandLine": "(optional) Additional command line args",
            "Path": "(optional) Profile path: 'temporary' or custom"
        },
        "example": {"QUIC": "enable", "MaxFPS": "30", "Path": "temporary"}
    },
    "cache_allow": {
        "name": "Cache Allow",
        "category": "Browser Settings",
        "description": "Configure caching rules for requests",
        "params": {
            "urlFilters": "(required) Array of URL filter objects",
            "methods": "(optional) HTTP methods: 'ALL', 'GET', 'POST', etc.",
            "limit": "(optional) Cache limit",
            "Save": "(optional) Variable to save rule ID"
        },
        "example": {"urlFilters": [{"type": "Contains", "match": True, "value": {"data": "api.example.com"}}], "methods": "GET"}
    },
    "default_move_params": {
        "name": "Default Mouse Movement",
        "category": "Browser Settings",
        "description": "Set default parameters for mouse movement",
        "params": {
            "Speed": "(required) Mouse speed expression",
            "Gravity": "(required) Curve gravity expression",
            "Deviation": "(required) Curve deviation expression"
        },
        "example": {"Speed": "rand(150,400)", "Gravity": "rand(7,10)", "Deviation": "rand(10,30) * 0.01"}
    },
    "get_browser_screen_settings": {
        "name": "Get Browser Screen Settings",
        "category": "Browser Settings",
        "description": "Get current browser viewport and cursor position",
        "params": {
            "CursorX": "(optional) Save relative cursor X",
            "CursorY": "(optional) Save relative cursor Y",
            "CursorAbsoluteX": "(optional) Save absolute cursor X",
            "CursorAbsoluteY": "(optional) Save absolute cursor Y",
            "ScrollX": "(optional) Save scroll X position",
            "ScrollY": "(optional) Save scroll Y position",
            "Width": "(optional) Save viewport width",
            "Height": "(optional) Save viewport height"
        },
        "example": {"CursorX": "CURSOR_X", "CursorY": "CURSOR_Y", "Width": "WIDTH", "Height": "HEIGHT"}
    },

    # === HTTP & NETWORK ===
    "switch_http_client_main": {
        "name": "HTTP Request",
        "category": "HTTP",
        "description": "Make HTTP request outside of browser",
        "params": {
            "Value": "(required) URL for the request",
            "Method": "(required) HTTP method: 'GET', 'POST', 'PUT', 'DELETE'",
            "PostDataRaw": "(optional) POST body data",
            "ContentType": "(optional) Content type: 'urlencode', 'json', 'multipart'",
            "ContentTypeRaw": "(optional) Raw content-type header",
            "Encoding": "(optional) Response encoding, default 'UTF-8'",
            "Headers": "(optional) Custom headers",
            "Check": "(optional) If true, saves response",
            "Check2": "(optional) Additional option"
        },
        "example": {"Value": "https://api.example.com/data", "Method": "POST", "PostDataRaw": "{\"key\":\"value\"}", "ContentTypeRaw": "application/json", "Check": True}
    },
    "replace_request_content": {
        "name": "Replace Request Content",
        "category": "HTTP",
        "description": "Intercept and modify outgoing requests",
        "params": {
            "urlFilters": "(required) URL filters array",
            "replaceMode": "(optional) 'regexp', 'exact', etc.",
            "regexp": "(optional) Regex pattern to find",
            "newValue": "(optional) Replacement value",
            "methods": "(optional) HTTP methods to intercept",
            "Save": "(optional) Variable to save rule ID"
        },
        "example": {"urlFilters": [{"type": "Contains", "match": True, "value": {"data": "api.example.com"}}], "replaceMode": "regexp", "regexp": "old_value", "newValue": "new_value"}
    },
    "replace_response_content": {
        "name": "Replace Response Content",
        "category": "HTTP",
        "description": "Intercept and modify incoming responses",
        "params": {
            "urlFilters": "(required) URL filters array",
            "replaceMode": "(optional) 'regexp', 'exact', etc.",
            "regexp": "(optional) Regex pattern to find",
            "newValue": "(optional) Replacement value",
            "methods": "(optional) HTTP methods to intercept",
            "Save": "(optional) Variable to save rule ID"
        },
        "example": {"urlFilters": [{"type": "Contains", "match": True, "value": {"data": "api.example.com"}}], "replaceMode": "regexp", "regexp": "\"score\": 0.\\d", "newValue": "\"score\": 0.9"}
    },
    "disable_rules": {
        "name": "Disable Network Rules",
        "category": "HTTP",
        "description": "Disable active request/response modification rules",
        "params": {
            "ids": "(required) Array or variable with rule IDs to disable, [[RULE_IDS]]"
        },
        "example": {"ids": "[[ACTIVE_RULE_IDS]]"}
    },
    "get_rule_stats": {
        "name": "Get Rule Statistics",
        "category": "HTTP",
        "description": "Get statistics for a network modification rule",
        "params": {
            "id": "(required) Rule ID, [[RULE_ID]]",
            "SaveExecutionCount": "(optional) Save execution count",
            "SaveIsActive": "(optional) Save active status",
            "SaveAllIds": "(optional) Save all rule IDs",
            "SaveActiveIds": "(optional) Save active rule IDs"
        },
        "example": {"id": "[[RULE_ID]]", "SaveExecutionCount": "RULE_COUNT", "SaveIsActive": "RULE_ACTIVE"}
    },
    "set_proxy_for_next_profile": {
        "name": "Set Proxy For Next Profile",
        "category": "HTTP",
        "description": "Set proxy for the next browser profile",
        "params": {
            "Code": "(required) Proxy string in format: type://user:pass@host:port"
        },
        "example": {"Code": "_set_proxy_for_next_profile(VAR_PROXY_TYPE + \"://\" + VAR_PROXY)!"}
    },

    # === FILES ===
    "native": {
        "name": "Native File Operation",
        "category": "Files",
        "description": "Read/write files on disk",
        "params": {
            "File": "(required) File path, can use [[PROJECT_DIRECTORY]]",
            "Value": "(optional) Content to write",
            "Check": "(optional) Options",
            "Check2": "(optional) Options",
            "Check3": "(optional) Options"
        },
        "example_write": {"File": "[[PROJECT_DIRECTORY]]/output.txt", "Value": "[[DATA]]"},
        "example_read": {"File": "[[PROJECT_DIRECTORY]]/input.txt"}
    },
    "save_cookies": {
        "name": "Save Cookies",
        "category": "Files",
        "description": "Save browser cookies to variable",
        "params": {
            "Domain": "(optional) Filter by domain",
            "Save": "(required) Variable name to save cookies"
        },
        "example": {"Save": "SAVED_COOKIES"}
    },

    # === RESOURCES ===
    "RInsert": {
        "name": "Insert Into Resource",
        "category": "Resources",
        "description": "Insert data into a resource (list/file)",
        "params": {
            "ResourceName": "(required) Name of the resource",
            "Data": "(required) Data to insert, can use [[VARIABLE]]",
            "Check": "(optional) Options",
            "Check2": "(optional) Options"
        },
        "example": {"ResourceName": "accounts", "Data": "[[NEW_ACCOUNT]]", "Check": True}
    },

    # === HTML PARSING ===
    "html_parser_xpath_parse": {
        "name": "XPath Parse HTML",
        "category": "HTML Parsing",
        "description": "Parse HTML/XML using XPath expression",
        "params": {
            "Text": "(required) HTML/XML content, [[VARIABLE]]",
            "Value": "(required) XPath expression",
            "Save": "(required) Variable to save result",
            "Check": "(optional) Options"
        },
        "example": {"Text": "[[PAGE_HTML]]", "Value": "//a/@href", "Save": "LINKS", "Check": False}
    },

    # === SPECIAL ===
    "unknown": {
        "name": "Various Utility Actions",
        "category": "Special",
        "description": """BAS uses type='unknown' for many utility actions. The actual operation is determined by parameters.

COMMON OPERATIONS (all use type='unknown'):

1. SET VARIABLE:
   params={"SetVariableName": "MYVAR", "SetVariableValue": "value or [[OTHER_VAR]]"}

2. STRING CONTAINS (check if substring exists):
   params={"string": "[[TEXT]]", "substring": "@", "from": "", "Save": "CONTAINS_RESULT"}
   Result: saves index of substring or -1 if not found

3. STRING REPLACE:
   params={"Value": "[[TEXT]]", "ReplaceFrom": "+", "ReplaceTo": "", "Save": "RESULT"}

4. STRING ENCODE/DECODE:
   params={"string": "[[TEXT]]", "Save": "RESULT", "Select": "decode"}
   Select options: encode, decode, base64encode, base64decode, urlencode, urldecode, md5, sha1

5. STRING SPLIT:
   params={"string": "[[TEXT]]", "separators": "_", "VariablesList": "VAR1,VAR2,VAR3", "ResultAsList": "LIST_VAR", "Check": false}

6. GET LIST ELEMENT:
   params={"Variable": "MY_LIST", "Index": "0", "VariableResult": "FIRST_ITEM", "Check": false}

7. GET LIST LENGTH:
   params={"Variable": "MY_LIST", "VariableLength": "LIST_LEN"}

8. READ FILE:
   params={"Value": "path/to/file.txt", "Save": "FILE_CONTENT", "From": "0", "To": "0", "Check": false}
   From/To: line range (0,0 = all lines)

9. GET FILE INFO:
   params={"Value": "path/to/file", "SaveExists": "EXISTS", "SaveSize": "SIZE", "SaveLastModified": "MODIFIED"}

10. EXECUTE JAVASCRIPT:
    params={"Code": "VAR_RESULT = Date.now()"}
    Note: Use VAR_ prefix in JS code

11. GET PROJECT DIRECTORY:
    params={"Save": "PROJECT_DIRECTORY"}

12. GET RANDOM NUMBER:
    params={"MinValue": "1", "MaxValue": "100", "Save": "RANDOM_NUM"}

13. GET RESOURCE PATH:
    params={"ResourceName": "accounts", "Save": "RESOURCE_PATH"}
""",
        "note": "Use bas_get_action_schema for official BAS params. These are common patterns found in real projects."
    },

    # === RESOURCES (additional) ===
    "RCreate": {
        "name": "Create Resource",
        "category": "Resources",
        "description": "Create a new resource (list/queue) for data storage and iteration",
        "params": {
            "Name": "(required) Resource name",
            "SuccessNumber": "(optional) Success count, default 1",
            "FailNumber": "(optional) Fail count, default 1",
            "SimultaneousUsage": "(optional) Max simultaneous usage",
            "Interval": "(optional) Interval in ms between uses",
            "Check": "(optional) Options",
            "Check2": "(optional) Options"
        },
        "example": {"Name": "my_queue", "SuccessNumber": "1", "FailNumber": "1", "Interval": "5000"}
    },

    # === FUNCTIONS (additional) ===
    "function_return": {
        "name": "Return From Function",
        "category": "Functions",
        "description": "Return a value from current function and exit",
        "params": {
            "ReturnValue": "(required) Value to return, can use [[VARIABLE]]"
        },
        "example": {"ReturnValue": "[[RESULT]]"}
    },

    # === BROWSER SETTINGS (additional) ===
    "general_timeout": {
        "name": "Set General Timeout",
        "category": "Browser Settings",
        "description": "Set global timeout for operations",
        "params": {
            "Value": "(required) Timeout in milliseconds",
            "Type": "(optional) Timeout type, e.g. 'general'"
        },
        "example": {"Value": "20000", "Type": "general"}
    },
    "resize": {
        "name": "Resize Browser Window",
        "category": "Browser Settings",
        "description": "Resize browser viewport to specified dimensions",
        "params": {
            "ResizeX": "(required) Width in pixels, can use [[VARIABLE]]",
            "ResizeY": "(required) Height in pixels, can use [[VARIABLE]]"
        },
        "example": {"ResizeX": "1920", "ResizeY": "1080"}
    },

    # === MOUSE/INPUT ===
    "mouse": {
        "name": "Move Mouse",
        "category": "Element Interaction",
        "description": "Move mouse cursor to specific coordinates",
        "params": {
            "ClickX": "(required) X coordinate",
            "ClickY": "(required) Y coordinate"
        },
        "example": {"ClickX": "500", "ClickY": "300"}
    },

    # === POPUPS/TABS ===
    "popupcreate2": {
        "name": "Open New Tab/Popup",
        "category": "Browser Navigation",
        "description": "Open a new browser tab or popup window",
        "params": {
            "Url": "(required) URL to open in new tab",
            "IsSilent": "(optional) If 'true', open in background",
            "Referrer": "(optional) Referrer URL"
        },
        "example": {"Url": "https://example.com", "IsSilent": "false"}
    },
    "popupselect": {
        "name": "Select Tab/Popup",
        "category": "Browser Navigation",
        "description": "Switch to a specific browser tab by index",
        "params": {
            "Index": "(required) Tab index (0 = first tab, 1 = second, etc.)"
        },
        "example": {"Index": "0"}
    },

    # === DELAYS (additional) ===
    "wait_async_load": {
        "name": "Wait For Async Load",
        "category": "Delays",
        "description": "Wait for asynchronous content (AJAX, fetch) to finish loading",
        "params": {},
        "example": {}
    },

    # === LOGGING (additional) ===
    "log": {
        "name": "Simple Log",
        "category": "Logging",
        "description": "Write a simple log message (alternative to logger_log)",
        "params": {
            "LogText": "(required) Text to log, can include [[VARIABLES]]"
        },
        "example": {"LogText": "Processing item [[INDEX]] of [[TOTAL]]"}
    },

    # === CONTROL FLOW ===
    "set_goto_label": {
        "name": "Set Label",
        "category": "Control Flow",
        "description": "Define a label that can be jumped to with long_goto",
        "params": {
            "Label": "(required) Label name (alphanumeric, no spaces)"
        },
        "example": {"Label": "retry_point"}
    },
    "long_goto": {
        "name": "Goto Label",
        "category": "Control Flow",
        "description": "Jump to a previously defined label (use sparingly, prefer loops)",
        "params": {
            "LabelName": "(required) Name of label to jump to"
        },
        "example": {"LabelName": "retry_point"}
    },

    # === FILES (additional) ===
    "native_async": {
        "name": "Async File List",
        "category": "Files",
        "description": "Asynchronously scan folder and get list of files",
        "params": {
            "Folder": "(required) Path to folder to scan",
            "Mask": "(required) File mask pattern, e.g. '*.txt', '*.json'",
            "FileContains": "(optional) Filter files containing this text",
            "Save": "(required) Variable to save file list",
            "Check": "(optional) Include subdirectories",
            "Check2": "(optional) Return full paths",
            "Check3": "(optional) Additional option"
        },
        "example": {"Folder": "C:/data", "Mask": "*.csv", "Save": "FILE_LIST", "Check": True}
    },

    # === JAVASCRIPT ===
    "parseInt": {
        "name": "Execute JavaScript (parseInt)",
        "category": "JavaScript",
        "description": "Execute JavaScript code (named parseInt but can run any JS)",
        "params": {
            "Code": "(required) JavaScript code to execute, use VAR_ prefix for variables"
        },
        "example": {"Code": "VAR_RESULT = parseInt(VAR_INPUT) + 100"}
    },

    # === CAPTCHA ===
    "solver_properties_clear": {
        "name": "Configure Captcha Solver",
        "category": "Captcha",
        "description": "Clear and configure captcha solver settings (CapMonster, 2Captcha, etc.)",
        "params": {
            "Code": "(required) Solver configuration code"
        },
        "example": {"Code": "solver_properties_clear(\"capmonster\")\nsolver_property(\"capmonster\",\"serverurl\",\"http://localhost:8080\")"}
    }
}


# Global BAS client
_client: Optional[BASClient] = None
_event_loop: Optional[asyncio.AbstractEventLoop] = None


def get_tools_list() -> List[Dict]:
    """Return list of all available MCP tools with detailed descriptions."""
    return [
        # ============= CONNECTION =============
        {
            "name": "bas_ping",
            "description": """Check connection to BAS (Browser Automation Studio).
Call this first to verify BAS is running and responding.
Returns: {success: true/false, message: string}""",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },

        # ============= SCRIPT CONTROL =============
        {
            "name": "bas_play",
            "description": """Start or continue script execution in BAS.
Use this to run the automation script from current position.
The script will execute all actions until completion or error.
Returns: {success: true/false, action: "play"}""",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "bas_step_next",
            "description": """Execute only the next action and pause.
Perfect for debugging - executes one action at a time.
Use with bas_move_execution_point to test specific actions.
Returns: {success: true/false, action: "step-next"}""",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "bas_pause",
            "description": """Pause script execution.
Stops the running script at current position.
Use bas_play to continue or bas_step_next to step through.
Returns: {success: true/false, action: "pause"}""",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "bas_restart",
            "description": """Restart script from the beginning.
Resets execution to first action in Record mode.
All variables are reset to initial state.
Returns: {success: true/false, action: "restart"}""",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "bas_get_status",
            "description": """Get current script execution status.
Shows if script is running, paused, stopped, or in record mode.
Returns: {success: true, status: string, is_executing: bool, is_recording: bool}""",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },

        # ============= MODULE DISCOVERY =============
        {
            "name": "bas_list_modules",
            "description": """Get list of all available BAS action modules.
Modules group related actions: Browser (navigation, clicks), Logic (if/else, loops),
Tools (files, strings), Waiters (delays, element waits), etc.
Use this to discover what categories of actions are available.
Returns: [{id: "browser", name: "Browser Actions"}, ...]""",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "bas_list_actions",
            "description": """Get list of actions available in a specific module.
Pass module ID from bas_list_modules, or '*' to get ALL actions.
Example: module="browser" returns load, click, type, scroll, etc.
Returns: [{id: "load", name: "Load URL"}, {id: "click", name: "Click Element"}, ...]""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "module": {
                        "type": "string",
                        "description": "Module ID (e.g., 'browser', 'logic', 'tools') or '*' for all actions"
                    }
                },
                "required": ["module"]
            }
        },
        {
            "name": "bas_get_action_schema",
            "description": """Get detailed parameter schema for a specific action.
Shows all parameters with names, types, and descriptions.
ALWAYS call this before bas_create_action to know correct parameter names!
Example: action="load" returns params: LoadUrl, Referrer, etc.
Returns: {action: "load", name: "Load URL", params: [{id: "LoadUrl", name: "URL to load", type: "string"}, ...]}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action ID (e.g., 'load', 'click', 'type', 'log', 'sleep')"
                    }
                },
                "required": ["action"]
            }
        },

        # ============= PROJECT OPERATIONS =============
        {
            "name": "bas_get_project",
            "description": """Get all actions in the current BAS project.
Returns the complete project structure with action IDs, types, parameters.
Use action IDs for bas_update_action, bas_delete_actions, bas_move_execution_point.
Returns: {actions: [{id: 123, type: "load", params: {LoadUrl: "..."}, comment: "..."}, ...], count: N}""",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "bas_create_action",
            "description": """Create a new action in the BAS project.

IMPORTANT: Call bas_get_action_help(action="action_type") to get detailed params for ANY action!

Quick examples:
  action="load", params={"LoadUrl": "https://google.com"}
  action="wait_element_visible", params={"PATH": ">CSS> #login-btn"}
  action="sleep", params={"sleepfrom": "1000", "sleepto": "3000"}

When execute=true:
- Creates action, runs it immediately, waits for completion (up to 60s)
- Returns HTML of page after execution (unless include_html=false)

=== PATH SELECTOR FORMAT (for element actions) ===
CSS:    >CSS> #id | >CSS> .class | >CSS> [attr="val"] | >CSS> .items >AT> 0
XPATH:  >XPATH> //button[@type="submit"]
MATCH:  >MATCH>button text (NO space! Use as LAST RESORT only!)
FRAME:  >CSS> iframe >FRAME> >CSS> #element-inside

=== COMMON ACTIONS (call bas_get_action_help for full details) ===
Browser:  load, url, page
Elements: wait_element_visible (click!), wait_element, get_element_selector, type
Delays:   sleep, waiter_timeout_next
Variables: PSet (set/increment)
Conditions: if, set_if_expression
Loops:    do, break, next
Functions: call_function
Logging:  logger_log
Status:   success, fail, fail_user

Returns: {success: true, action_id: 123456, html: "...", url: "..."}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action type ID (e.g., 'load', 'click', 'type', 'log')"
                    },
                    "params": {
                        "type": "object",
                        "description": "Action parameters - use bas_get_action_schema to see available params"
                    },
                    "after_id": {
                        "type": "integer",
                        "description": "Insert after this action ID (0 = append at end, default)"
                    },
                    "parent_id": {
                        "type": "integer",
                        "description": "Parent action ID for nested actions like if/loop (0 = root level)"
                    },
                    "comment": {
                        "type": "string",
                        "description": "Optional comment/label displayed in BAS"
                    },
                    "color": {
                        "type": "string",
                        "description": "Action color: white, green (default), brown, lightblue, darkblue, red"
                    },
                    "execute": {
                        "type": "boolean",
                        "description": "If true, execute action immediately after creating and wait for result (default: false)"
                    },
                    "include_html": {
                        "type": "boolean",
                        "description": "If execute=true, include page HTML in response (default: true)"
                    }
                },
                "required": ["action"]
            }
        },
        {
            "name": "bas_update_action",
            "description": """Update an existing action's parameters or comment.
Get action_id from bas_get_project.
Can update params (merged with existing) and/or comment.
Returns: {success: true/false}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action_id": {
                        "type": "integer",
                        "description": "ID of the action to update (from bas_get_project)"
                    },
                    "params": {
                        "type": "object",
                        "description": "New parameters to set (merged with existing)"
                    },
                    "comment": {
                        "type": "string",
                        "description": "New comment/label for the action"
                    }
                },
                "required": ["action_id"]
            }
        },
        {
            "name": "bas_delete_actions",
            "description": """Delete one or more actions from the project.
Pass array of action IDs from bas_get_project.
Warning: This cannot be undone!
Returns: {success: true/false}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Array of action IDs to delete"
                    }
                },
                "required": ["action_ids"]
            }
        },
        {
            "name": "bas_run_from",
            "description": """Run scenario starting from a specific action.
Useful for testing - start execution from middle of script.
Get action_id from bas_get_project.
Returns: {success: true/false}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action_id": {
                        "type": "integer",
                        "description": "Action ID to start execution from"
                    }
                },
                "required": ["action_id"]
            }
        },

        # ============= BROWSER =============
        {
            "name": "bas_get_html",
            "description": """Get current browser page HTML content using JavaScript.
Returns the full HTML source of the currently loaded page.
Useful for analyzing page structure before creating click/type actions.

Uses browserjavascript action internally for reliable HTML retrieval.
Creates temporary action, executes it, reads result, and cleans up automatically.

Returns: {success: true, html: "<html>...</html>"}""",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "bas_get_url",
            "description": """Get current browser page URL.
Returns the URL of the currently loaded page.
Returns: {success: true, url: "https://..."}""",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },

        # ============= DEBUG / VARIABLES =============
        {
            "name": "bas_move_execution_point",
            "description": """Move the debugger cursor to a specific action.
Only works when script is paused/stopped.
After moving, use bas_step_next to execute that action.
Get action_id from bas_get_project.
Returns: {success: true, moved_to: action_id, from: previous_id}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action_id": {
                        "type": "integer",
                        "description": "Action ID to move execution point to"
                    }
                },
                "required": ["action_id"]
            }
        },
        {
            "name": "bas_get_variables",
            "description": """Get list of all variables defined in the BAS project.
Variables are named VAR_SOMETHING and can store values during execution.
Returns: {success: true, variables: ["VAR_NAME1", "VAR_NAME2"], count: N}""",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "bas_get_variable",
            "description": """Get the current value of a specific variable.
Variable must be initialized (script must have executed past its Set Variable action).
Example: name="VAR_USERNAME"
Returns: {success: true, name: "VAR_USERNAME", value: "john", type: "string"}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Variable name (e.g., 'VAR_MYVAR') - include the VAR_ prefix"
                    },
                    "no_truncate": {
                        "type": "boolean",
                        "description": "If true, return full value without truncation (default: true). Set to false for large values if you only need a preview."
                    }
                },
                "required": ["name"]
            }
        },
        {
            "name": "bas_get_resources",
            "description": """Get list of all resources defined in the BAS project.
Resources are data lists (accounts, proxies, etc.) that can be iterated.
Returns: {success: true, resources: ["accounts", "proxies"], count: N}""",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "bas_get_resource",
            "description": """Get the current value/content of a specific resource.
Resources are data lists used for iteration in scripts.
Returns: {success: true, name: "accounts", value: "current_item", total: N, index: I}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Resource name"
                    }
                },
                "required": ["name"]
            }
        },
        {
            "name": "bas_eval",
            "description": """Evaluate a JavaScript expression in BAS context.
Can access variables directly: "VAR_X + VAR_Y" or "VAR_NAME.toUpperCase()"
Simple expressions only - function calls are restricted for security.
Useful for checking variable values or simple calculations.
Returns: {success: true, expression: "...", result: value, type: "string/number/..."}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "JavaScript expression (e.g., 'VAR_X + 1', 'VAR_NAME.length')"
                    }
                },
                "required": ["expression"]
            }
        },

        # ============= FUNCTION MANAGEMENT =============
        {
            "name": "bas_list_functions",
            "description": """Get list of all functions (sections) in the BAS project.
Functions are reusable code blocks that can be called with "Call Function" action.
Special function "OnApplicationStart" runs automatically once at script startup.
Returns: {success: true, functions: [{id, name, actions_count}, ...], count: N}""",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "bas_create_function",
            "description": """Create a new function (section) in the BAS project.
Functions group actions together and can be called from anywhere in the script.
The function will be created at root level (not inside another function).
After creation, the BAS UI will navigate to the new function.
Returns: {success: true/false, function_id: ID, name: "FunctionName"}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name for the new function (must be unique)"
                    },
                    "after_function": {
                        "type": "string",
                        "description": "Optional: name of function to insert after"
                    }
                },
                "required": ["name"]
            }
        },
        {
            "name": "bas_delete_function",
            "description": """Delete a function and all actions inside it.
WARNING: This will delete the function AND all actions it contains!
Cannot delete "OnApplicationStart" function.
Returns: {success: true/false, deleted_count: N}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the function to delete"
                    },
                    "function_id": {
                        "type": "integer",
                        "description": "Alternative: ID of the function to delete"
                    }
                },
                "required": []
            }
        },
        {
            "name": "bas_open_function",
            "description": """Open/navigate to a function in the BAS UI for editing.
This will switch the BAS view to show the specified function's contents.
Use this before adding actions to a specific function.
Returns: {success: true/false, function: {id, name}}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the function to open"
                    },
                    "function_id": {
                        "type": "integer",
                        "description": "Alternative: ID of the function to open"
                    }
                },
                "required": []
            }
        },
        {
            "name": "bas_get_function_actions",
            "description": """Get all actions inside a specific function.
Returns the list of actions that belong to the specified function.
Useful for understanding what a function does or modifying its contents.
Returns: {success: true/false, function: {id, name}, actions: [...], count: N}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the function"
                    },
                    "function_id": {
                        "type": "integer",
                        "description": "Alternative: ID of the function"
                    }
                },
                "required": []
            }
        },

        # ============= SCREENSHOT =============
        {
            "name": "bas_screenshot",
            "description": """Take a screenshot of the current page or specific element.
Creates a Screenshot action, executes it, and returns the image as base64.
The temporary action is automatically cleaned up after execution.
Returns: {success: true/false, screenshot_base64: "base64_encoded_png_data"}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "Element selector (default: '>CSS> html' for full page). Use PATH format: >CSS> #id, >MATCH>text, >XPATH> //element"
                    }
                },
                "required": []
            }
        },

        # ============= ELEMENT INFO =============
        {
            "name": "bas_check_element",
            "description": """Check element existence, visibility and count on the page.
Combines three checks in one call:
- exists: whether element exists in DOM (even if hidden)
- visible: whether element exists AND is visible on screen
- count: number of elements matching the selector

IMPORTANT: Use >CSS> or >XPATH> selectors.
>MATCH> (by text/markup) should ONLY be used as LAST RESORT when CSS/XPath don't work!

Returns: {success: true, exists: true/false, visible: true/false, count: N}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "Element selector in PATH format: >CSS> #id, >CSS> .class, >XPATH> //element. Avoid >MATCH> unless absolutely necessary."
                    }
                },
                "required": ["selector"]
            }
        },

        # ============= MODULE ANALYSIS =============
        {
            "name": "bas_find_modules",
            "description": """Find all module actions (call/call_function) in the current project.

Scans project for module calls and detects their type based on parameters.
Use this to discover existing module actions that can be used as templates.

Detected module types:
- sql: SQL database queries
- sms: SMS service integrations
- captcha: Captcha solving (GeeTest, reCAPTCHA)
- fingerprint: Browser fingerprint management
- vpn: VPN/proxy connections
- imap: Email reading via IMAP
- geolocation: IP info and geolocation

Example workflow:
1. bas_find_modules(module_hint="sms") - find SMS module actions
2. bas_analyze_module(action_id=123456) - get parameter mapping
3. bas_create_from_template(template_id=123456, values={...}) - create new action

Returns: {modules: [{action_id, detected_module, params_preview, ...}], count: N}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "module_hint": {
                        "type": "string",
                        "description": "Filter by module type: 'sql', 'sms', 'captcha', 'fingerprint', 'vpn', 'imap', 'geolocation'"
                    }
                },
                "required": []
            }
        },
        {
            "name": "bas_analyze_module",
            "description": """Analyze a module action to discover its parameter mapping.

Examines an existing module action and guesses what each parameter does
based on value patterns. This helps understand what random param names mean.

Detected purposes:
- phone_number: Phone number value or variable
- regex_pattern: Regular expression
- element_selector: CSS/XPath selector
- css_selector: Simple CSS selector
- url: URL endpoint
- timeout_ms: Timeout in milliseconds
- numeric: Numeric value
- boolean: True/false flag
- filter_pattern: Pattern like "a|b|c"
- variable_reference: [[VARIABLE]] reference
- api_key_or_id: API key (hidden)
- sql_query: SQL query

Returns: {params_mapping: {"random_name": {value, guessed_purpose, description}, ...}}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action_id": {
                        "type": "integer",
                        "description": "ID of module action to analyze (from bas_find_modules or bas_get_project)"
                    }
                },
                "required": ["action_id"]
            }
        },
        {
            "name": "bas_create_from_template",
            "description": """Create a new module action based on an existing template.

Uses an existing module action as template and replaces values based on PURPOSE.
This lets you use logical names instead of random parameter names!

Example:
Template action has: {"hkvfgjkd": "[[OLD_NUMBER]]", "rxenllxc": "([0-9]{4})"}
After analysis: hkvfgjkd -> phone_number, rxenllxc -> regex_pattern

You call:
bas_create_from_template(
    template_id=123456,
    values={"phone_number": "[[MY_NUMBER]]", "regex_pattern": "([0-9]{6})"}
)

Result: New action with {"hkvfgjkd": "[[MY_NUMBER]]", "rxenllxc": "([0-9]{6})"}

Common purpose names to use in values:
- phone_number, regex_pattern, element_selector, css_selector
- url, timeout_ms, numeric, boolean, filter_pattern
- Save (for result variable)

Returns: {success: true, action_id: new_id, mapped_params: {...}}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "template_id": {
                        "type": "integer",
                        "description": "ID of existing module action to use as template"
                    },
                    "values": {
                        "type": "object",
                        "description": "New values mapped by PURPOSE (e.g., {'phone_number': '[[NUM]]', 'regex_pattern': '...'})"
                    },
                    "after_id": {
                        "type": "integer",
                        "description": "Insert after this action ID (0 = append)"
                    },
                    "parent_id": {
                        "type": "integer",
                        "description": "Parent action ID for nesting"
                    },
                    "comment": {
                        "type": "string",
                        "description": "Comment for new action"
                    }
                },
                "required": ["template_id", "values"]
            }
        },
        {
            "name": "bas_get_module_schema",
            "description": """Get detailed schema for a BAS custom module.

Returns parameter definitions including:
- Random parameter IDs and their readable descriptions
- Default values for each parameter
- Available variants/options (like dropdown lists)
- Data types (string, int, variable)

This is essential for creating module actions with correct parameters!

Example usage:
1. Find module name from existing action using bas_get_project or bas_analyze_module
2. Call bas_get_module_schema(module_name="GoodXevilPaySolver_GXP_ReCaptcha_Bypass_No_Exten", action_id=12345)
3. Use the returned schema to create new actions with correct params and defaults

Returns: {
    success: true,
    module_name: "...",
    params: [
        {id: "xknmvqbc", description: "Solve Service", data_type: "string", default_value: "SCTG", variants: ["SCTG", "Multibot"]},
        {id: "pmvdseyg", description: "ApiKey", data_type: "string", default_value: ""},
        ...
    ],
    code_params: {"apikey": "apikey", "service_solver": "Service_Solver", ...}
}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "module_name": {
                        "type": "string",
                        "description": "Full module name (e.g., 'GoodXevilPaySolver_GXP_ReCaptcha_Bypass_No_Exten')"
                    },
                    "action_id": {
                        "type": "integer",
                        "description": "Optional: ID of existing action to get code-to-param mapping"
                    }
                },
                "required": ["module_name"]
            }
        },
        {
            "name": "bas_clone_module_action",
            "description": """Clone a BAS module action with modified parameters.

This is the RECOMMENDED way to create new module actions!
It properly handles Dat JSON encoding and JavaScript code updates.

Workflow:
1. Get schema: bas_get_module_schema(module_name, template_id)
2. Find param IDs you need to change from schema
3. Clone with new values: bas_clone_module_action(template_id, new_params)

Example:
  Schema shows: pmvdseyg -> ApiKey, xknmvqbc -> Solve Service
  Clone: bas_clone_module_action(
      template_id=12345,
      new_params={"pmvdseyg": "{{apikey}}", "xknmvqbc": "Multibot"}
  )

Resources syntax in params:
  - "{{resource_name}}" - get value from resource
  - "{{resource_name|notreuse}}" - force get NEW value

Returns: {success: true, action_id: new_id, updated_params: {...}}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "template_id": {
                        "type": "integer",
                        "description": "ID of existing module action to clone"
                    },
                    "new_params": {
                        "type": "object",
                        "description": "Dict mapping param ID to new value, e.g., {'pmvdseyg': '{{apikey}}'}"
                    },
                    "comment": {
                        "type": "string",
                        "description": "Optional comment for the new action"
                    }
                },
                "required": ["template_id", "new_params"]
            }
        },

        # ============= ACTION HELP =============
        {
            "name": "bas_get_action_help",
            "description": """Get detailed help for a specific BAS action type.
ALWAYS call this before creating an action if you're not sure about its parameters!

Returns detailed information about:
- Action name and category
- All available parameters with descriptions
- Example usage with correct param names

Available action types by category:
- Browser: load, url, page
- Elements: wait_element_visible, wait_element, get_element_selector, type
- Delays: sleep, waiter_timeout_next, waiter_nofail_next
- Variables: PSet, RS
- Conditions: if, set_if_expression, cycle_params
- Loops: do, do_with_params, break, next
- Functions: call_function, call, section_insert
- Logging: logger_log, logger_success
- Status: success, fail, fail_user, result
- Browser Settings: browser_mode, require_extensions, cache_allow, default_move_params, get_browser_screen_settings
- HTTP: switch_http_client_main, replace_request_content, replace_response_content, disable_rules, get_rule_stats, set_proxy_for_next_profile
- Files: native, save_cookies
- Resources: RInsert
- HTML: html_parser_xpath_parse

Pass action="*" to get list of all documented actions.
Returns: {action: "name", name: "...", category: "...", params: {...}, example: {...}}""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action type to get help for (e.g., 'load', 'wait_element_visible', 'sleep'). Use '*' to list all."
                    }
                },
                "required": ["action"]
            }
        },

        # ============= LOGS =============
        {
            "name": "bas_list_logs",
            "description": """List available BAS project log files.
Returns list of log files sorted by date (newest first).
Log files are named by start time: 2026.01.11.04.20.11.txt""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max number of logs to return (default: 20)"
                    }
                }
            }
        },
        {
            "name": "bas_get_log",
            "description": """Read BAS project log file content.
If no log_name specified, returns the latest (most recent) log.
Useful for debugging script execution and seeing action results.""",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "log_name": {
                        "type": "string",
                        "description": "Log filename (e.g., '2026.01.11.04.20.11.txt'). If omitted, returns latest log."
                    },
                    "tail": {
                        "type": "integer",
                        "description": "Return only last N lines (0 = all lines, default)"
                    }
                }
            }
        }
    ]


def normalize_variable_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize variable references in params dict based on parameter type.

    BAS has two types of variable parameters:
    1. "Save to" params (Save, SaveUrl, Variable, SetVariableName, etc.) - need plain name: MYVAR
    2. "Value" params (SetVariableValue, Value1/2/3, TypeData, Code, etc.) - need [[MYVAR]] for variables

    This function auto-corrects Claude's common mistakes:
    - VAR_MYVAR in save param → MYVAR
    - VAR_MYVAR in value param → [[MYVAR]]
    - [[VAR_MYVAR]] → [[MYVAR]]
    """
    if not params:
        return params

    # Parameters that are "save to" targets - need plain variable name
    SAVE_PARAMS = {
        'save', 'saveurl', 'variable', 'setvariablename',
        'savelist', 'saveresult', 'savevalue', 'saveto',
        # Common patterns
    }

    # Parameters that are "value/input" - need [[]] for variable references
    VALUE_PARAMS = {
        'setvariablevalue', 'value', 'value1', 'value2', 'value3',
        'typedata', 'code', 'expression', 'text', 'data',
        'loadurl', 'url',  # URLs can contain [[vars]]
    }

    result = {}
    for key, value in params.items():
        if not isinstance(value, str):
            result[key] = value
            continue

        key_lower = key.lower()

        # Check if it's a "save to" parameter
        is_save_param = (
            key_lower in SAVE_PARAMS or
            key_lower.startswith('save') or
            key_lower.endswith('name') and 'variable' in key_lower
        )

        # Check if it's a "value/input" parameter
        is_value_param = (
            key_lower in VALUE_PARAMS or
            key_lower.startswith('value') or
            key_lower.endswith('value') or
            key_lower.endswith('data')
        )

        if is_save_param:
            # Save params: strip VAR_ and [[]] - need plain name
            clean_value = value
            if clean_value.startswith('VAR_'):
                clean_value = clean_value[4:]
            if clean_value.startswith('[[') and clean_value.endswith(']]'):
                clean_value = clean_value[2:-2]
            if clean_value.startswith('VAR_'):  # In case [[VAR_X]]
                clean_value = clean_value[4:]
            result[key] = clean_value

        elif is_value_param:
            # Value params: if it looks like a variable reference, wrap in [[]]
            if value.startswith('VAR_'):
                var_name = value[4:]  # Remove VAR_
                result[key] = f'[[{var_name}]]'
            elif '[[VAR_' in value:
                # Fix [[VAR_X]] → [[X]] anywhere in the string
                result[key] = value.replace('[[VAR_', '[[')
            else:
                result[key] = value
        else:
            # Unknown param type - just strip VAR_ prefix if present
            if value.startswith('VAR_'):
                result[key] = value[4:]
            else:
                result[key] = value

    return result


async def call_tool_async(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a tool asynchronously and return result."""
    global _client

    if _client is None:
        return {"error": "Not connected to BAS. Server must be started with --pid argument."}

    try:
        # ============= CONNECTION =============
        if name == "bas_ping":
            result = await _client.ping()
            if result:
                return {"success": True, "message": "Connected to BAS", "data": result}
            return {"success": False, "error": "No response from BAS"}

        # ============= SCRIPT CONTROL =============
        elif name == "bas_play":
            return await _client.play()

        elif name == "bas_step_next":
            return await _client.step_next()

        elif name == "bas_pause":
            return await _client.pause()

        elif name == "bas_restart":
            return await _client.restart()

        elif name == "bas_get_status":
            return await _client.get_status()

        # ============= MODULE DISCOVERY =============
        elif name == "bas_list_modules":
            modules = await _client.list_modules()
            return {"modules": modules, "count": len(modules)}

        elif name == "bas_list_actions":
            module = args.get("module", "*")
            actions = await _client.list_actions(module)
            return {"actions": actions, "count": len(actions), "module": module}

        elif name == "bas_get_action_schema":
            action = args.get("action", "")
            schema = await _client.get_action_schema(action)
            return schema

        # ============= PROJECT OPERATIONS =============
        elif name == "bas_get_project":
            project = await _client.get_project()
            return {"actions": project, "count": len(project)}

        elif name == "bas_create_action":
            action = args.get("action", "")
            params = normalize_variable_params(args.get("params", {}))
            after_id = args.get("after_id", 0)
            parent_id = args.get("parent_id", 0)
            comment = args.get("comment", "")
            color = args.get("color", "green")
            execute = args.get("execute", False)
            include_html = args.get("include_html", True)
            return await _client.create_action(action, params, after_id, parent_id, comment, color, execute, include_html)

        elif name == "bas_update_action":
            action_id = args.get("action_id", 0)
            params = args.get("params")
            if params:
                params = normalize_variable_params(params)
            comment = args.get("comment")
            return await _client.update_action(action_id, params, comment)

        elif name == "bas_delete_actions":
            action_ids = args.get("action_ids", [])
            return await _client.delete_actions(action_ids)

        elif name == "bas_run_from":
            action_id = args.get("action_id", 0)
            return await _client.run_from(action_id)

        # ============= BROWSER =============
        elif name == "bas_get_html":
            # Use JavaScript-based method for reliable HTML retrieval
            return await _client.get_page_html_safe()

        elif name == "bas_get_url":
            return await _client.get_url()

        # ============= DEBUG / EXECUTION =============
        elif name == "bas_move_execution_point":
            action_id = args.get("action_id", 0)
            return await _client.move_to(action_id)

        elif name == "bas_get_variables":
            return await _client.get_variables()

        elif name == "bas_get_variable":
            name_arg = args.get("name", "")
            # Auto-add VAR_ prefix if not present
            if name_arg and not name_arg.startswith("VAR_"):
                name_arg = "VAR_" + name_arg
            no_truncate = args.get("no_truncate", True)  # Default to full value
            return await _client.get_variable(name_arg, no_truncate=no_truncate)

        elif name == "bas_get_resources":
            return await _client.get_resources()

        elif name == "bas_get_resource":
            name_arg = args.get("name", "")
            return await _client.get_resource(name_arg)

        elif name == "bas_eval":
            expression = args.get("expression", "")
            return await _client.eval_expr(expression)

        # ============= FUNCTION MANAGEMENT =============
        elif name == "bas_list_functions":
            return await _client.list_functions()

        elif name == "bas_create_function":
            func_name = args.get("name", "")
            after_function = args.get("after_function")
            return await _client.create_function(func_name, after_function)

        elif name == "bas_delete_function":
            func_name = args.get("name")
            func_id = args.get("function_id")
            if func_name == "OnApplicationStart":
                return {"success": False, "error": "Cannot delete OnApplicationStart function"}
            return await _client.delete_function(func_name, func_id)

        elif name == "bas_open_function":
            func_name = args.get("name")
            func_id = args.get("function_id")
            return await _client.open_function(func_name, func_id)

        elif name == "bas_get_function_actions":
            func_name = args.get("name")
            func_id = args.get("function_id")
            return await _client.get_function_actions(func_name, func_id)

        # ============= SCREENSHOT =============
        elif name == "bas_screenshot":
            selector = args.get("selector", ">CSS> html")
            return await _client.take_screenshot(selector)

        # ============= ELEMENT INFO =============
        elif name == "bas_check_element":
            selector = args.get("selector", "")
            if not selector:
                return {"error": "selector is required"}
            return await _client.check_element(selector)

        # ============= MODULE ANALYSIS =============
        elif name == "bas_find_modules":
            module_hint = args.get("module_hint")
            return await _client.find_module_actions(module_hint)

        elif name == "bas_analyze_module":
            action_id = args.get("action_id", 0)
            if not action_id:
                return {"error": "action_id is required"}
            return await _client.analyze_module_action(action_id)

        elif name == "bas_create_from_template":
            template_id = args.get("template_id", 0)
            values = args.get("values", {})
            after_id = args.get("after_id", 0)
            parent_id = args.get("parent_id", 0)
            comment = args.get("comment", "")
            if not template_id:
                return {"error": "template_id is required"}
            if not values:
                return {"error": "values dict is required"}
            return await _client.create_module_action_from_template(
                template_id, values, after_id, parent_id, comment
            )

        elif name == "bas_get_module_schema":
            module_name = args.get("module_name", "")
            action_id = args.get("action_id")
            if not module_name:
                return {"error": "module_name is required"}
            return await _client.get_module_schema(module_name, action_id)

        elif name == "bas_clone_module_action":
            template_id = args.get("template_id", 0)
            new_params = args.get("new_params", {})
            comment = args.get("comment", "")
            if not template_id:
                return {"error": "template_id is required"}
            if not new_params:
                return {"error": "new_params dict is required"}
            return await _client.clone_module_action(template_id, new_params, comment)

        # ============= ACTION HELP =============
        elif name == "bas_get_action_help":
            action = args.get("action", "")
            if not action:
                return {"error": "action is required"}

            if action == "*":
                # Return list of all documented actions grouped by category
                categories = {}
                for action_type, help_data in ACTION_HELP.items():
                    cat = help_data.get("category", "Other")
                    if cat not in categories:
                        categories[cat] = []
                    categories[cat].append({
                        "action": action_type,
                        "name": help_data.get("name", action_type),
                        "requires_path": help_data.get("requires_path", False)
                    })
                return {
                    "success": True,
                    "categories": categories,
                    "total_actions": len(ACTION_HELP)
                }

            # Get help for specific action
            if action in ACTION_HELP:
                help_data = ACTION_HELP[action].copy()
                help_data["action"] = action
                help_data["success"] = True
                return help_data
            else:
                # Action not in our database - suggest using bas_get_action_schema
                return {
                    "success": False,
                    "error": f"Action '{action}' not in help database",
                    "suggestion": "Try bas_get_action_schema for official BAS schema, or bas_get_action_help with action='*' to see all documented actions"
                }

        # ============= LOGS =============
        elif name == "bas_list_logs":
            limit = args.get("limit", 20)
            logs = list_log_files(limit=limit)
            logs_dir = find_logs_dir()
            return {
                "success": True,
                "logs_dir": str(logs_dir) if logs_dir else None,
                "logs": logs,
                "count": len(logs)
            }

        elif name == "bas_get_log":
            log_name = args.get("log_name")
            tail = args.get("tail", 0)
            return read_log_file(log_name=log_name, tail_lines=tail)

        else:
            return {"error": f"Unknown tool: {name}"}

    except Exception as e:
        return {"error": str(e)}


def call_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Synchronous wrapper for async tool calls."""
    global _event_loop
    if _event_loop is None:
        _event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_event_loop)
    return _event_loop.run_until_complete(call_tool_async(name, args))


def handle_request(request: Dict) -> Optional[Dict]:
    """Handle incoming MCP JSON-RPC request."""
    method = request.get("method", "")
    params = request.get("params", {})
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "bas-mcp",
                    "version": "3.0.0"
                }
            }
        }

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": get_tools_list()
            }
        }

    elif method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})

        result = call_tool(tool_name, tool_args)

        # Special handling for screenshot - return as image content
        if tool_name == "bas_screenshot" and result.get("success") and result.get("screenshot_base64"):
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": "Screenshot captured successfully:"
                        },
                        {
                            "type": "image",
                            "data": result["screenshot_base64"],
                            "mimeType": "image/png"
                        }
                    ]
                }
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, ensure_ascii=False, indent=2)
                    }
                ]
            }
        }

    elif method == "notifications/initialized":
        return None  # No response for notifications

    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}"
            }
        }


def main():
    """Main entry point - JSON-RPC over stdin/stdout."""
    global _client, _event_loop

    parser = argparse.ArgumentParser(description='BAS MCP Server for Claude CLI')
    parser.add_argument('--pid', type=int, required=True, help='BAS process ID')
    parser.add_argument('--ipc-dir', type=str, help='IPC directory path (optional)')
    args = parser.parse_args()

    # Create event loop
    _event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_event_loop)

    # Initialize BAS client with file-based IPC
    from pathlib import Path
    ipc_dir = Path(args.ipc_dir) if args.ipc_dir else None
    _client = BASClient(args.pid, ipc_dir)

    exe_dir = get_exe_directory()
    print(f"BAS MCP Server started", file=sys.stderr, flush=True)
    print(f"  EXE dir: {exe_dir}", file=sys.stderr, flush=True)
    print(f"  IPC dir: {_client.ipc_dir}", file=sys.stderr, flush=True)
    print(f"  BAS PID: {args.pid}", file=sys.stderr, flush=True)

    # Read JSON-RPC requests from stdin using readline() for lower latency
    # Note: "for line in sys.stdin" uses block buffering which causes delays!
    while True:
        try:
            line = sys.stdin.readline()
            if not line:  # EOF
                break
            line = line.strip()
            if not line:
                continue

            request = json.loads(line)
            response = handle_request(request)
            if response is not None:
                print(json.dumps(response, ensure_ascii=False), flush=True)
        except json.JSONDecodeError as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": f"Parse error: {e}"
                }
            }
            print(json.dumps(error_response, ensure_ascii=False), flush=True)
        except Exception as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32603,
                    "message": f"Internal error: {e}"
                }
            }
            print(json.dumps(error_response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
