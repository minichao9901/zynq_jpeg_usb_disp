connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "APU"}
puts [mrd -address-space AP0 -force 0xE0002140 44]
puts [mrd -address-space AP0 -force 0xF8000700 40]
puts [mrd -address-space AP0 -force 0xE000A040 4]
disconnect
exit
