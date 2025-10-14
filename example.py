from modules.emotion_recognition_pipeline.clip import initialize_model
from modules.emotion_recognition_pipeline.task_management import TaskManager

from PIL import Image
import os


###### Это отработает один раз при старте приложения ######
model = initialize_model()
tm = TaskManager()
###########################################################

#### ВСЕ ЧТО ИДЕТ НИЖЕ МОЖЕТ РАБОТАТЬ В ЦИКЛЕ - ПОКА АКТИВНО ПРИЛОЖЕНИЕ ####

# Формируем задание для пользователя
category, task, hint = tm.get_random_task()

# Это заглушка. Тут как-то просто получили набор картинок от юзеров. Формат Image.Image
images = [
    Image.open(os.path.join('./data/images', image_path)).convert("RGB")
    for image_path in os.listdir('./data/images/')
    if image_path.endswith('.jpg')
]

# Добавили картинку-идеал в пул картинок тоже
images.append(hint)
#######################################################################################

# Основная функция - что вернет смотри описание метода
# report[-1] - это кортеж для картинки hint и ее скор. Это можно обыграть тоже
report = model.play_duel(task, images)

for img, score in report:
    print(img, score)

# Дальше на усмотрение что с этим делать






