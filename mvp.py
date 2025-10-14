#####################################
##### ЭТО ПРИМЕР ВЗАИМОДЕЙСТВИЯ #####
#####################################
from modules.emotion_recognition_pipeline.clip import initialize_model
from modules.emotion_recognition_pipeline.task_management import TaskManager

from PIL import Image
import os
import matplotlib.pyplot as plt
import numpy as np


model = initialize_model()
tm = TaskManager()

print("🟢 Модель и менеджер задач инициализированы.")
print("Введите 'stop', чтобы завершить.\n")

while True:
    category, task, hint = tm.get_random_task()
    print(f"\n📋 Новое задание: {task}")
    print(f"Категория: {category}")
    print(f"Подсказка (образец): добавлена в сравнение.\n")

    ready = input("Готов? (y/n или stop): ").strip().lower()
    if ready == "stop":
        print("\n🛑 Завершение работы.")
        break
    if ready != "y":
        print("⏸ Пропускаем это задание.\n")
        continue

    images = [
        Image.open(os.path.join('./data/images', image_path)).convert("RGB")
        for image_path in os.listdir('./data/images/')
        if image_path.endswith('.jpg')
    ]

    if not images:
        print("⚠️  В папке ./data/images/ нет картинок.")
        continue

    images.append(hint)

    print("🔍 Анализ изображений...")
    report = model.play_duel(task, images)
    scores = np.array([score for _, score in report])

    if scores.max() > scores.min():
        scores_norm = (scores - scores.min()) / (scores.max() - scores.min())
    else:
        scores_norm = np.zeros_like(scores)

    report_norm = [(img, s) for (img, _), s in zip(report, scores_norm)]

    hint_idx = len(report_norm) - 1
    hint_score = report_norm[hint_idx][1]

    report_sorted = sorted(report_norm, key=lambda x: x[1], reverse=True)

    cols = min(5, len(report_sorted))
    rows = (len(report_sorted) + cols - 1) // cols
    plt.figure(figsize=(3 * cols, 3 * rows))

    for idx, (img, score) in enumerate(report_sorted):
        plt.subplot(rows, cols, idx + 1)
        plt.imshow(img)
        plt.axis("off")

        if img == hint:
            plt.title(f"⭐ Образец ({score:.2f})", fontsize=9, color="gold")
            plt.gca().spines[:].set_color("gold")
            plt.gca().spines[:].set_linewidth(3)
        else:
            plt.title(f"{score:.2f}", fontsize=9)

        if score > hint_score and img != hint:
            plt.gca().spines[:].set_color("lime")
            plt.gca().spines[:].set_linewidth(2)

    plt.suptitle(f"Task: {task}", fontsize=14)
    plt.tight_layout()
    plt.show()

    print(f"⭐ Score образца: {hint_score:.3f}")
    winners = sum(1 for _, s in report_norm if s > hint_score)
    print(f"🏆 Картинок, превзошедших образец: {winners}/{len(report_norm) - 1}")

    cont = input("\nПродолжить к следующему заданию? (y/n): ").strip().lower()
    if cont != "y":
        print("\n🛑 Завершение работы.")
        break


