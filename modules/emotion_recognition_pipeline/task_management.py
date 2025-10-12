import glob
import random
import os
import json
from PIL import Image


TASKS_JSON_PATH = "./data/tasks.json"
TASKS_HINTS_PATH = "./data/hints/"
PELMEN_PATH = './data/hint_for_sure.jpg'


class TaskManager:
    '''
    Позволяет формировать задания для пользователя
    '''
    def __init__(self, tasks_path=TASKS_JSON_PATH, hints_path=TASKS_HINTS_PATH):
        self.tasks_path = tasks_path
        self.hints_path = hints_path

        self.tasks = None
        with open(self.tasks_path, "r") as file: 
            self.tasks = json.load(file)
        self.categories = list(self.tasks.keys())

        self.hints_examples = {}
        for hint in os.listdir(hints_path):
            img_path = os.path.join(hints_path, hint, os.listdir(os.path.join(hints_path, hint))[0])
            self.hints_examples[hint.replace("_", " ")] = img_path


    def get_random_task(self) -> tuple[str, str, Image.Image]:
        '''
        Возвращает категорию позирования, саму формулировку позирования и фото-подсказку для прояснения
        '''
        category = random.choice(self.categories)
        task = random.choice(self.tasks[category])
        try:
            hint = Image.open(self.hints_examples[task])
        except:
            hint = Image.open(PELMEN_PATH)
        return category, task, hint