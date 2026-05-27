with open('hospital/auth/permissions_map.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = "HMS/RoomOccupencyReport/?(\\?.*)?$': 'HMS-P-ROR',"
new = ("HMS/RoomOccupencyReport/?(\\?.*)?$': 'HMS-P-ROR',\n"
       "    r'^/_b_a_c_k_e_n_d/HMS/PreDayRoomOccupancyReport/?(\\?.*)?$': 'HMS-P-ROR',")

if old in content:
    content = content.replace(old, new, 1)
    with open('hospital/auth/permissions_map.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Done — PreDayRoomOccupancyReport permission added")
else:
    print("String not found, showing context:")
    idx = content.find('RoomOccupen')
    print(repr(content[idx:idx+100]))
