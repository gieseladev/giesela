import os


def count_lines(location):
    print(location)
    local_score = 0
    for file in os.listdir(location):
        combined_loc = "{}/{}".format(location,
                                      file) if location is not None else file
        if os.path.isfile(combined_loc):
            if file[-3:] == ".py":
                local_score += sum(1 for line in open(combined_loc, "r"))
        elif not file.startswith("."):
            local_score += count_lines(combined_loc)

    return local_score

print(count_lines(None))
