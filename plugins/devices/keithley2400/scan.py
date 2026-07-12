import pyvisa

rm = pyvisa.ResourceManager()

print("VISA backend:", rm)
print("Resources:")

for r in rm.list_resources():
    print(" ", r)