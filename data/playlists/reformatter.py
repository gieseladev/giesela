import json

while True:
    data = input("Filename?")
    if data.lower() in ["end", "exit", "stop"]:
        break
    with open(data + ".txt", "r") as f:
        d = f.read()

    o = []
    for x in d.split("\n;\n"):
        obj = json.loads(x)
        o.append(obj)
    json.dump(o, open(data + ".gpl", "w+"))
