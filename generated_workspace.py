import os

file_path = 'ghost_data.json'

if not os.path.exists(file_path):
    print(f"The file '{file_path}' does not exist. Please check the file path and try again.")
else:
    with open(file_path, 'r') as file:
        content = file.read()
        print(content)