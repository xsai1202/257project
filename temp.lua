local ssid = "NETGEAR61"
local password = "windyvalley967"
dtype = 1
pin = 1

ds18b20=require("ds")
ds18b20.init_18b20()
function update() 
	print("start read")
	ds18b20.get_tmp(function (t)
		-- Float firmware using this example
		print("Temperature:"..t)
        socket:send(20180, sip, struct.pack("Bf", dtype, t))
	end)
end

socket = net.createUDPSocket()
connected = false

local station_cfg = {}
station_cfg.ssid = ssid
station_cfg.pwd = password
station_cfg.save = true
wifi.sta.config(station_cfg)

socket:on(
    "receive",
    function(s, data, port, ip)
        print(string.format("Ack '%s' from %s:%d", data, ip, port))
        connected = true
        sip = ip
    end
)

boardtmr = tmr.create()
boardtmr:alarm(
    1000,
    tmr.ALARM_AUTO,
    function()
        if connected then
            boardtmr:unregister()
			boardtmr:alarm(
			2000,
			tmr.ALARM_AUTO,
			update)
            return
        end
		if wifi.sta.getip() then
			local dip=wifi.sta.getbroadcast()
			print(string.format("send to address / port: %s:%d", dip, 20180))
			socket:send(20180, dip, struct.pack("BBI4", 0, dtype, node.chipid()))
		end
    end
)

