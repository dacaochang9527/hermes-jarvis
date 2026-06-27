on run argv
	if (count of argv) < 1 then
		error "Usage: osascript switch_cursor_model.scpt MODEL_NAME" number -50
	end if
	set modelName to item 1 of argv

	tell application "System Events"
		if not (exists process "Cursor") then
			error "Cursor is not running" number -51
		end if

		tell process "Cursor" to set frontmost to true
		delay 0.25

		-- Dismiss stray dialogs / panels
		repeat 2 times
			key code 53
			delay 0.15
		end repeat

		-- CRITICAL: leave integrated terminal before Cmd+L.
		key code 53
		delay 0.15
		keystroke "1" using command down
		delay 0.35

		-- CRITICAL: focus Agent chat, not the code editor
		keystroke "l" using command down
		delay 0.6

		keystroke "/" using command down
		delay 0.8

		keystroke "v" using command down
		delay 0.25
		keystroke return
	end tell

	return "submitted model picker search for: " & modelName
end run
