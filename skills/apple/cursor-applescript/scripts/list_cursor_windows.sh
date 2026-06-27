#!/usr/bin/env bash
# List open Cursor workspaces (Window/窗口 menu) and the current front tab title.
set -euo pipefail

cursor_running() {
  pgrep -x Cursor >/dev/null 2>&1 || pgrep -f '/Applications/Cursor\.app/Contents/MacOS/Cursor' >/dev/null 2>&1
}

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "error: macOS only" >&2
  exit 1
fi

if ! cursor_running; then
  echo "error: Cursor is not running" >&2
  exit 1
fi

osascript <<'APPLESCRIPT'
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

on isWorkspaceMenuItem(itemName)
	if itemName is missing value then return false
	if itemName is "" then return false
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

tell application "System Events"
	if not (exists process "Cursor") then
		error "Cursor is not running" number -51
	end if
	tell process "Cursor"
		set frontmost to true
		set frontTabTitle to ""
		try
			set frontTabTitle to name of front window as text
		end try

		set menuBarItemRef to my getWindowMenuBarItem()
		click menuBarItemRef
		delay 0.15
		set windowMenu to menu 1 of menuBarItemRef

		set output to "workspaces (Window/窗口 menu):" & linefeed
		repeat with menuItemRef in menu items of windowMenu
			try
				set itemName to name of menuItemRef as text
				if my isWorkspaceMenuItem(itemName) then
					set marker to " "
					try
						set markChar to value of attribute "AXMenuItemMarkChar" of menuItemRef
						if markChar is not missing value and markChar is not "" then set marker to "*"
					end try
					set output to output & marker & " " & itemName & linefeed
				end if
			end try
		end repeat

		set output to output & linefeed & "open windows (tab titles, fallback only):" & linefeed
		repeat with w in windows
			try
				set output to output & "  - " & (name of w as text) & linefeed
			end try
		end repeat

		key code 53
		set output to output & linefeed & "front tab title: " & frontTabTitle & linefeed & linefeed & "note: use workspace folder names from Window menu; tab titles are fallback hints only."
		return output
	end tell
end tell
APPLESCRIPT
