# PV-Aggregator

###What it does:
- collectes active power and meter readings from a number of huawei sun2000 units defined in config.yaml
- aggregates the individual readings to a total
- provides the total number via a modbus-tcp server
- provides the detailed results on a flask webserver as json on  http://xxx.xxx.xxx.xxx:5000/readings


###features:
- Error handling for measurement readings:
- reports back last successful reading in case of failed reading (or 0, if no succesful reading before)
- increments and reports total number of failed readings (for tracking reliability)
- trys reconnecting to inverter if reading fails
- modbus-tcp server, flask-webserver, and main data-update looop running in seperated threads with save data storage (lock)
- rolling logs to folder /temp/logs 
- graceful shutdown running servers as deamons and signal handler

###Modbus-tcp Register-mapping:
- port: 502
- Register 0-1: aggregated power output (kw); Type=UINT32
- Register 2-3: aggreagated meter readings (kWh); Type=UINT32
- Register 4: Number of succesfull measurement readings (-); type=UINT16 
- (value should be 7 inverters x 2 measurements =  14 --> if it is smaller it indicates that some measurements were not successful)



