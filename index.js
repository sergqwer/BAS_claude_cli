
class BASHelper {
    #cancel = null;

    constructor()
    {
        this.COLORS_MAP = {
            white: '',
            green: '1',
            brown: '2',
            lightblue: '3',
            darkblue: '4',
            red: '5',
        };

        // Actions that don't use underscore prefix
        this.NO_PREFIX_ACTIONS = new Set([
            'log', 'comment', 'success', 'fail', 'stop'
        ]);
    }

    HexToString(hexStr)
    {
        var hex = hexStr.toString();
        var bytes = [];
        for (var i = 0; i < hex.length; i += 2) {
            bytes.push(parseInt(hex.substr(i, 2), 16));
        }
        var utf8Str = new TextDecoder('utf-8').decode(new Uint8Array(bytes));
        return utf8Str;
    }

    StringToHex(str)
    {
        // Encode string as UTF-8 bytes, then convert to hex
        var encoder = new TextEncoder();  // Uses UTF-8 by default
        var bytes = encoder.encode(str);
        var hex = '';
        for (var i = 0; i < bytes.length; i++) {
            hex += bytes[i].toString(16).padStart(2, '0');
        }
        return hex;
    }

    SendMessage(Type, Id, Data)
    {
        // Encode as UTF-8 hex to preserve non-ASCII characters
        var json = JSON.stringify({type: Type, id: Id, data: Data});
        var hex = this.StringToHex(json);
        BrowserAutomationStudio_SendMessageToHelper(hex);
    }

    async OnMessageFromHelperHex(MessageHex)
    {
        let Message = this.HexToString(MessageHex)
        Message = JSON.parse(Message)

        // ============= SIMPLE CLAUDE PROTOCOL =============

        if(Message.type == "ping")
        {
            this.SendMessage("pong", Message.id, null)
        }
        // ============= SCRIPT CONTROL =============
        else if(Message.type == "play")
        {
            let result = this.Play();
            this.SendMessage("play-result", Message.id, result)
        }
        else if(Message.type == "step-next")
        {
            let result = this.StepNext();
            this.SendMessage("step-next-result", Message.id, result)
        }
        else if(Message.type == "pause")
        {
            let result = this.Pause();
            this.SendMessage("pause-result", Message.id, result)
        }
        else if(Message.type == "restart")
        {
            let result = this.Restart();
            this.SendMessage("restart-result", Message.id, result)
        }
        else if(Message.type == "stop")
        {
            let result = this.Stop();
            this.SendMessage("stop-result", Message.id, result)
        }
        else if(Message.type == "get-status")
        {
            let result = this.GetScriptStatus();
            this.SendMessage("get-status-result", Message.id, result)
        }
        // ============= MODULE & ACTION DISCOVERY =============
        else if(Message.type == "list-modules")
        {
            let modules = this.GetModulesList();
            this.SendMessage("list-modules-result", Message.id, modules)
        }
        else if(Message.type == "list-actions")
        {
            let moduleName = Message.data.module;
            let actions = this.GetModuleActions(moduleName);
            this.SendMessage("list-actions-result", Message.id, actions)
        }
        else if(Message.type == "get-action-schema")
        {
            try {
                let actionType = Message.data ? Message.data.action : null;
                if(!actionType) {
                    this.SendMessage("get-action-schema-result", Message.id, {error: "No action specified"});
                    return;
                }
                let schema = this.GetActionSchema(actionType);
                this.SendMessage("get-action-schema-result", Message.id, schema)
            } catch(e) {
                this.SendMessage("get-action-schema-result", Message.id, {error: e.toString(), stack: e.stack})
            }
        }
        // ============= PROJECT OPERATIONS =============
        else if(Message.type == "get-project")
        {
            let project = this.GetProjectActions();
            this.SendMessage("get-project-result", Message.id, project)
        }
        else if(Message.type == "get-task-raw")
        {
            // Get raw task data including code field
            let taskId = Message.data.action_id;
            let result = null;
            _TaskCollection.forEach((Task) => {
                if(parseInt(Task.get('id')) == taskId) {
                    result = {
                        id: Task.get('id'),
                        name: Task.get('name'),
                        code: Task.get('code'),
                        dat_precomputed: Task.get('dat_precomputed'),
                        parentid: Task.get('parentid'),
                        color: Task.get('color')
                    };
                }
            });
            this.SendMessage("get-task-raw-result", Message.id, result || {error: "Task not found"})
        }
        else if(Message.type == "create-action")
        {
            let result = await this.CreateActionSimple(
                Message.data.action,
                Message.data.params || {},
                Message.data.after_id || 0,
                Message.data.parent_id || 0,
                Message.data.comment || "",
                Message.data.color || "green",
                Message.data.execute || false,
                Message.data.include_html !== false  // default true
            );
            this.SendMessage("create-action-result", Message.id, result)
        }
        else if(Message.type == "update-action")
        {
            let result = await this.UpdateActionSimple(
                Message.data.action_id,
                Message.data.params || {},
                Message.data.comment
            );
            this.SendMessage("update-action-result", Message.id, result)
        }
        else if(Message.type == "delete-actions")
        {
            let result = await this.DeleteActions(Message.data.action_ids);
            this.SendMessage("delete-actions-result", Message.id, result)
        }
        else if(Message.type == "run-from")
        {
            let result = this.RunFromAction(Message.data.action_id);
            this.SendMessage("run-from-result", Message.id, result)
        }
        // ============= FUNCTION MANAGEMENT =============
        else if(Message.type == "create-function")
        {
            let result = await this.CreateFunction(
                Message.data.name,
                Message.data.after_id || 0
            );
            this.SendMessage("create-function-result", Message.id, result)
        }
        else if(Message.type == "list-functions")
        {
            let result = this.ListFunctions();
            this.SendMessage("list-functions-result", Message.id, result)
        }
        else if(Message.type == "open-function")
        {
            let result = this.OpenFunction(Message.data.name || Message.data.function_id);
            this.SendMessage("open-function-result", Message.id, result)
        }
        // ============= BROWSER INTERACTION =============
        else if(Message.type == "get-html")
        {
            let result = await this.GetBrowserHtml();
            this.SendMessage("get-html-result", Message.id, result)
        }
        else if(Message.type == "get-url")
        {
            let result = this.GetBrowserUrl();
            this.SendMessage("get-url-result", Message.id, result)
        }
        // ============= DEBUG / VARIABLES / RESOURCES =============
        else if(Message.type == "move-execution-point")
        {
            let result = this.MoveExecutionPoint(Message.data.action_id);
            this.SendMessage("move-execution-point-result", Message.id, result)
        }
        else if(Message.type == "get-variables")
        {
            let result = this.GetVariablesList();
            this.SendMessage("get-variables-result", Message.id, result)
        }
        else if(Message.type == "get-variable")
        {
            let result = await this.GetVariableValue(Message.data.name, Message.data.no_truncate);
            this.SendMessage("get-variable-result", Message.id, result)
        }
        else if(Message.type == "get-resources")
        {
            let result = this.GetResourcesList();
            this.SendMessage("get-resources-result", Message.id, result)
        }
        else if(Message.type == "get-resource")
        {
            let result = await this.GetResourceValue(Message.data.name);
            this.SendMessage("get-resource-result", Message.id, result)
        }
        else if(Message.type == "eval")
        {
            let result = await this.EvalExpression(Message.data.expression);
            this.SendMessage("eval-result", Message.id, result)
        }
        else if(Message.type == "cancel")
        {
            if(this.#cancel != null)
            {
                this.#cancel();
                this.#cancel = null;
            }
        }
        // Legacy support
        else if(Message.type == "add-actions-group" || Message.type == "add-actions-group-auto")
        {
            await this.HandleLegacyAddActions(Message);
        }
    }

    // ============= SCRIPT CONTROL COMMANDS =============

    Play()
    {
        try {
            if(_GobalModel.get("isscriptexecuting")) {
                return {success: false, error: "Script is already running"};
            }

            // Try clicking the actual play button
            let playBtn = document.getElementById('play');
            if(playBtn) {
                playBtn.click();
                return {success: true, action: "play", method: "button_click"};
            }

            // Fallback to _MainView.play with proper event
            if(typeof _MainView !== 'undefined' && typeof _MainView.play === 'function') {
                let fakeEvent = {preventDefault: function(){}, stopPropagation: function(){}, target: document.getElementById('play')};
                _MainView.play(fakeEvent);
                return {success: true, action: "play", method: "_MainView.play"};
            }

            return {success: false, error: "Play function not available"};
        } catch(e) {
            return {success: false, error: e.toString()};
        }
    }

    StepNext()
    {
        try {
            // Try clicking the actual stepnext button
            let stepBtn = document.getElementById('stepnext');
            if(stepBtn) {
                stepBtn.click();
                return {success: true, action: "step-next", method: "button_click"};
            }

            // Fallback to _MainView.stepnext with proper event
            if(typeof _MainView !== 'undefined' && typeof _MainView.stepnext === 'function') {
                let fakeEvent = {preventDefault: function(){}, stopPropagation: function(){}, target: document.getElementById('stepnext')};
                _MainView.stepnext(fakeEvent);
                return {success: true, action: "step-next", method: "_MainView.stepnext"};
            }

            return {success: false, error: "StepNext function not available"};
        } catch(e) {
            return {success: false, error: e.toString()};
        }
    }

    Pause()
    {
        try {
            if(typeof _GobalModel !== 'undefined') {
                _GobalModel.set("isexecutionaborting", true);
                _GobalModel.set("isscriptexecuting", false);
                return {success: true, action: "pause"};
            }
            return {success: false, error: "Pause not available"};
        } catch(e) {
            return {success: false, error: e.toString()};
        }
    }

    Restart()
    {
        try {
            if(typeof BrowserAutomationStudio_Restart === 'function') {
                BrowserAutomationStudio_Restart(false);
                return {success: true, action: "restart"};
            }
            return {success: false, error: "Restart function not available"};
        } catch(e) {
            return {success: false, error: e.toString()};
        }
    }

    Stop()
    {
        try {
            if(typeof BrowserAutomationStudio_Restart === 'function') {
                BrowserAutomationStudio_Restart(true);
                return {success: true, action: "stop"};
            }
            return {success: false, error: "Stop function not available"};
        } catch(e) {
            return {success: false, error: e.toString()};
        }
    }

    GetScriptStatus()
    {
        try {
            if(typeof _GobalModel !== 'undefined') {
                return {
                    success: true,
                    is_executing: _GobalModel.get("isscriptexecuting") || false,
                    is_task_executing: _GobalModel.get("istaskexecuting") || false,
                    is_aborting: _GobalModel.get("isexecutionaborting") || false,
                    current_action_id: _GobalModel.get("execute_next_id") || 0,
                    is_step_mode: _GobalModel.get("isstepnextactivated") || false
                };
            }
            return {success: false, error: "Status not available"};
        } catch(e) {
            return {success: false, error: e.toString()};
        }
    }

    // ============= DYNAMIC MODULE DISCOVERY =============

    GetModulesList()
    {
        // Parse modules from global _G object
        let modules = [];

        if(typeof _G !== 'undefined') {
            for(let [id, info] of Object.entries(_G)) {
                modules.push({
                    id: id,
                    name: this.CapitalizeFirst(id),
                    description: info.info || '',
                    icon: info.icon || ''
                });
            }
        }

        // Also collect unique groups from actions
        if(typeof _A !== 'undefined') {
            let groups = new Set(modules.map(m => m.id));
            for(let action of Object.values(_A)) {
                let group = action.group || action.class;
                if(group && !groups.has(group)) {
                    groups.add(group);
                    modules.push({
                        id: group,
                        name: this.CapitalizeFirst(group),
                        description: '',
                        icon: ''
                    });
                }
            }
        }

        return modules;
    }

    GetModuleActions(moduleName)
    {
        // Parse actions from global _A object
        let actions = [];

        if(typeof _A === 'undefined') {
            return [{error: "_A actions object not available"}];
        }

        for(let [code, action] of Object.entries(_A)) {
            let actionGroup = (action.group || action.class || '').toLowerCase();

            // Match module or return all if '*'
            if(moduleName === '*' || actionGroup === moduleName.toLowerCase()) {
                actions.push({
                    id: code,
                    name: action.name || code,
                    module: action.group || action.class || 'other',
                    description: action.description || '',
                    has_children: this.ActionHasChildren(code)
                });
            }
        }

        return actions;
    }

    GetActionSchema(actionCode)
    {
        // Parse action schema from global _A object
        if(typeof _A === 'undefined') {
            return {error: "_A actions object not available"};
        }

        let action = _A[actionCode];
        if(!action) {
            return {error: `Action '${actionCode}' not found`};
        }

        // Parse parameters from template
        let template = action.template || '';
        let params = this.ParseTemplateParams(template);

        return {
            id: actionCode,
            name: action.name || actionCode,
            module: action.group || action.class || 'other',
            description: action.description || '',
            params: params,
            has_children: this.ActionHasChildren(actionCode),
            suggestion: action.suggestion || {}
        };
    }

    ParseTemplateParams(template)
    {
        // Template is pre-processed by BAS: <prop name="X"/> becomes {{X}}
        let params = [];

        if(!template) return params;

        // Match {{paramName}} placeholders (including dashes like use-waiter)
        let placeholderRegex = /\{\{([\w-]+)\}\}/g;
        let match;

        while((match = placeholderRegex.exec(template)) !== null) {
            let paramId = match[1];
            params.push({
                id: paramId,
                name: this.FormatParamName(paramId),
                type: 'string',
                description: this.GetParamDescription(paramId)
            });
        }

        return params;
    }

    FormatParamName(paramId)
    {
        // Convert camelCase/PascalCase to readable name
        // LoadUrl -> Load URL, use-waiter -> Wait page
        let name = paramId
            .replace(/([a-z])([A-Z])/g, '$1 $2')
            .replace(/-/g, ' ')
            .replace(/^./, s => s.toUpperCase());
        return name;
    }

    GetParamDescription(paramId)
    {
        // Try to get description from _AL translations
        if(typeof _AL !== 'undefined') {
            let desc = _AL[paramId];
            if(desc) {
                return typeof desc === 'object' ? (desc.en || desc.ru || '') : desc;
            }
        }
        return '';
    }

    ParsePropAttributes(attrString)
    {
        // Parse attributes from prop tag
        let param = {
            id: '',
            name: '',
            type: 'string',
            label: '',
            description: '',
            priority: 0,
            hide_if_default: false,
            is_variable: false
        };

        // Parse name="value" pairs
        let attrRegex = /(\w+)\s*=\s*"([^"]*)"/gi;
        let match;

        while((match = attrRegex.exec(attrString)) !== null) {
            let attrName = match[1].toLowerCase();
            let attrValue = match[2];

            switch(attrName) {
                case 'name':
                    param.id = attrValue;
                    param.name = attrValue;
                    break;
                case 'label':
                    param.label = this.TranslateLabel(attrValue);
                    break;
                case 'priority':
                    param.priority = parseInt(attrValue) || 0;
                    break;
                case 'hide_if_default':
                    param.hide_if_default = attrValue === 'true';
                    break;
                case 'is_variable':
                    param.is_variable = attrValue === 'true';
                    param.type = 'variable';
                    break;
                case 'show_label':
                    param.show_label = attrValue;
                    break;
            }
        }

        // Use label as display name if available
        if(param.label) {
            param.name = param.label;
        }

        // Try to get description from _AL translations
        if(typeof _AL !== 'undefined' && param.id) {
            let desc = _AL[param.id] || _AL[param.label];
            if(desc) {
                param.description = typeof desc === 'object' ? (desc.en || desc.ru || '') : desc;
            }
        }

        return param;
    }

    TranslateLabel(label)
    {
        // Translate special labels like "-LABEL-Delay"
        if(label.startsWith('-LABEL-')) {
            let key = label.substring(7);
            if(typeof _AL !== 'undefined' && _AL[label]) {
                return _AL[label].en || _AL[label].ru || key;
            }
            return key;
        }
        return label;
    }

    ActionHasChildren(actionCode)
    {
        // Actions that contain child actions
        let containerActions = new Set([
            'if', 'else', 'while', 'foreach', 'for', 'function',
            'trycatch', 'try', 'catch', 'thread', 'element_loop'
        ]);
        return containerActions.has(actionCode.toLowerCase());
    }

    CapitalizeFirst(str)
    {
        return str.charAt(0).toUpperCase() + str.slice(1);
    }

    // ============= PROJECT ACTIONS (HUMAN-READABLE) =============

    GetProjectActions()
    {
        let actions = [];
        _TaskCollection.forEach((Task, Index) => {
            let actionInfo = this.ParseTaskToReadable(Task, Index);
            actions.push(actionInfo);
        });
        return actions;
    }

    ParseTaskToReadable(Task, Index)
    {
        let code = Task.get('code') || '';
        let actionType = this.ExtractActionType(code);
        let params = this.ExtractActionParams(Task);

        return {
            id: parseInt(Task.get('id')),
            index: Index,
            type: actionType,
            comment: Task.get('name') || '',
            params: params,
            parent_id: parseInt(Task.get('parentid')) || 0,
            color: this.ColorCodeToName(Task.get('color'))
        };
    }

    ExtractActionType(code)
    {
        // Extract action type from code like "_load(...)" or "log(...)"
        let match = code.match(/^\s*_?(\w+)\s*\(/m);
        if(match) return match[1];

        // Try patterns in code
        if(code.includes('if(')) return 'if';
        if(code.includes('else')) return 'else';
        if(code.includes('while(')) return 'while';
        if(code.includes('foreach(')) return 'foreach';

        return 'unknown';
    }

    ExtractActionParams(Task)
    {
        let params = {};

        let datPrecomputed = Task.get('dat_precomputed');
        if(datPrecomputed && datPrecomputed.d) {
            datPrecomputed.d.forEach(param => {
                if(param.id && param.data !== undefined) {
                    params[param.id] = param.data;
                }
            });
            return params;
        }

        let dat = Task.get('dat');
        if(dat && typeof dat === 'object' && dat.d) {
            dat.d.forEach(param => {
                if(param.id && param.data !== undefined) {
                    params[param.id] = param.data;
                }
            });
        }

        return params;
    }

    ColorCodeToName(colorCode)
    {
        let reverseMap = {
            '': 'white',
            '1': 'green',
            '2': 'brown',
            '3': 'lightblue',
            '4': 'darkblue',
            '5': 'red'
        };
        return reverseMap[colorCode] || 'white';
    }

    // ============= FUNCTION MANAGEMENT =============

    ListFunctions()
    {
        let functions = [];
        _TaskCollection.forEach((Task, Index) => {
            let code = Task.get('code') || '';
            // Functions are marked by section_insert() in their code
            if(code.includes('section_insert()')) {
                let funcId = parseInt(Task.get('id'));
                let funcName = Task.get('name') || '';

                // Count actions inside this function
                let actionsCount = 0;
                _TaskCollection.forEach((T) => {
                    if(parseInt(T.get('parentid')) === funcId) {
                        actionsCount++;
                    }
                });

                functions.push({
                    id: funcId,
                    name: funcName,
                    actions_count: actionsCount,
                    index: Index
                });
            }
        });

        return {
            success: true,
            functions: functions,
            count: functions.length
        };
    }

    async CreateFunction(name, afterId = 0)
    {
        try {
            if(!name || name.trim() === '') {
                return {success: false, error: "Function name cannot be empty"};
            }

            // Check if function with this name already exists
            let existing = this.ListFunctions();
            if(existing.functions.some(f => f.name === name)) {
                return {success: false, error: `Function '${name}' already exists`};
            }

            // Set insertion point
            if(afterId > 0) {
                let afterIndex = -1;
                _TaskCollection.every((Task, Index) => {
                    if(parseInt(Task.get('id')) == afterId) {
                        afterIndex = Index;
                        return false;
                    }
                    return true;
                });
                if(afterIndex >= 0) {
                    _MainView.model.attributes["insert_index"] = afterIndex + 1;
                    _MainView.model.attributes["insert_parent"] = 0; // Functions are always at root level
                }
            } else {
                _MainView.model.attributes["insert_index"] = _TaskCollection.length;
                _MainView.model.attributes["insert_parent"] = 0;
            }
            _MainView.UpdateInsertDataInterface();

            // Generate unique ID
            let newId = Math.floor(Math.random() * 900000000) + 100000000;

            // Create the function (section) task object
            // The code is simply "section_insert()" which marks it as a function
            let functionObj = {
                name: name,
                code: "section_insert()",
                internal_label_id: "",
                dat_precomputed: null,
                code_precomputed: null,
                color: "",
                id: newId,
                parentid: 0,
                is_fold: 0
            };

            window.App.overlay.show();

            let Ids = _MainView.PasteFinal(JSON.stringify([functionObj]), true);

            window.App.overlay.hide();

            if(!Ids || Ids.length === 0) {
                return {success: false, error: "Failed to create function - PasteFinal returned empty"};
            }

            // Navigate to the new function
            _GobalModel.set("function_name", name);

            return {
                success: true,
                function_id: Ids[0],
                name: name
            };

        } catch(e) {
            window.App.overlay.hide();
            return {success: false, error: e.toString()};
        }
    }

    OpenFunction(nameOrId)
    {
        try {
            let targetName = null;
            let targetId = null;

            // Find the function
            _TaskCollection.every((Task, Index) => {
                let code = Task.get('code') || '';
                if(code.includes('section_insert()')) {
                    let funcName = Task.get('name') || '';
                    let funcId = parseInt(Task.get('id'));

                    // Match by name or id
                    if(funcName === nameOrId || funcId === nameOrId) {
                        targetName = funcName;
                        targetId = funcId;
                        return false;
                    }
                }
                return true;
            });

            if(!targetName) {
                return {success: false, error: `Function '${nameOrId}' not found`};
            }

            // Set the current function name in the global model
            // This will switch the view to show this function
            _GobalModel.set("function_name", targetName);

            return {
                success: true,
                function: {
                    id: targetId,
                    name: targetName
                }
            };

        } catch(e) {
            return {success: false, error: e.toString()};
        }
    }

    // ============= CREATE ACTION (SIMPLE) =============

    async CreateActionSimple(actionType, params, afterId, parentId, comment, color, execute = false, includeHtml = true)
    {
        try {
            // Get action info from _A
            if(typeof _A === 'undefined' || !_A[actionType]) {
                return {success: false, error: `Action type '${actionType}' not found in BAS`};
            }

            let actionInfo = _A[actionType];
            let templateParams = this.ParseTemplateParams(actionInfo.template || '');

            // Set insertion point
            if(afterId > 0) {
                let afterIndex = -1;
                _TaskCollection.every((Task, Index) => {
                    if(parseInt(Task.get('id')) == afterId) {
                        afterIndex = Index;
                        if(parentId === 0) {
                            parentId = parseInt(Task.get('parentid')) || 0;
                        }
                        return false;
                    }
                    return true;
                });
                if(afterIndex >= 0) {
                    _MainView.model.attributes["insert_index"] = afterIndex + 1;
                    _MainView.model.attributes["insert_parent"] = parentId;
                }
            } else {
                _MainView.model.attributes["insert_index"] = _TaskCollection.length;
                _MainView.model.attributes["insert_parent"] = parentId;
            }
            _MainView.UpdateInsertDataInterface();

            // Build dat object with parameters
            let datParams = [];
            templateParams.forEach(item => {
                let value = params[item.id] !== undefined ? params[item.id] : '';
                datParams.push({
                    id: item.id,
                    type: "constr",
                    data: String(value),
                    class: "string",
                    is_def: params[item.id] === undefined || value === ''
                });
            });

            // Also add any extra params not in template
            for(let [key, value] of Object.entries(params)) {
                if(!templateParams.find(p => p.id === key)) {
                    datParams.push({
                        id: key,
                        type: "constr",
                        data: String(value),
                        class: "string",
                        is_def: false
                    });
                }
            }

            let dat = {
                s: actionType,
                v: 1,
                f: [],
                uw: "0",
                ut: "0",
                uto: "0",
                um: "0",
                ue: "0",
                usp: "0",
                d: datParams
            };

            // Handle PATH parameter (element selector) - it goes in a separate 'p' object
            if(params.PATH) {
                let pathValue = params.PATH;
                let selectorType = 'css'; // default

                // Determine selector type from PATH format
                if(pathValue.includes('>MATCH>')) {
                    selectorType = 'match';
                } else if(pathValue.includes('>XPATH>')) {
                    selectorType = 'xpath';
                } else if(pathValue.includes('>CSS>')) {
                    selectorType = 'css';
                }

                dat.p = {
                    is_image: false,
                    css: selectorType === 'css' ? pathValue : '',
                    version: '1.0',
                    css1: '',
                    css2: '',
                    css3: '',
                    current: selectorType,
                    match: selectorType === 'match' ? pathValue : '',
                    xpath: selectorType === 'xpath' ? pathValue : '',
                    at: '',
                    we: true,  // wait element
                    fa: true   // fail action
                };
            }

            // Create action object
            let colorCode = this.COLORS_MAP[color] || '';
            let datJson = JSON.stringify(dat);
            let datBase64 = btoa(unescape(encodeURIComponent(datJson)));

            // Determine if action uses underscore prefix
            let usePrefix = !this.NO_PREFIX_ACTIONS.has(actionType);
            let code = `/*Dat:${datBase64}*/\n${usePrefix ? '_' : ''}${actionType}()!`;

            // Generate unique ID
            let newId = Math.floor(Math.random() * 900000000) + 100000000;

            let actionObj = {
                name: comment,
                code: code,
                internal_label_id: "",
                dat_precomputed: null,
                code_precomputed: null,
                color: colorCode,
                id: newId,
                parentid: parentId,
                is_fold: 0
            };

            window.App.overlay.show();

            let Ids = _MainView.PasteFinal(JSON.stringify([actionObj]), true);

            if(!Ids || Ids.length === 0) {
                window.App.overlay.hide();
                return {success: false, error: "PasteFinal returned empty"};
            }

            // Compile the action
            let insertedTask = FindTaskById(Ids[0]);
            await new Promise(resolve => {
                _ActionUpdater.model.once('finish', resolve).set({
                    tasks: App.utils.filterTasks('all', [insertedTask]),
                    isStarted: true,
                });
            });

            window.App.overlay.hide();

            if(!_ActionUpdater.model.isSuccessfulUpdate()) {
                let errorInfo = _ActionUpdater.model.get('error') || 'compile error';
                await this.DeleteActions(Ids);
                return {success: false, error: `Compile failed: ${errorInfo}`, ids: Ids};
            }

            // If execute requested, run the action and wait for completion
            if(execute) {
                let execResult = await this.ExecuteActionAndWait(Ids[0], includeHtml);
                return {
                    success: true,
                    action_id: Ids[0],
                    ids_count: Ids.length,
                    executed: true,
                    execution_result: execResult.result,
                    execution_error: execResult.error,
                    html: execResult.html,
                    url: execResult.url
                };
            }

            return {success: true, action_id: Ids[0], ids_count: Ids.length};

        } catch(e) {
            window.App.overlay.hide();
            return {success: false, error: e.toString()};
        }
    }

    // ============= EXECUTE ACTION AND WAIT =============

    async ExecuteActionAndWait(actionId, includeHtml = true, timeout = 60000)
    {
        try {
            // Wait for any previous execution to finish (check both flags)
            let waitStart = Date.now();
            while(Date.now() - waitStart < 5000) {
                let preStatus = this.GetScriptStatus();
                if(!preStatus.is_executing && !preStatus.is_task_executing) {
                    break;
                }
                await new Promise(r => setTimeout(r, 100));
            }

            // Move execution point to the action
            let moveResult = this.MoveExecutionPoint(actionId);
            if(!moveResult.success) {
                return {result: 'failed', error: moveResult.error};
            }

            // Small delay to let move complete
            await new Promise(r => setTimeout(r, 200));

            // Execute the action (step next)
            let stepResult = this.StepNext();
            if(!stepResult.success) {
                return {result: 'failed', error: stepResult.error};
            }

            let startTime = Date.now();
            let initialActionId = this.GetScriptStatus().current_action_id;

            // Wait for execution to start (current_action_id changes or is_executing becomes true)
            let executionStarted = false;
            while(Date.now() - startTime < 5000) {
                await new Promise(r => setTimeout(r, 100));
                let status = this.GetScriptStatus();

                if(status.is_executing) {
                    executionStarted = true;
                    break;
                }

                // Also consider started if we moved past the action
                if(status.current_action_id !== initialActionId && status.current_action_id !== 0) {
                    executionStarted = true;
                    break;
                }
            }

            // Wait for execution to complete (check BOTH flags - is_executing AND is_task_executing)
            let executionCompleted = false;

            while(Date.now() - startTime < timeout) {
                await new Promise(r => setTimeout(r, 100));

                let status = this.GetScriptStatus();

                // Check if execution finished - BOTH flags must be false (same as pre-execution check)
                if(!status.is_executing && !status.is_task_executing) {
                    executionCompleted = true;
                    break;
                }
            }

            if(!executionCompleted) {
                return {result: 'timeout', error: `Execution timeout after ${timeout}ms`};
            }

            // Execution completed - short delay for stability
            await new Promise(r => setTimeout(r, 300));

            let result = {result: 'completed'};

            // Get HTML if requested - fast retry with fewer attempts
            if(includeHtml) {
                let maxRetries = 2;
                for(let retry = 0; retry < maxRetries; retry++) {
                    let htmlResult = await this.GetBrowserHtml();
                    if(htmlResult.success) {
                        result.html = htmlResult.html;
                        break;
                    }
                    // Short wait and retry
                    await new Promise(r => setTimeout(r, 200));
                }

                let urlResult = await this.GetBrowserUrl();
                if(urlResult.success) {
                    result.url = urlResult.url;
                }

                if(!result.html) {
                    result.html_error = 'Could not get HTML after multiple attempts';
                }
            }

            return result;

        } catch(e) {
            return {result: 'error', error: e.toString()};
        }
    }

    // ============= UPDATE ACTION =============

    async UpdateActionSimple(actionId, params, comment)
    {
        let task = FindTaskById(actionId);
        if(!task) {
            return {success: false, error: 'Action not found'};
        }

        try {
            await BrowserAutomationStudio_LockRender(async () => {
                if(comment !== undefined) {
                    task.set('name', comment);
                }

                if(Object.keys(params).length > 0) {
                    let dat = task.get('dat') || task.get('dat_precomputed');
                    if(dat && dat.d) {
                        dat.d.forEach(param => {
                            if(params[param.id] !== undefined) {
                                param.data = String(params[param.id]);
                                param.is_def = false;
                            }
                        });
                        task.attributes["dat_precomputed"] = dat;
                        task.attributes["code_precomputed"] = null;
                    }
                }
            }, false);

            await new Promise(resolve => {
                _ActionUpdater.model.once('finish', resolve).set({
                    tasks: [task],
                    isStarted: true,
                });
            });

            return {success: true, action_id: actionId};
        } catch(e) {
            return {success: false, error: e.toString()};
        }
    }

    // ============= DELETE ACTIONS =============

    async DeleteActions(actionIds)
    {
        try {
            await BrowserAutomationStudio_LockRender(async () => {
                actionIds.forEach(Id => {
                    _TaskCollection.every((Task, Index) => {
                        if(parseInt(Task.get('id')) != Id) return true;
                        _MainView.currentTargetId = Index;
                        _MainView.Delete();
                        return false;
                    });
                });
            }, false);
            return {success: true, deleted: actionIds};
        } catch(e) {
            return {success: false, error: e.toString()};
        }
    }

    // ============= RUN FROM ACTION =============

    RunFromAction(actionId)
    {
        let startIndex = -1;
        _TaskCollection.every((Task, Index) => {
            if(parseInt(Task.get('id')) == actionId) {
                startIndex = Index;
                return false;
            }
            return true;
        });

        if(startIndex < 0) {
            return {success: false, error: 'Action not found'};
        }

        try {
            _MainView.currentTargetId = startIndex;
            if(typeof BrowserAutomationStudio_RunAction === 'function') {
                BrowserAutomationStudio_RunAction();
            }
            return {success: true, started_from: actionId};
        } catch(e) {
            return {success: false, error: e.toString()};
        }
    }

    // ============= BROWSER INTERACTION =============

    async GetBrowserHtml()
    {
        try {
            // Method 1: Use ScriptWorker (available during/after script execution)
            if(typeof ScriptWorker !== 'undefined' && ScriptWorker.Browser) {
                try {
                    let html = await ScriptWorker.Browser.Evaluate('document.documentElement.outerHTML');
                    if(html) return {success: true, html: html};
                } catch(e) {}
            }

            // Method 2: Use _Worker.browser (available during script execution)
            if(typeof _Worker !== 'undefined' && _Worker.browser) {
                try {
                    let html = await _Worker.browser.evaluate('document.documentElement.outerHTML');
                    if(html) return {success: true, html: html};
                } catch(e) {}
            }

            // Method 3: Use BrowserAutomationStudio_QuerySelector
            if(typeof BrowserAutomationStudio_QuerySelector === 'function') {
                try {
                    let html = await new Promise((resolve, reject) => {
                        let timeout = setTimeout(() => reject('Timeout'), 3000);
                        BrowserAutomationStudio_QuerySelector(
                            "document.documentElement.outerHTML",
                            (result) => { clearTimeout(timeout); resolve(result); },
                            (error) => { clearTimeout(timeout); reject(error); }
                        );
                    });
                    if(html) return {success: true, html: html};
                } catch(e) {}
            }

            // Method 4: Use BrowserAutomationStudio_ExecuteSyncCode
            if(typeof BrowserAutomationStudio_ExecuteSyncCode === 'function') {
                try {
                    let code = `_execute_sync_result("-BAS-EXECUTESYNC-ID-", {"html": document.documentElement.outerHTML})`;
                    let response = await BrowserAutomationStudio_ExecuteSyncCode(code, 3000);
                    if(!response.was_timeout) {
                        let parsed = JSON.parse(response.result);
                        if(parsed.html) return {success: true, html: parsed.html};
                    }
                } catch(e) {}
            }

            // Method 5: Use BrowserAutomationStudio_Eval
            if(typeof BrowserAutomationStudio_Eval === 'function') {
                try {
                    let html = await new Promise((resolve, reject) => {
                        let timeout = setTimeout(() => reject('Timeout'), 3000);
                        BrowserAutomationStudio_Eval(
                            'document.documentElement.outerHTML',
                            (result) => { clearTimeout(timeout); resolve(result); }
                        );
                    });
                    if(html) return {success: true, html: html};
                } catch(e) {}
            }

            // Method 6: Use App.Inspector.utils.executeExpression (works in browser context)
            if(typeof App !== 'undefined' && App.Inspector && App.Inspector.utils && App.Inspector.utils.executeExpression) {
                try {
                    let result = await App.Inspector.utils.executeExpression('document.documentElement.outerHTML', {noTruncate: true});
                    if(!result.error && result.result) {
                        return {success: true, html: result.result};
                    }
                } catch(e) {}
            }

            // Method 7: Direct BrowserAutomationStudio_Execute with callback
            if(typeof BrowserAutomationStudio_Execute === 'function') {
                try {
                    let html = await new Promise((resolve, reject) => {
                        let timeout = setTimeout(() => resolve(null), 3000);
                        // Try to execute in browser and store in a temp variable
                        BrowserAutomationStudio_Execute(
                            'var __temp_html = document.documentElement.outerHTML; __temp_html;',
                            false,
                            (result) => { clearTimeout(timeout); resolve(result); }
                        );
                    });
                    if(html) return {success: true, html: html};
                } catch(e) {}
            }

            return {success: false, error: 'Browser not available. Make sure browser is open and page is loaded.'};
        } catch(e) {
            return {success: false, error: e.toString()};
        }
    }

    async GetBrowserUrl()
    {
        try {
            // Method 1: ScriptWorker
            if(typeof ScriptWorker !== 'undefined' && ScriptWorker.Browser) {
                try {
                    let url = ScriptWorker.Browser.GetUrl();
                    if(url) return {success: true, url: url};
                } catch(e) {}
            }

            // Method 2: _Worker.browser
            if(typeof _Worker !== 'undefined' && _Worker.browser) {
                try {
                    let url = _Worker.browser.getUrl();
                    if(url) return {success: true, url: url};
                } catch(e) {}
            }

            // Method 3: BrowserAutomationStudio_ExecuteSyncCode
            if(typeof BrowserAutomationStudio_ExecuteSyncCode === 'function') {
                try {
                    let code = `_execute_sync_result("-BAS-EXECUTESYNC-ID-", {"url": window.location.href})`;
                    let response = await BrowserAutomationStudio_ExecuteSyncCode(code, 5000);
                    if(!response.was_timeout) {
                        let parsed = JSON.parse(response.result);
                        if(parsed.url) return {success: true, url: parsed.url};
                    }
                } catch(e) {}
            }

            // Method 4: BrowserAutomationStudio_Eval
            if(typeof BrowserAutomationStudio_Eval === 'function') {
                try {
                    let url = await new Promise((resolve, reject) => {
                        let timeout = setTimeout(() => reject('Timeout'), 5000);
                        BrowserAutomationStudio_Eval(
                            'window.location.href',
                            (result) => { clearTimeout(timeout); resolve(result); }
                        );
                    });
                    if(url) return {success: true, url: url};
                } catch(e) {}
            }

            // Method 5: App.Inspector.utils.executeExpression
            if(typeof App !== 'undefined' && App.Inspector && App.Inspector.utils && App.Inspector.utils.executeExpression) {
                try {
                    let result = await App.Inspector.utils.executeExpression('window.location.href', {});
                    if(!result.error && result.result) {
                        return {success: true, url: result.result};
                    }
                } catch(e) {}
            }

            return {success: false, error: 'Browser not available'};
        } catch(e) {
            return {success: false, error: e.toString()};
        }
    }

    // ============= DEBUG / EXECUTION POINT =============

    MoveExecutionPoint(actionId)
    {
        try {
            if(_GobalModel.get("isscriptexecuting") || _GobalModel.get("istaskexecuting")) {
                return {success: false, error: "Cannot move execution point while script is running"};
            }

            // Find task by ID
            let targetIndex = -1;
            let targetTask = null;
            _TaskCollection.every((Task, Index) => {
                if(parseInt(Task.get('id')) == actionId) {
                    targetIndex = Index;
                    targetTask = Task;
                    return false;
                }
                return true;
            });

            if(!targetTask) {
                return {success: false, error: `Action ${actionId} not found`};
            }

            // Generate code for moving execution point
            let currentId = _GobalModel.get("execute_next_id");
            let execute_point_code = GenerateCodeForMovingExecutionPoint(currentId, actionId);

            // Notify system about move
            _WebInterfaceTasks.MovedExecutionPoint(currentId, actionId);

            // Execute the move
            let second_line = `debug_callstack()!\nsection_start("test", ${actionId})!`;
            let code = execute_point_code + "\n" + second_line;
            BrowserAutomationStudio_Execute(code, false);

            return {success: true, moved_to: actionId, from: currentId};
        } catch(e) {
            return {success: false, error: e.toString()};
        }
    }

    // ============= VARIABLES =============

    GetVariablesList()
    {
        try {
            let variables = [];

            // Method 1: Use BrowserAutomationStudio_GetVariablesList if available
            if(typeof BrowserAutomationStudio_GetVariablesList === 'function') {
                variables = BrowserAutomationStudio_GetVariablesList();
            }
            // Method 2: Parse from _CodeContainer
            else if(typeof _CodeContainer !== 'undefined' && _CodeContainer.GetVariablesInfo) {
                let varInfo = JSON.parse(_CodeContainer.GetVariablesInfo());
                variables = varInfo.map(v => "VAR_" + v.name);
            }

            // Also get global variables
            let globalVars = [];
            if(typeof _CodeContainer !== 'undefined' && _CodeContainer.GetGlobalVariablesInfo) {
                try {
                    let globalInfo = JSON.parse(_CodeContainer.GetGlobalVariablesInfo());
                    globalVars = globalInfo.map(v => "GLOBAL:" + v.name);
                } catch(e) {}
            }

            return {
                success: true,
                variables: variables,
                global_variables: globalVars,
                count: variables.length + globalVars.length
            };
        } catch(e) {
            return {success: false, error: e.toString()};
        }
    }

    async GetVariableValue(varName, noTruncate = true)
    {
        try {
            // Use Inspector's executeExpression if available
            if(typeof App !== 'undefined' && App.Inspector && App.Inspector.utils && App.Inspector.utils.executeExpression) {
                // noTruncate: true gets full value (important for large data like screenshots)
                let result = await App.Inspector.utils.executeExpression(varName, {isVariable: true, noTruncate: noTruncate});
                if(result.error) {
                    return {success: false, error: result.error, name: varName};
                }
                return {success: true, name: varName, value: result.result, type: typeof result.result};
            }

            // Fallback: use BrowserAutomationStudio_ExecuteSyncCode
            if(typeof BrowserAutomationStudio_ExecuteSyncCode === 'function') {
                let code = `_execute_sync_result("-BAS-EXECUTESYNC-ID-", {"value": ${varName}})`;
                let response = await BrowserAutomationStudio_ExecuteSyncCode(code, 5000);
                if(response.was_timeout) {
                    return {success: false, error: "Timeout", name: varName};
                }
                let parsed = JSON.parse(response.result);
                return {success: true, name: varName, value: parsed.value, type: typeof parsed.value};
            }

            return {success: false, error: "No method available to get variable value"};
        } catch(e) {
            return {success: false, error: e.toString(), name: varName};
        }
    }

    // ============= RESOURCES =============

    GetResourcesList()
    {
        try {
            let resources = [];

            // Parse resources from code using extract_resources pattern
            if(typeof _CodeContainer !== 'undefined' && _CodeContainer.GetCode) {
                let code = _CodeContainer.GetCode();
                let regexp = /RCreate\("([^"]+)"/g;
                let matches;
                while((matches = regexp.exec(code)) !== null) {
                    if(!resources.includes(matches[1])) {
                        resources.push(matches[1]);
                    }
                }
            }

            return {
                success: true,
                resources: resources,
                count: resources.length
            };
        } catch(e) {
            return {success: false, error: e.toString()};
        }
    }

    async GetResourceValue(resourceName)
    {
        try {
            // Use ScriptWorker to get resource info
            if(typeof ScriptWorker !== 'undefined') {
                let totalLength = ScriptWorker.GetTotalLength(resourceName);
                let currentIndex = ScriptWorker.GetCurrentIndex ? ScriptWorker.GetCurrentIndex(resourceName) : 0;

                // Get current value
                let currentValue = null;
                if(totalLength > 0) {
                    currentValue = ScriptWorker.GetAtIndex(resourceName, currentIndex);
                }

                return {
                    success: true,
                    name: resourceName,
                    total_length: totalLength,
                    current_index: currentIndex,
                    current_value: currentValue
                };
            }

            // Fallback: use executeExpression with resource syntax
            if(typeof App !== 'undefined' && App.Inspector && App.Inspector.utils && App.Inspector.utils.executeExpression) {
                let result = await App.Inspector.utils.executeExpression(`{{${resourceName}}}`, {});
                return {
                    success: true,
                    name: resourceName,
                    value: result.result
                };
            }

            return {success: false, error: "ScriptWorker not available", name: resourceName};
        } catch(e) {
            return {success: false, error: e.toString(), name: resourceName};
        }
    }

    // ============= EVAL EXPRESSION =============

    async EvalExpression(expression)
    {
        try {
            if(typeof App !== 'undefined' && App.Inspector && App.Inspector.utils && App.Inspector.utils.executeExpression) {
                let result = await App.Inspector.utils.executeExpression(expression, {noTruncate: true});
                if(result.error) {
                    return {success: false, error: result.error, expression: expression};
                }
                return {success: true, expression: expression, result: result.result, type: typeof result.result};
            }

            // Fallback
            if(typeof BrowserAutomationStudio_ExecuteSyncCode === 'function') {
                let code = `
                    try {
                        _execute_sync_result("-BAS-EXECUTESYNC-ID-", {"result": (${expression})})
                    } catch(e) {
                        _execute_sync_result("-BAS-EXECUTESYNC-ID-", {"error": e.message})
                    }
                `;
                let response = await BrowserAutomationStudio_ExecuteSyncCode(code, 10000);
                if(response.was_timeout) {
                    return {success: false, error: "Timeout", expression: expression};
                }
                let parsed = JSON.parse(response.result);
                if(parsed.error) {
                    return {success: false, error: parsed.error, expression: expression};
                }
                return {success: true, expression: expression, result: parsed.result, type: typeof parsed.result};
            }

            return {success: false, error: "No eval method available"};
        } catch(e) {
            return {success: false, error: e.toString(), expression: expression};
        }
    }

    // ============= LEGACY SUPPORT =============

    async HandleLegacyAddActions(Message)
    {
        let Result = [];
        let isAuto = Message.type == "add-actions-group-auto";

        if(!isAuto) {
            App.insertion.toggle("clipboard", false);
            if(App.insertion.toggle("helper", true)) {
                App.notification.show($t("toast.insertion"));
                this.SendMessage("wait-for-insertion", 0, null);

                let canceled = await new Promise(resolve => {
                    this.#cancel = () => resolve(true);
                    $(document).one("keydown", (e) => {
                        if(e.keyCode === 27) resolve(true);
                    });
                    $(document).one("click", ".main", (e) => {
                        if(!e.target.closest('.tool-div')) resolve(true);
                    });
                    $(document).one("click", ".toolinsertdata", () => resolve(false));
                });

                App.notification.hide();
                App.insertion.toggle("helper", false);

                if(canceled) return;
            }
        } else {
            _MainView.model.attributes["insert_index"] = _TaskCollection.length;
            _MainView.model.attributes["insert_parent"] = 0;
            _MainView.UpdateInsertDataInterface();
        }

        for(let DataItem of Message.data) {
            let ActionIds = await this.BulkAddActionsPart(DataItem.actions, DataItem.color);
            Result.push({
                "group-id": DataItem["group-id"],
                "action-ids": ActionIds,
                "is-success": ActionIds.length > 0
            });
        }
        this.SendMessage("add-actions-group-result", Message.id, Result);
    }

    async BulkAddActionsPart(ListOfActions, Color)
    {
        window.App.overlay.show();

        if(!Color || typeof(this.COLORS_MAP[Color]) == "undefined") {
            Color = "white";
        }
        Color = this.COLORS_MAP[Color];
        ListOfActions.forEach(Action => Action.color = Color);

        try {
            let Ids = _MainView.PasteFinal(JSON.stringify(ListOfActions), true);

            await new Promise(resolve => {
                let AllInsertedTasks = Ids.map(Id => FindTaskById(Id));
                _ActionUpdater.model.once('finish', resolve).set({
                    tasks: App.utils.filterTasks('all', AllInsertedTasks),
                    isStarted: true,
                });
            });

            if(_ActionUpdater.model.isSuccessfulUpdate()) {
                window.App.overlay.hide();
                return Ids;
            } else {
                await this.DeleteActions(Ids);
                window.App.overlay.hide();
                return [];
            }
        } catch(e) {
            window.App.overlay.hide();
            return [];
        }
    }
}
