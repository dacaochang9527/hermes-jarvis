on run argv
	if (count of argv) < 1 or item 1 of argv is "" then
		error "Usage: osascript focus_cursor_window.scpt WORKSPACE_QUERY" number -50
	end if
	set workspaceQuery to item 1 of argv

	tell application "System Events"
		if not (exists process "Cursor") then
			error "Cursor is not running" number -51
		end if
	end tell

	tell application "Cursor" to activate
	delay 0.2

	-- Prefer real Cursor window titles first. On some macOS/Cursor states the
	-- Window menu exposes only system items (Minimize/Zoom/etc.), while the
	-- AX window title still carries "<tab> — <workspace>".
	set titleFallback to my focusByWindowTitle(workspaceQuery)
	if titleFallback is not "" then return titleFallback

	set workspaceNames to my listWorkspaceNames()
	if (count of workspaceNames) is 0 then
		error "No Cursor workspaces found in Window menu" number -55
	end if

	set exactMatches to my filterExactMatches(workspaceNames, workspaceQuery)
	set matchCount to count of exactMatches

	if matchCount is 1 then
		set targetWorkspace to item 1 of exactMatches
	else if matchCount is 0 then
		set partialMatches to my filterPartialMatches(workspaceNames, workspaceQuery)
		set partialCount to count of partialMatches
		if partialCount is 0 then
			set availableText to my joinLines(workspaceNames)
			if availableText is "" then set availableText to "(Window 菜单里没有工作区项；可能只有 Settings 窗或未打开项目主窗口)"
			error "No Cursor workspace matched query: " & workspaceQuery & linefeed & "Open workspaces:" & linefeed & availableText number -52
		end if
		if partialCount > 1 then
			set namesText to my joinLines(partialMatches)
			error "Workspace query matched multiple Cursor workspaces: " & workspaceQuery & linefeed & namesText number -53
		end if
		set targetWorkspace to item 1 of partialMatches
	else
		set namesText to my joinLines(exactMatches)
		error "Workspace query matched multiple Cursor workspaces: " & workspaceQuery & linefeed & namesText number -53
	end if

	my focusWorkspaceMenuItem(targetWorkspace)
	delay 0.25

	if not my isWorkspaceFront(targetWorkspace) then
		error "Failed to focus Cursor workspace '" & workspaceQuery & "' (expected '" & targetWorkspace & "' front)" number -54
	end if

	return targetWorkspace
end run

on getWindowMenuBarItem()
	tell application "System Events" to tell process "Cursor"
		repeat with menuBarItemRef in menu bar items of menu bar 1
			set itemName to name of menuBarItemRef as text
			if itemName is "Window" or itemName is "窗口" then
				return menuBarItemRef
			end if
		end repeat
	end tell
	error "Cursor Window menu not found (expected Window or 窗口)" number -56
end getWindowMenuBarItem

on getWindowMenu()
	tell application "System Events" to tell process "Cursor"
		set menuBarItemRef to my getWindowMenuBarItem()
		return menu 1 of menuBarItemRef
	end tell
end getWindowMenu

on listWorkspaceNames()
	tell application "System Events" to tell process "Cursor"
		set frontmost to true
		set menuBarItemRef to my getWindowMenuBarItem()
		click menuBarItemRef
		delay 0.15
		set windowMenu to menu 1 of menuBarItemRef
		set namesList to {}
		repeat with menuItemRef in menu items of windowMenu
			try
				set itemName to name of menuItemRef as text
				if my isWorkspaceMenuItem(itemName) then
					set end of namesList to itemName
				end if
			end try
		end repeat
		key code 53
	end tell
	return namesList
end listWorkspaceNames

on isWorkspaceMenuItem(itemName)
	if itemName is missing value then return false
	if itemName is "" then return false
	if itemName starts with "missing value" then return false

	set blockedNames to {"Minimize", "Minimize All", "Zoom", "Zoom All", "Fill", "Center", "Move & Resize", "Full Screen Tile", "Remove Window from Set", "Rename Window", "Show Previous Tab", "Show Next Tab", "Show Previous Window", "Show Next Window", "Bring All to Front", "Arrange in Front", "Switch Window...", "最小化", "全部最小化", "缩放", "全部缩放", "填充", "居中", "移动与调整大小", "全屏幕平铺", "移除窗口套组", "从组中移除窗口", "重新命名窗口", "显示上一个标签页", "显示下一个标签页", "显示上一个窗口", "显示下一个窗口", "全部置于顶层", "排在前面", "切换窗口…", "切换窗口..."}
	repeat with blockedName in blockedNames
		if itemName is blockedName then return false
	end repeat

	if itemName contains " — " then return false
	if itemName contains "..." then return false
	if itemName contains "…" then return false
	if itemName contains "⌘" then return false

	return true
end isWorkspaceMenuItem

on filterExactMatches(namesList, workspaceQuery)
	set hits to {}
	repeat with wsName in namesList
		if (wsName as text) is workspaceQuery then
			set end of hits to wsName as text
		end if
	end repeat
	return hits
end filterExactMatches

on filterPartialMatches(namesList, workspaceQuery)
	set hits to {}
	repeat with wsName in namesList
		set wsText to wsName as text
		if wsText contains workspaceQuery then
			set end of hits to wsText
		end if
	end repeat
	return hits
end filterPartialMatches

on joinLines(namesList)
	set namesText to ""
	repeat with wsName in namesList
		set namesText to namesText & "- " & (wsName as text) & linefeed
	end repeat
	return namesText
end joinLines

on focusWorkspaceMenuItem(targetWorkspace)
	tell application "System Events" to tell process "Cursor"
		set frontmost to true
		set menuBarItemRef to my getWindowMenuBarItem()
		click menuBarItemRef
		delay 0.15
		click menu item targetWorkspace of menu 1 of menuBarItemRef
	end tell
end focusWorkspaceMenuItem

on isWorkspaceFront(targetWorkspace)
	tell application "System Events" to tell process "Cursor"
		set frontmost to true
		set menuBarItemRef to my getWindowMenuBarItem()
		click menuBarItemRef
		delay 0.12
		set windowMenu to menu 1 of menuBarItemRef
		set isFront to false
		repeat with menuItemRef in menu items of windowMenu
			try
				set itemName to name of menuItemRef as text
				if itemName is targetWorkspace then
					try
						set markChar to value of attribute "AXMenuItemMarkChar" of menuItemRef
						if markChar is not missing value and markChar is not "" then set isFront to true
					end try
					exit repeat
				end if
			end try
		end repeat
		key code 53
	end tell
	return isFront
end isWorkspaceFront

on listCursorWindowTitles()
	set titles to {}
	tell application "System Events" to tell process "Cursor"
		set frontmost to true
		repeat with w in windows
			try
				set end of titles to name of w as text
			end try
		end repeat
	end tell
	return titles
end listCursorWindowTitles

on scoreWindowTitle(winTitle, workspaceQuery)
	if winTitle is missing value or winTitle is "" then return -1
	if winTitle starts with "Cursor Settings — " then return 1
	if winTitle ends with (" — " & workspaceQuery) then return 10
	if winTitle contains workspaceQuery then return 5
	return -1
end scoreWindowTitle

on focusByWindowTitle(workspaceQuery)
	set bestTitle to ""
	set bestScore to -1
	set settingsTitle to ""
	repeat with winTitle in my listCursorWindowTitles()
		set winText to winTitle as text
		if winText starts with "Cursor Settings — " and winText contains workspaceQuery then
			set settingsTitle to winText
		end if
		set score to my scoreWindowTitle(winText, workspaceQuery)
		if score > bestScore then
			set bestScore to score
			set bestTitle to winText
		end if
	end repeat

	if bestScore < 0 then
		if settingsTitle is not "" then
			error "Only Cursor Settings window found for '" & workspaceQuery & "'. Open the project editor window (not Settings) and retry." number -57
		end if
		return ""
	end if

	if bestTitle starts with "Cursor Settings — " then
		error "Only Cursor Settings window found for '" & workspaceQuery & "'. Open the project editor window (not Settings) and retry." number -57
	end if

	tell application "System Events" to tell process "Cursor"
		set frontmost to true
		repeat with w in windows
			if (name of w as text) is bestTitle then
				perform action "AXRaise" of w
				exit repeat
			end if
		end repeat
	end tell
	delay 0.2
	return workspaceQuery
end focusByWindowTitle
