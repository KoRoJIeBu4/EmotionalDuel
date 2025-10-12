from icrawler.builtin import GoogleImageCrawler, BingImageCrawler
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import json
import logging
import glob


logging.getLogger("icrawler").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)


TASKS_PATH = './data/tasks.json'


def download_images(query: str, limit: int = 300, base_dir: str = "dataset"):
    """
    Скачивает изображения по запросу в отдельную папку
    """
    output_path = os.path.join(base_dir, query.replace(" ", "_"))
    os.makedirs(output_path, exist_ok=True)

    full_query = f"{query} person"
    
    crawler = GoogleImageCrawler(
        feeder_threads=1,
        parser_threads=1,
        downloader_threads=4,
        storage={"root_dir": output_path}
    )

    filters = dict(
        size=">640x480",
        type="photo",
        color="color"
    )

    crawler.crawl(
        keyword=full_query,
        filters=filters,
        offset=0,
        max_num=limit,
        min_size=(256, 256),
        file_idx_offset=0
    )

    n_downloaded = len(glob.glob(os.path.join(output_path, "*")))
    print(f"[OK] {query} — {n_downloaded}/{limit} images saved to {output_path}")


def download_all_impl(tasks: list[str], limit: int = 100, base_dir: str = "dataset", max_workers: int = 4):
    """
    Скачивает изображения для всех задач многопоточно
    """
    os.makedirs(base_dir, exist_ok=True)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(download_images, task, limit, base_dir) for task in tasks]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as error:
                print(f"[ERROR] {error}")


def download_all(limit: int = 300, base_dir: str = "dataset", max_workers: int = 4):
    """
    Загружает все tasks из JSON файла
    """
    with open(TASKS_PATH, mode="r", encoding="utf-8") as file:
        tasks = []
        for category, items in json.load(file).items():
            tasks.extend(items)

    download_all_impl(tasks, limit, base_dir, max_workers)


if __name__ == "__main__":
    code = input("Are you want to download [enter <QWERTY> if yes]: ")
    if code == "QWERTY":
        download_all(limit=300, base_dir="dataset", max_workers=4)
    total_images = 0
    for subdir in os.listdir("dataset"):
        current = 0
        path = os.path.join("dataset", subdir)
        if os.path.isdir(path):
            current += len([f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))])
        if current < 50:
            print(f"Not enough for {subdir}: accounts {current}")
        total_images += current
    print(f"[TOTAL IMAGES] = {total_images}")
