-- See https://wiki.hypr.land/Configuring/Basics/Monitors/
-- List current monitors and supported resolutions with: hyprctl monitors all
local omarchy_gdk_scale = 1
local omarchy_monitor_scale = "auto"
hl.env("GDK_SCALE", tostring(omarchy_gdk_scale))

-- Configure specific monitors: LG UltraGear on the right (primary), ViewSonic on the left
hl.monitor({ output = "HDMI-A-1", mode = "1920x1080@144", position = "2560x0", scale = 1 })
hl.monitor({ output = "DP-1", mode = "2560x1080@75", position = "0x0", scale = 1 })
