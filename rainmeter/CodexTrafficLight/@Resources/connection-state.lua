-- Local receipt time is authoritative for connectivity; server task time can be old.
-- Keep this file ASCII: Rainmeter's Lua API may use the Windows ANSI code page.
-- Bang variable references are expanded by Rainmeter from the Unicode skin.
function Initialize()
    lastSuccess = 0
    failed = true
    offline = true
end

local function showState(isOffline)
    SKIN:Bang('!SetVariable', 'ConnectionOnline', isOffline and '0' or '1')
    SKIN:Bang('!HideMeterGroup', 'StatusLights')
    if isOffline then
        SKIN:Bang('!ShowMeter', 'MeterIdleLight')
        SKIN:Bang('!SetOption', 'MeterStatusText', 'Text', '#StatusOfflineText#')
        SKIN:Bang('!SetOption', 'MeterRailTaskValue', 'Text', '#StatusOfflineText#')
        SKIN:Bang('!SetOption', 'MeterRailHealthValue', 'Text', 'OFF')
        SKIN:Bang('!SetOption', 'MeterRailHealthNode', 'Shape', 'Ellipse 0,0,(3*#SkinScale#) | Fill Color #GrayColor# | StrokeWidth 0')
    else
        local code = math.floor(SKIN:GetMeasure('MeasureStatus'):GetValue())
        local meters = {'MeterIdleLight', 'MeterRunningLight', 'MeterWaitingLight', 'MeterSuccessLight', 'MeterErrorLight'}
        local labels = {'#StatusIdleText#', '#StatusRunningText#', '#StatusWaitingText#', '#StatusSuccessText#', '#StatusErrorText#'}
        code = math.max(0, math.min(4, code))
        SKIN:Bang('!ShowMeter', meters[code + 1])
        SKIN:Bang('!SetOption', 'MeterStatusText', 'Text', labels[code + 1])
        SKIN:Bang('!SetOption', 'MeterRailTaskValue', 'Text', labels[code + 1])
        -- The native WebParser substitute returns ASCII, independent of code page.
        local good = SKIN:GetMeasure('MeasureHealthState'):GetStringValue() == '1'
        SKIN:Bang('!SetOption', 'MeterRailHealthValue', 'Text', good and 'OK' or 'ERR')
        SKIN:Bang('!SetOption', 'MeterRailHealthNode', 'Shape', 'Ellipse 0,0,(3*#SkinScale#) | Fill Color ' .. (good and '#GreenColor#' or '#RedColor#') .. ' | StrokeWidth 0')
    end
end

function Success()
    lastSuccess = os.time()
    failed = false
    offline = false
    showState(false)
    Update()
end

function Failure()
    failed = true
    Update()
end

function Update()
    local age = lastSuccess == 0 and 999999 or math.max(0, os.time() - lastSuccess)
    local timeout = tonumber(SKIN:GetVariable('OfflineAfterSeconds', '10')) or 10
    offline = age >= math.max(3, timeout)
    if offline then showState(true) end
    local last = lastSuccess == 0 and '#ConnectionNeverText#' or ('#ConnectionLastText# ' .. os.date('%H:%M:%S', lastSuccess))
    local label = (offline and '#ConnectionOfflineText# ' or (failed and '#ConnectionRetryText# ' or '#ConnectionOnlineText# ')) .. last
    SKIN:Bang('!SetOption', 'MeterConnection', 'Text', label)
    SKIN:Bang('!SetOption', 'MeterConnection', 'FontColor', offline and '#LowQuotaTextColor#' or '#MutedTextColor#')
    SKIN:Bang('!UpdateMeter', '*')
    SKIN:Bang('!Redraw')
    return age
end
