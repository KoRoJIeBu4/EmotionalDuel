import json
import random


PATH = "./data/tasks.json"

class TaskManager:
    def __init__(self, path=PATH):
        self.path = path
        self.tasks = None
        with open(self.path, "r") as file: 
            self.tasks = json.load(file)

    
    def get_random_task(self):
        print(self.tasks.keys())
        category = random.choice(self.tasks.keys())
        task = random.choice(self.tasks[category])
        return category, task


tm = TaskManager()

print(tm.get_random_task())





