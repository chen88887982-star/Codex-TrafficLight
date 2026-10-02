-- Local receipt time is authoritative for connectivity; server task time can be old.
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
        SKIN:Bang('!SetOption', 'MeterStatusText', 'Text', '离线')
        SKIN:Bang('!SetOption', 'MeterRailTaskValue', 'Text', '离线')
        SKIN:Bang('!SetOption', 'MeterRailHealthValue', 'Text', 'OFF')
        SKIN:Bang('!SetOption', 'MeterRailHealthNode', 'Shape', 'Ellipse 0,0,(3*#SkinScale#) | Fill Color #GrayColor# | StrokeWidth 0')
    else
        local code = math.floor(SKIN:GetMeasure('MeasureStatus'):GetValue())
        local meters = {'MeterIdleLight', 'MeterRunningLight', 'MeterWaitingLight', 'MeterSuccessLight', 'MeterErrorLight'}
        local labels = {'空闲', '运行中', '等待确认', '已完成', '异常'}
        code = math.max(0, math.min(4, code))
        SKIN:Bang('!ShowMeter', meters[code + 1])
        SKIN:Bang('!SetOption', 'MeterStatusText', 'Text', labels[code + 1])
        SKIN:Bang('!SetOption', 'MeterRailTaskValue', 'Text', labels[code + 1])
        local health = SKIN:GetMeasure('MeasureHealth'):GetStringValue()
        local good = string.find(health, '服务正常', 1, true) == 1
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
    local last = lastSuccess == 0 and '尚未成功连接' or ('上次 ' .. os.date('%H:%M:%S', lastSuccess))
    local label = (offline and '离线 · ' or (failed and '重试中 · ' or '已连接 · ')) .. last
    SKIN:Bang('!SetOption', 'MeterConnection', 'Text', label)
    SKIN:Bang('!SetOption', 'MeterConnection', 'FontColor', offline and '#LowQuotaTextColor#' or '#MutedTextColor#')
    SKIN:Bang('!UpdateMeter', '*')
    SKIN:Bang('!Redraw')
    return age
end
