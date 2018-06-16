local ssid = "Apt3323"
local password = "Yanwang3Gaosiji"
dtype = 2
pin = 1

function update() 
	local status, temp, humi, temp_dec, humi_dec = dht.read(pin)
	if status == dht.OK then
		-- Float firmware using this example
		print("DHT Temperature:"..temp..";".."Humidity:"..humi)
        socket:send(20180, sip, struct.pack("Bf", dtype, humi))

	elseif status == dht.ERROR_CHECKSUM then
		print( "DHT Checksum error." )
	elseif status == dht.ERROR_TIMEOUT then
		print( "DHT timed out." )
	end
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
		tmr.create()
		boardtmr:alarm(
			1000,
			tmr.ALARM_AUTO,
			update)
    end
)

boardtmr = tmr.create()
boardtmr:alarm(
    1000,
    tmr.ALARM_AUTO,
    function()
        if connected then
            boardtmr:unregister()
            return
        end
		if wifi.sta.getip() then
			local dip=wifi.sta.getbroadcast()
			print(string.format("send to address / port: %s:%d", dip, 20180))
			socket:send(20180, dip, struct.pack("BBI4", 0, dtype, node.chipid()))
		end
    end
)

