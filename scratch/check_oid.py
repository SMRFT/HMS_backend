from bson import ObjectId
import datetime

oid = ObjectId("6afef55b36c64ea53d065839")
print("ObjectId generation time:", oid.generation_time)

oid_cc = ObjectId("6afef62136c64ea53d0658c7")
print("Cash counter doc ObjectId generation time:", oid_cc.generation_time)
