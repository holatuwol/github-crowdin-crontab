#!/usr/bin/env python
import json
import os
import shutil


def get_articles(dir):
    files = {}

    for file in os.listdir(dir):
        if file[-5:] == ".json":
            with open(os.path.join(dir, file), "r") as f:
                files[file] = json.load(f)

    return files


uat_articles = get_articles("../learn-uat-xliff/en/")
prd_articles = get_articles("../learn-xliff/en/")

uat_files_by_title = {article["title"]: file for file, article in uat_articles.items()}
prd_files_by_title = {article["title"]: file for file, article in prd_articles.items()}

for title in uat_files_by_title:
    if title not in prd_files_by_title:
        continue

    uat_html_file = uat_files_by_title[title][:-5] + ".html"
    prd_html_file = prd_files_by_title[title][:-5] + ".html"

    prd_file = os.path.join("../learn-xliff/ja/", prd_html_file)
    uat_file = os.path.join("../learn-uat-xliff/ja/", uat_html_file)

    shutil.copyfile(prd_file, uat_file)
